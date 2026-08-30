"""The Postgres-backed job queue: claim, reap, complete. No Redis, no Celery — see
STACK.md and db/schema.sql's inline comments for why `FOR UPDATE SKIP LOCKED` plus a
lease column is enough at this scale.

Three operations, matching the three things a queue actually needs to do:
  - claim_next_job: a worker takes ownership of one queued job, atomically, without
    blocking on or double-claiming a job another worker is mid-claim on.
  - reap_expired_leases: a worker that died mid-job leaves its row 'running' forever
    unless something notices the lease lapsed and returns it to the queue.
  - complete_job: mark a claimed job finished, successfully or not.
"""

from __future__ import annotations

from dataclasses import dataclass

import psycopg
from psycopg.rows import dict_row


@dataclass(frozen=True)
class ClaimedJob:
    id: str
    job_type: str
    package_id: str | None
    document_sha256: str | None
    pipeline_version_id: str | None
    payload: dict
    attempts: int


def claim_next_job(
    conn: psycopg.Connection, *, worker_id: str, lease_seconds: int = 600
) -> ClaimedJob | None:
    """Atomically claims one queued job, or returns None if there isn't one.

    SKIP LOCKED is what makes concurrent workers safe: a job another transaction has
    already selected FOR UPDATE (and not yet committed) is invisible to this query
    rather than something we'd block waiting for, or a second copy we'd double-claim.
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            UPDATE ingestion_jobs
            SET status = 'running',
                locked_at = now(),
                locked_by = %(worker_id)s,
                lease_until = now() + make_interval(secs => %(lease_seconds)s),
                started_at = now(),
                attempts = attempts + 1
            WHERE id = (
                SELECT id FROM ingestion_jobs
                WHERE status = 'queued' AND run_after <= now()
                ORDER BY created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING id, job_type, package_id, document_sha256, pipeline_version_id, payload, attempts
            """,
            {"worker_id": worker_id, "lease_seconds": lease_seconds},
        )
        row = cur.fetchone()
        if row is None:
            return None
        return ClaimedJob(**row)


def reap_expired_leases(conn: psycopg.Connection) -> int:
    """Returns any job whose lease lapsed — a worker that crashed, was killed, or lost
    its connection mid-job — to the queue for another worker to pick up. Returns the
    number of jobs reaped. Safe to call opportunistically before every claim, or on a
    schedule; a job with a still-valid lease is untouched either way."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE ingestion_jobs
            SET status = 'queued', locked_by = NULL, lease_until = NULL
            WHERE status = 'running' AND lease_until < now()
            """
        )
        return cur.rowcount


def complete_job(
    conn: psycopg.Connection,
    job_id: str,
    *,
    status: str,
    result: dict | None = None,
    error: str | None = None,
) -> None:
    if status not in ("succeeded", "failed"):
        raise ValueError(f"complete_job status must be 'succeeded' or 'failed', got {status!r}")
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE ingestion_jobs
            SET status = %s, result = %s, error = %s, finished_at = now(),
                locked_by = NULL, lease_until = NULL
            WHERE id = %s
            """,
            (status, psycopg.types.json.Json(result) if result is not None else None, error, job_id),
        )
