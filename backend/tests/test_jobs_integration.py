"""Integration tests for the Postgres-backed job queue (app.pipeline.jobs), against a
real PostgreSQL instance. Same skip-if-no-database convention as
test_reprocessing_service_integration.py.

The concurrent-claim tests use TWO separate connections deliberately — SKIP LOCKED's
whole behavior is about what one transaction can see of another transaction's
in-flight, uncommitted row lock, which a single connection can never actually exercise
regardless of how the test code is sequenced.

Isolation note, kept because it was earned the hard way: _queue_job commits (a second
connection must actually see the row to race for it), so a test's own rollback can
never undo it. Two designs were tried and rejected before landing on the one below:

  1. A fixture that deletes tracked ids at teardown. Failed with a real deadlock:
     pytest tears fixtures down in the REVERSE of setup order, so the cleanup
     fixture's DELETE ran BEFORE `conn`'s rollback released its row lock, and the
     DELETE blocked forever on a lock only a later teardown step would free.
  2. An explicit `_finish()` call at the end of each test body, after that test's own
     rollback. Fixed the deadlock, but not the cascading failure: a test that fails
     its OWN assertion never reaches `_finish()`, leaving its committed row behind to
     pollute every later test's "the next queued job" query in the same run.

The fix that actually holds: wipe the table at the START of every test, before that
test's own connections even exist to conflict with. This relies on one guarantee
pytest actually gives — a test's fixtures are fully torn down before the next test's
fixtures are set up, even after an assertion failure (not after a hard process kill,
which is why a stray timeout during development required one manual TRUNCATE, done
directly against the database rather than adding more test-harness machinery for a
kill-behavior these tests never intend to survive).
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from app.pipeline.jobs import claim_next_job, complete_job, reap_expired_leases

DATABASE_URL = os.environ.get("CR_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="CR_TEST_DATABASE_URL not set")


@pytest.fixture(autouse=True)
def _wipe_ingestion_jobs():
    with psycopg.connect(DATABASE_URL, autocommit=True) as admin:
        admin.execute("DELETE FROM ingestion_jobs")


@pytest.fixture()
def conn():
    connection = psycopg.connect(DATABASE_URL, autocommit=False)
    yield connection
    connection.rollback()
    connection.close()


@pytest.fixture()
def second_conn():
    """A genuinely separate connection/session, needed to prove SKIP LOCKED behavior
    that a single connection's sequential statements cannot demonstrate."""
    connection = psycopg.connect(DATABASE_URL, autocommit=False)
    yield connection
    connection.rollback()
    connection.close()


def _uuid() -> str:
    return str(uuid.uuid4())


def _queue_job(conn, job_type: str = "extract") -> str:
    job_id = _uuid()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ingestion_jobs (id, job_type, status) VALUES (%s, %s, 'queued')",
            (job_id, job_type),
        )
    conn.commit()  # the other connection must actually see this row to race for it
    return job_id


def test_claim_returns_none_when_queue_is_empty(conn):
    assert claim_next_job(conn, worker_id="w1") is None


def test_claim_sets_running_locked_by_and_a_future_lease(conn):
    job_id = _queue_job(conn)

    claimed = claim_next_job(conn, worker_id="worker-a", lease_seconds=600)

    assert claimed is not None
    assert str(claimed.id) == job_id
    assert claimed.attempts == 1

    with conn.cursor() as cur:
        cur.execute(
            "SELECT status, locked_by, lease_until > now(), attempts FROM ingestion_jobs WHERE id = %s",
            (job_id,),
        )
        status, locked_by, lease_in_future, attempts = cur.fetchone()
        assert status == "running"
        assert locked_by == "worker-a"
        assert lease_in_future is True
        assert attempts == 1


def test_a_queued_job_locked_by_an_uncommitted_transaction_is_invisible_to_a_second_worker(conn, second_conn):
    """This is the actual SKIP LOCKED proof: connection A claims the only job and does
    NOT commit. Connection B, racing for the same job, must get None — not block
    forever waiting for A's lock, and not double-claim the row."""
    job_id = _queue_job(conn)

    claimed_by_a = claim_next_job(conn, worker_id="worker-a")
    assert claimed_by_a is not None
    assert str(claimed_by_a.id) == job_id
    # deliberately NOT committing `conn` yet — the row lock is still held

    claimed_by_b = claim_next_job(second_conn, worker_id="worker-b")
    assert claimed_by_b is None  # skipped, not blocked, not double-claimed


