"""S7 — Citation resolution + threading. Runs after S6 has inserted a document's
letters and their extracted_fields (including cited_ref fields) for the current
extraction run.

Threading strategy: recompute connected components over the WHOLE package's current
letters and resolved citations on every ingest, rather than incrementally merging.
At the package sizes this product targets (a package's correspondence, not a
multi-package corpus), this is cheap and — critically — avoids a class of merge bugs
where two previously separate threads should combine because a new letter cites into
both: incremental merge logic for that case is real and easy to get wrong, and a full
recompute sidesteps it by construction. thread_key is stable (the earliest member's
letter_ref), so re-running keeps assigning existing letters to the same thread row
unless a new citation actually connects it to something else.
"""

from __future__ import annotations

import re
import unicodedata

import psycopg


def normalize_ref(ref: str) -> str:
    ref = unicodedata.normalize("NFC", ref)
    return " ".join(ref.split()).upper()


# SQL fragment stripping a reference down to letters and digits only, so two
# spellings of the SAME reference ("No. PW/CE/NH/22/2018/Pt/47" vs
# "PW-CE-NH-22-2018-PT-47") compare equal. Deliberately NOT similarity: every
# character that survives must still match exactly, so two references that
# differ only in their trailing serial -- 295 vs 367, 61 vs 66 -- remain
# distinct. Real data showed those scoring 64-68% on trigram similarity purely
# because they share a long identical prefix, which is exactly why a percentage
# threshold cannot be used to auto-link an evidentiary register.
#
# A leading "No."/"NO." is also dropped: it is the word "Number", a label
# attached inconsistently across these documents ("No. PW/CE/..." vs
# "PW/CE/..."), not part of the identifier. A separator (period or whitespace)
# is REQUIRED after it so a reference that genuinely begins with those letters
# -- NOIDA/... -- is left alone.
_ALNUM_SQL = (
    "upper(regexp_replace("
    "regexp_replace(upper({col}), '^NO[.[:space:]]+', ''), "
    "'[^A-Za-z0-9]', '', 'g'))"
)

_NO_PREFIX = re.compile(r"^NO[.\s]+")


def strip_to_alnum(ref: str) -> str:
    stripped = _NO_PREFIX.sub("", ref.upper())
    return "".join(ch for ch in stripped if ch.isalnum())


