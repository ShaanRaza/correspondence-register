"""Integration tests for apply_reprocessing() against a real PostgreSQL instance.

Requires db/schema.sql applied to the database named by CR_TEST_DATABASE_URL. Skipped
entirely when that env var is unset, so `pytest` stays runnable without a database for
the pure-logic tests in test_reprocessing.py. This file exists specifically because
FOR UPDATE / partial-unique-index / composite-FK behavior is not meaningfully
testable without a real database — that's the whole lesson of this session's earlier
smoke tests, applied here as an actual pytest suite instead of a one-off psql script.
"""

from __future__ import annotations

import os
import uuid

import psycopg
import pytest

from app.pipeline.reprocessing import CandidateLetter, MatchAction
from app.pipeline.reprocessing_service import apply_reprocessing

DATABASE_URL = os.environ.get("CR_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="CR_TEST_DATABASE_URL not set")


@pytest.fixture()
def conn():
    connection = psycopg.connect(DATABASE_URL, autocommit=False)
    yield connection
    connection.rollback()  # every test's writes are undone; the schema itself persists
    connection.close()


def _uuid() -> str:
    return str(uuid.uuid4())


def _make_package(conn) -> tuple[str, str]:
    """Returns (contractor_id, package_id)."""
    contractor_id = _uuid()
    package_id = _uuid()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO contractors (id, name, short_code) VALUES (%s, %s, %s)",
            (contractor_id, "Acme Infra", f"ACME-{contractor_id[:8]}"),
        )
        cur.execute(
            "INSERT INTO packages (id, contractor_id, name, contract_no) VALUES (%s, %s, %s, %s)",
            (package_id, contractor_id, "NH-44 PKG-3", f"PKG3-{package_id[:8]}"),
        )
    return contractor_id, package_id


def _make_document(conn) -> str:
    sha256 = uuid.uuid4().hex + uuid.uuid4().hex  # 64 hex chars, doesn't need to be a real hash for this test
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO documents (sha256, byte_size, mime_type, original_filename, storage_uri) "
            "VALUES (%s, 1000, 'application/pdf', 'letter.pdf', 'file:///x')",
            (sha256,),
        )
    return sha256