def test_two_queued_jobs_two_workers_each_gets_a_different_one(conn, second_conn):
    job_1 = _queue_job(conn, job_type="ocr")
    job_2 = _queue_job(conn, job_type="extract")

    claimed_by_a = claim_next_job(conn, worker_id="worker-a")
    claimed_by_b = claim_next_job(second_conn, worker_id="worker-b")

    assert claimed_by_a is not None and claimed_by_b is not None
    assert {str(claimed_by_a.id), str(claimed_by_b.id)} == {job_1, job_2}


def test_reap_returns_an_expired_lease_to_queued_and_clears_lock_fields(conn):
    job_id = _queue_job(conn)
    claim_next_job(conn, worker_id="worker-that-crashed", lease_seconds=600)

    # Simulate the passage of time past the lease without a crash actually needing to
    # happen in wall-clock time: directly backdate lease_until, exactly as if this
    # worker had been given a 10-minute lease and then vanished 11 minutes ago.
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE ingestion_jobs SET lease_until = %s WHERE id = %s",
            (datetime.now(timezone.utc) - timedelta(minutes=1), job_id),
        )

    reaped_count = reap_expired_leases(conn)
    assert reaped_count == 1

    with conn.cursor() as cur:
        cur.execute(
            "SELECT status, locked_by, lease_until FROM ingestion_jobs WHERE id = %s",
            (job_id,),
        )
        status, locked_by, lease_until = cur.fetchone()
        assert status == "queued"
        assert locked_by is None
        assert lease_until is None


def test_reap_does_not_touch_a_job_whose_lease_has_not_expired_yet(conn):
    job_id = _queue_job(conn)
    claim_next_job(conn, worker_id="worker-still-alive", lease_seconds=600)

    reaped_count = reap_expired_leases(conn)
    assert reaped_count == 0

    with conn.cursor() as cur:
        cur.execute("SELECT status, locked_by FROM ingestion_jobs WHERE id = %s", (job_id,))
        status, locked_by = cur.fetchone()
        assert status == "running"
        assert locked_by == "worker-still-alive"


def test_a_reaped_job_can_be_reclaimed_by_a_different_worker(conn):
    """The end-to-end crash-recovery story: claim, crash (backdate the lease), reap,
    reclaim — a different worker than the one that died."""
    job_id = _queue_job(conn)
    claim_next_job(conn, worker_id="worker-that-crashed", lease_seconds=600)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE ingestion_jobs SET lease_until = %s WHERE id = %s",
            (datetime.now(timezone.utc) - timedelta(minutes=1), job_id),
        )

    reap_expired_leases(conn)
    reclaimed = claim_next_job(conn, worker_id="worker-b-picks-it-up")

    assert reclaimed is not None
    assert str(reclaimed.id) == job_id
    assert reclaimed.attempts == 2  # bumped on both the original claim and the reclaim


def test_complete_job_marks_succeeded_and_clears_lock_fields(conn):
    job_id = _queue_job(conn)
    claim_next_job(conn, worker_id="worker-a")

    complete_job(conn, job_id, status="succeeded", result={"letters_created": 3})

    with conn.cursor() as cur:
        cur.execute(
            "SELECT status, result, locked_by, lease_until, finished_at IS NOT NULL FROM ingestion_jobs WHERE id = %s",
            (job_id,),
        )
        status, result, locked_by, lease_until, finished = cur.fetchone()
        assert status == "succeeded"
        assert result == {"letters_created": 3}
        assert locked_by is None
        assert lease_until is None
        assert finished is True


def test_complete_job_marks_failed_with_an_error_message(conn):
    job_id = _queue_job(conn)
    claim_next_job(conn, worker_id="worker-a")

    complete_job(conn, job_id, status="failed", error="OCR provider timeout")

    with conn.cursor() as cur:
        cur.execute("SELECT status, error FROM ingestion_jobs WHERE id = %s", (job_id,))
        status, error = cur.fetchone()
        assert status == "failed"
        assert error == "OCR provider timeout"


def test_complete_job_rejects_an_invalid_status():
    with pytest.raises(ValueError):
        complete_job(None, "irrelevant", status="queued")  # never reaches the database