def resolve_citations(conn: psycopg.Connection, package_id: str, extraction_run_id: str) -> None:
    """For every cited_ref extracted_field belonging to this run, look up whether it
    matches an existing current letter in the package by normalized reference."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ef.id, ef.letter_id, ef.value_text, ef.value_verbatim
            FROM extracted_fields ef
            WHERE ef.extraction_run_id = %s AND ef.field_key = 'cited_ref'
            """,
            (extraction_run_id,),
        )
        cited_fields = cur.fetchall()

    for field_id, citing_letter_id, value_text, value_verbatim in cited_fields:
        # verbatim first: see ingest.py's identical reasoning for letter_ref --
        # value is unvalidated free-form re-typing and real data showed it
        # corrupting reference numbers the verbatim text got right.
        ref_normalized = normalize_ref(value_verbatim or value_text or "")
        if not ref_normalized:
            continue

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id FROM letters
                WHERE package_id = %s AND is_current AND letter_ref_normalized = %s
                      AND id != %s
                """,
                (package_id, ref_normalized, citing_letter_id),
            )
            matches = [row[0] for row in cur.fetchall()]
            fuzzy_candidates: list[tuple] = []  # (letter_id, score) -- only used when no exact match

            # Second pass before falling back to fuzzy: the same reference written
            # with different punctuation/spacing/case is still the same reference.
            # Only run when the strict comparison found nothing, and only accept a
            # single unambiguous hit -- if two letters collapse to the same
            # alphanumeric string, that is genuinely ambiguous and goes to review.
            if not matches:
                cur.execute(
                    f"""
                    SELECT id FROM letters
                    WHERE package_id = %s AND is_current AND id != %s
                          AND letter_ref_normalized IS NOT NULL
                          AND {_ALNUM_SQL.format(col='letter_ref_normalized')} = %s
                    """,
                    (package_id, citing_letter_id, strip_to_alnum(ref_normalized)),
                )
                alnum_matches = [row[0] for row in cur.fetchall()]
                if len(alnum_matches) == 1:
                    matches = alnum_matches

            if len(matches) == 1:
                resolution, cited_letter_id = "resolved", matches[0]
            elif len(matches) > 1:
                resolution, cited_letter_id = "unresolved_ambiguous", None
            else:
                # No EXACT match. Real data proved this doesn't mean "not held" --
                # OCR noise on either side (the citing text or the target letter's
                # own ref field) routinely breaks exact string equality between
                # two refs that are actually the same letter. But similarity alone
                # can't tell a genuine OCR-garbled match apart from two DIFFERENT
                # letters that just happen to share a sequential-numbering prefix
                # (e.g. ".../25-26/556" citing ".../25-26/559" -- adjacent memo
                # numbers, not the same letter). Silently auto-resolving either
                # case risks linking evidence between two different letters, which
                # is worse than leaving it unresolved -- so any fuzzy match is
                # surfaced as unresolved_ambiguous with its candidates recorded
                # for a human to confirm, never auto-resolved.
                cur.execute(
                    """
                    SELECT id, similarity(letter_ref_normalized, %s) AS score
                    FROM letters
                    WHERE package_id = %s AND is_current AND id != %s
                          AND letter_ref_normalized IS NOT NULL
                          AND similarity(letter_ref_normalized, %s) >= 0.5
                    ORDER BY score DESC
                    LIMIT 3
                    """,
                    (ref_normalized, package_id, citing_letter_id, ref_normalized),
                )
                fuzzy_candidates = cur.fetchall()
                resolution, cited_letter_id = (
                    ("unresolved_ambiguous", None) if fuzzy_candidates else ("unresolved_missing", None)
                )

            cur.execute(
                """
                INSERT INTO citations (package_id, citing_letter_id, cited_ref_text,
                                        cited_ref_normalized, cited_letter_id, resolution)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (citing_letter_id, cited_ref_normalized)
                DO UPDATE SET cited_letter_id = EXCLUDED.cited_letter_id,
                              resolution = EXCLUDED.resolution
                RETURNING id
                """,
                (package_id, citing_letter_id, value_verbatim or value_text,
                 ref_normalized, cited_letter_id, resolution),
            )
            (citation_id,) = cur.fetchone()

            cur.execute(
                "INSERT INTO citation_occurrences (citation_id, extracted_field_id) "
                "VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (citation_id, field_id),
            )

            if len(matches) > 1:
                for candidate_id in matches:
                    cur.execute(
                        """
                        INSERT INTO citation_candidates (citation_id, package_id, candidate_letter_id, match_method)
                        VALUES (%s, %s, %s, 'exact_ref')
                        ON CONFLICT (citation_id, candidate_letter_id) DO NOTHING
                        """,
                        (citation_id, package_id, candidate_id),
                    )
            for candidate_id, score in fuzzy_candidates:
                cur.execute(
                    """
                    INSERT INTO citation_candidates (citation_id, package_id, candidate_letter_id, match_method, match_score)
                    VALUES (%s, %s, %s, 'trgm_fuzzy', %s)
                    ON CONFLICT (citation_id, candidate_letter_id) DO NOTHING
                    """,
                    (citation_id, package_id, candidate_id, score),
                )


class _UnionFind:
    def __init__(self, ids: list[str]) -> None:
        self.parent = {i: i for i in ids}

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def recompute_threads(conn: psycopg.Connection, package_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, letter_ref, letter_ref_normalized, dated, serial, subject
            FROM letters WHERE package_id = %s AND is_current
            """,
            (package_id,),
        )
        letters = {
            str(row[0]): {
                "letter_ref": row[1], "letter_ref_normalized": row[2],
                "dated": row[3], "serial": row[4], "subject": row[5],
            }
            for row in cur.fetchall()
        }
        cur.execute(
            """
            SELECT citing_letter_id, cited_letter_id FROM citations
            WHERE package_id = %s AND resolution = 'resolved'
            """,
            (package_id,),
        )
        edges = [(str(a), str(b)) for a, b in cur.fetchall()]

    if not letters:
        return

    uf = _UnionFind(list(letters.keys()))
    for a, b in edges:
        if a in letters and b in letters:
            uf.union(a, b)

    components: dict[str, list[str]] = {}
    for letter_id in letters:
        root = uf.find(letter_id)
        components.setdefault(root, []).append(letter_id)

    for member_ids in components.values():
        member_ids.sort(key=lambda lid: (letters[lid]["dated"] or "9999-99-99", letters[lid]["serial"]))
        earliest = letters[member_ids[0]]
        thread_key = earliest["letter_ref_normalized"] or earliest["letter_ref"] or member_ids[0]
        dates = [letters[m]["dated"] for m in member_ids if letters[m]["dated"]]

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO threads (package_id, thread_key, subject, first_dated, last_dated, letter_count)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (package_id, thread_key) DO UPDATE SET
                    first_dated = EXCLUDED.first_dated,
                    last_dated = EXCLUDED.last_dated,
                    letter_count = EXCLUDED.letter_count,
                    thread_version = threads.thread_version + 1,
                    computed_at = now()
                RETURNING id, thread_version
                """,
                (package_id, thread_key, earliest["subject"],
                 min(dates) if dates else None, max(dates) if dates else None, len(member_ids)),
            )
            thread_id, thread_version = cur.fetchone()

            for letter_id in member_ids:
                cur.execute("UPDATE letters SET thread_id = %s WHERE id = %s", (thread_id, letter_id))
                cur.execute(
                    """
                    INSERT INTO thread_memberships (thread_id, letter_id, thread_version)
                    VALUES (%s, %s, %s) ON CONFLICT DO NOTHING
                    """,
                    (thread_id, letter_id, thread_version),
                )
