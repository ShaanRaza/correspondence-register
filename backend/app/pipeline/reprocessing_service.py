"""Wires match_reprocessed_letters() (pure logic, reprocessing.py) to PostgreSQL.

Loads the current letters for one (package, document), runs the match, then executes
whatever the match decided: supersede an existing logical letter, insert a genuinely
new one, or insert-and-flag when the match couldn't confidently decide. See
PIPELINE.md § "Reprocessing an already-published document" for the algorithm and the
three-statement supersede ordering (insert not-current, flip old off, flip new on) —
that exact ordering is required by two constraints proven by running the naive
two-step version against a live Postgres and watching it fail both ways.

This module does not manage the transaction. The caller opens one, calls
apply_reprocessing(), and commits — consistent with PIPELINE.md's rule that S6-S8
share a single transaction containing only fast, deterministic database operations.

Not yet handled here (explicitly out of scope for this pass, not silently missing):
relinking `extracted_fields.letter_id` from the new run onto the letters this function
creates. That's an assembly-stage concern that sits upstream of matching, not part of
deciding which existing letter a candidate corresponds to.
"""

from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

from .reprocessing import (
    CandidateLetter,
    ExistingLetter,
    MatchAction,
    MatchResult,
    match_reprocessed_letters,
)


def load_existing_letters(
    conn: psycopg.Connection, package_id: str, document_sha256: str
) -> list[ExistingLetter]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, serial, document_sha256, letter_ref_normalized, page_from, page_to
            FROM letters
            WHERE package_id = %s AND document_sha256 = %s AND is_current AND voided_at IS NULL
            """,
            (package_id, document_sha256),
        )
        return [ExistingLetter(**row) for row in cur.fetchall()]


def _next_serial(conn: psycopg.Connection, package_id: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE packages SET next_serial = next_serial + 1 WHERE id = %s RETURNING next_serial - 1",
            (package_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"no such package {package_id}")
        return row[0]


def _insert_letter(
    conn: psycopg.Connection,
    *,
    package_id: str,
    document_sha256: str,
    extraction_run_id: str,
    serial: int,
    candidate: CandidateLetter,
    is_current: bool,
    review_status: str = "unverified",
) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO letters (package_id, document_sha256, extraction_run_id, serial,
                                  letter_ref_normalized, page_from, page_to, is_current, review_status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                package_id,
                document_sha256,
                extraction_run_id,
                serial,
                candidate.letter_ref_normalized,
                candidate.page_from,
                candidate.page_to,
                is_current,
                review_status,
            ),
        )
        return cur.fetchone()[0]


def _supersede(conn: psycopg.Connection, *, old_id: str, new_id: str) -> None:
    # Same three-step reason as record_field_correction() in db/schema.sql: the
    # partial unique index letters_one_current_serial can't have both rows current at
    # once, and the caller INSERTs the new row as not-current first, so this function
    # only ever does the flip: old off, then new on.
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE letters SET is_current = false, superseded_by = %s WHERE id = %s",
            (new_id, old_id),
        )
        cur.execute("UPDATE letters SET is_current = true WHERE id = %s", (new_id,))


def _flag(conn: psycopg.Connection, *, letter_id: str, actor: str, note: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO review_events (letter_id, actor, action, note) VALUES (%s, %s, 'flagged', %s)",
            (letter_id, actor, note),
        )


def apply_reprocessing(
    conn: psycopg.Connection,
    *,
    package_id: str,
    document_sha256: str,
    extraction_run_id: str,
    candidates: list[CandidateLetter],
    actor: str = "pipeline:reprocessing",
) -> list[tuple[MatchResult, str]]:
    """Runs the match and executes it. Returns (MatchResult, new_letter_id) per candidate,
    in the order `candidates` was given. Caller commits."""
    existing = load_existing_letters(conn, package_id, document_sha256)
    results = match_reprocessed_letters(existing, candidates)
    candidates_by_index = {c.index: c for c in candidates}
    existing_by_id = {e.id: e for e in existing}

    outcomes: list[tuple[MatchResult, str]] = []
    for result in results:
        candidate = candidates_by_index[result.candidate_index]

        if result.action == MatchAction.SUPERSEDE:
            old = existing_by_id[result.matched_existing_id]
            new_id = _insert_letter(
                conn,
                package_id=package_id,
                document_sha256=document_sha256,
                extraction_run_id=extraction_run_id,
                serial=old.serial,
                candidate=candidate,
                is_current=False,
            )
            _supersede(conn, old_id=old.id, new_id=new_id)

        elif result.action == MatchAction.NEW:
            serial = _next_serial(conn, package_id)
            new_id = _insert_letter(
                conn,
                package_id=package_id,
                document_sha256=document_sha256,
                extraction_run_id=extraction_run_id,
                serial=serial,
                candidate=candidate,
                is_current=True,
            )

        else:  # FLAG_AMBIGUOUS or FLAG_CONFLICT — inserted as new, never silently
            # applied and never dropped: a fresh serial, needs_review from the start,
            # and a machine-authored review_events row explaining why.
            serial = _next_serial(conn, package_id)
            new_id = _insert_letter(
                conn,
                package_id=package_id,
                document_sha256=document_sha256,
                extraction_run_id=extraction_run_id,
                serial=serial,
                candidate=candidate,
                is_current=True,
                review_status="needs_review",
            )
            _flag(conn, letter_id=new_id, actor=actor, note=result.reason)

        outcomes.append((result, new_id))

    return outcomes