def _make_pipeline_version(conn, vid: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO pipeline_versions (id, ocr_provider, ocr_provider_version, llm_model, "
            "prompt_sha256, schema_sha256) VALUES (%s, 'fixture', '1', 'claude-opus-5', %s, %s) "
            "ON CONFLICT (id) DO NOTHING",
            (vid, "a" * 64, "b" * 64),
        )


def _make_run(
    conn, *, package_id: str, document_sha256: str, pipeline_version_id: str, is_current: bool,
    supersedes: str | None = None,
) -> str:
    """`supersedes`: mark that prior run non-current first, so this one can legally
    take the (document_sha256, package_id) is_current slot the partial unique index
    only allows one occupant of."""
    if supersedes is not None:
        with conn.cursor() as cur:
            cur.execute("UPDATE extraction_runs SET is_current = false WHERE id = %s", (supersedes,))
    run_id = _uuid()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO extraction_runs (id, document_sha256, package_id, pipeline_version_id, "
            "status, is_current, finished_at) VALUES (%s, %s, %s, %s, 'succeeded', %s, now())",
            (run_id, document_sha256, package_id, pipeline_version_id, is_current),
        )
        if supersedes is not None:
            cur.execute("UPDATE extraction_runs SET superseded_by = %s WHERE id = %s", (run_id, supersedes))
    return run_id


def _advance_next_serial_past(conn, package_id: str, serial: int) -> None:
    """Test-only: _make_existing_letter inserts a hardcoded serial without touching
    packages.next_serial (unlike the real pipeline, which only ever assigns serials
    through _next_serial). Call this after manually seeding letters so the counter
    does not collide with them when apply_reprocessing() next asks for a fresh one."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE packages SET next_serial = GREATEST(next_serial, %s) WHERE id = %s",
            (serial + 1, package_id),
        )


def _make_existing_letter(conn, *, package_id, document_sha256, extraction_run_id, serial, ref, page_from=1, page_to=1):
    letter_id = _uuid()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO letters (id, package_id, document_sha256, extraction_run_id, serial, "
            "letter_ref, letter_ref_normalized, page_from, page_to, is_current) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, true)",
            (letter_id, package_id, document_sha256, extraction_run_id, serial, ref, ref, page_from, page_to),
        )
    return letter_id


def test_supersede_carries_the_serial_forward_and_register_shows_one_row(conn):
    _, package_id = _make_package(conn)
    document_sha256 = _make_document(conn)
    _make_pipeline_version(conn, "v1")
    old_run = _make_run(conn, package_id=package_id, document_sha256=document_sha256, pipeline_version_id="v1", is_current=True)
    old_letter_id = _make_existing_letter(
        conn, package_id=package_id, document_sha256=document_sha256, extraction_run_id=old_run,
        serial=1, ref="CTR/PKG3/001",
    )

    _make_pipeline_version(conn, "v2")
    new_run = _make_run(conn, package_id=package_id, document_sha256=document_sha256, pipeline_version_id="v2", is_current=True, supersedes=old_run)

    outcomes = apply_reprocessing(
        conn,
        package_id=package_id,
        document_sha256=document_sha256,
        extraction_run_id=new_run,
        candidates=[CandidateLetter(index=0, document_sha256=document_sha256, letter_ref_normalized="CTR/PKG3/001", page_from=1, page_to=1)],
    )

    [(result, new_letter_id)] = outcomes
    assert result.action == MatchAction.SUPERSEDE
    assert result.matched_serial == 1

    with conn.cursor() as cur:
        cur.execute("SELECT id, is_current FROM letters WHERE id = %s", (old_letter_id,))
        old_id, old_is_current = cur.fetchone()
        assert old_is_current is False

        cur.execute("SELECT serial FROM register WHERE id = %s", (new_letter_id,))
        (serial,) = cur.fetchone()
        assert serial == 1

        # THE actual bug this whole thread started from: exactly one row, not two.
        cur.execute("SELECT count(*) FROM register WHERE package_id = %s AND serial = 1", (package_id,))
        assert cur.fetchone()[0] == 1


def test_no_ref_match_falls_back_to_page_overlap_and_still_produces_one_register_row(conn):
    _, package_id = _make_package(conn)
    document_sha256 = _make_document(conn)
    _make_pipeline_version(conn, "v1")
    old_run = _make_run(conn, package_id=package_id, document_sha256=document_sha256, pipeline_version_id="v1", is_current=True)
    _make_existing_letter(
        conn, package_id=package_id, document_sha256=document_sha256, extraction_run_id=old_run,
        serial=7, ref="CTR/PKG3/OO7", page_from=3, page_to=4,  # OCR misread: letter O instead of digit 0
    )

    _make_pipeline_version(conn, "v2")
    new_run = _make_run(conn, package_id=package_id, document_sha256=document_sha256, pipeline_version_id="v2", is_current=True, supersedes=old_run)

    [(result, _new_id)] = apply_reprocessing(
        conn, package_id=package_id, document_sha256=document_sha256, extraction_run_id=new_run,
        candidates=[CandidateLetter(index=0, document_sha256=document_sha256, letter_ref_normalized="CTR/PKG3/007", page_from=3, page_to=4)],
    )

    assert result.action == MatchAction.SUPERSEDE
    assert result.matched_serial == 7
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM register WHERE package_id = %s AND serial = 7", (package_id,))
        assert cur.fetchone()[0] == 1


def test_new_candidate_gets_a_fresh_serial_from_the_package_counter(conn):
    _, package_id = _make_package(conn)
    document_sha256 = _make_document(conn)
    _make_pipeline_version(conn, "v1")
    run_id = _make_run(conn, package_id=package_id, document_sha256=document_sha256, pipeline_version_id="v1", is_current=True)

    [(result, new_id)] = apply_reprocessing(
        conn, package_id=package_id, document_sha256=document_sha256, extraction_run_id=run_id,
        candidates=[CandidateLetter(index=0, document_sha256=document_sha256, letter_ref_normalized="CTR/PKG3/001", page_from=1, page_to=1)],
    )

    assert result.action == MatchAction.NEW
    with conn.cursor() as cur:
        cur.execute("SELECT serial, is_current, review_status FROM letters WHERE id = %s", (new_id,))
        serial, is_current, review_status = cur.fetchone()
        assert serial == 1  # packages.next_serial starts at 1
        assert is_current is True
        assert review_status == "unverified"


def test_ambiguous_match_is_flagged_not_applied_and_leaves_a_review_event(conn):
    _, package_id = _make_package(conn)
    document_sha256 = _make_document(conn)
    _make_pipeline_version(conn, "v1")
    old_run = _make_run(conn, package_id=package_id, document_sha256=document_sha256, pipeline_version_id="v1", is_current=True)
    # two existing letters both overlap the candidate's page range, and it has no ref
    _make_existing_letter(conn, package_id=package_id, document_sha256=document_sha256, extraction_run_id=old_run, serial=1, ref="A", page_from=1, page_to=3)
    _make_existing_letter(conn, package_id=package_id, document_sha256=document_sha256, extraction_run_id=old_run, serial=2, ref="B", page_from=2, page_to=4)
    _advance_next_serial_past(conn, package_id, 2)

    _make_pipeline_version(conn, "v2")
    new_run = _make_run(conn, package_id=package_id, document_sha256=document_sha256, pipeline_version_id="v2", is_current=True, supersedes=old_run)

    [(result, new_id)] = apply_reprocessing(
        conn, package_id=package_id, document_sha256=document_sha256, extraction_run_id=new_run,
        candidates=[CandidateLetter(index=0, document_sha256=document_sha256, letter_ref_normalized=None, page_from=2, page_to=2)],
        actor="pipeline:reprocessing:test",
    )

    assert result.action == MatchAction.FLAG_AMBIGUOUS
    with conn.cursor() as cur:
        cur.execute("SELECT review_status FROM letters WHERE id = %s", (new_id,))
        assert cur.fetchone()[0] == "needs_review"

        cur.execute(
            "SELECT actor, action, note FROM review_events WHERE letter_id = %s",
            (new_id,),
        )
        actor, action, note = cur.fetchone()
        assert actor == "pipeline:reprocessing:test"
        assert action == "flagged"
        assert "1" in note and "2" in note  # both candidate serials named in the note

    # both pre-existing letters remain untouched and current — nothing was silently applied
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM letters WHERE package_id = %s AND is_current AND serial IN (1, 2)",
            (package_id,),
        )
        assert cur.fetchone()[0] == 2
