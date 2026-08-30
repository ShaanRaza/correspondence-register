"""S6 reprocessing match: decide whether a newly-extracted candidate letter is a new
version of an already-published logical letter, or a genuinely new one.

See PIPELINE.md § "Reprocessing an already-published document" for the algorithm this
implements, and DATA_MODEL.md § "letters" for why the match matters: a matched
candidate inherits the existing letter's immutable `serial` and supersedes it; an
unmatched candidate becomes a new logical letter with a freshly-assigned serial.

This module is pure and has no database dependency. It takes the current letters for
one (package, document) as loaded by the caller and the newly-assembled candidates from
a fresh extraction run, and returns one MatchResult per candidate. The caller is
responsible for executing the actual three-statement supersede sequence (insert
not-current, flip old off, flip new on) documented in PIPELINE.md and proven against a
live Postgres instance — this module only decides WHICH letters correspond to which; it
performs no writes.

Two rules govern every decision here, both stated directly in PIPELINE.md:
  - Primary match is exact letter_ref_normalized among current letters.
  - Fallback is page-range overlap on the same document_sha256, for the case OCR fixed
    a previously-garbled reference so the ref no longer matches.
  - No confident match, by either rule, is never resolved by a guess. It is flagged.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MatchAction(str, Enum):
    SUPERSEDE = "supersede"  # candidate is a new version of an existing logical letter
    NEW = "new"  # candidate is a genuinely new logical letter; assign a fresh serial
    FLAG_AMBIGUOUS = "flag_ambiguous"  # candidate matched more than one existing letter
    FLAG_CONFLICT = "flag_conflict"  # two candidates in this run both matched the same existing letter


@dataclass(frozen=True)
class ExistingLetter:
    """One CURRENT letter already on file for this (package, document). The caller
    must pass only is_current letters — this module does not filter on that."""

    id: str
    serial: int
    document_sha256: str
    letter_ref_normalized: str | None
    page_from: int
    page_to: int


@dataclass(frozen=True)
class CandidateLetter:
    """One letter assembled from a NEW extraction run, not yet persisted."""

    index: int  # the candidate's position in this run's output, for stable reporting
    document_sha256: str
    letter_ref_normalized: str | None
    page_from: int
    page_to: int


@dataclass(frozen=True)
class MatchResult:
    candidate_index: int
    action: MatchAction
    matched_existing_id: str | None  # set only for SUPERSEDE
    matched_serial: int | None  # set only for SUPERSEDE
    reason: str  # human-readable; becomes the review_events note for a flagged result


def _page_ranges_overlap(a_from: int, a_to: int, b_from: int, b_to: int) -> bool:
    return max(a_from, b_from) <= min(a_to, b_to)


def _match_by_ref(candidate: CandidateLetter, existing: list[ExistingLetter]) -> list[ExistingLetter]:
    if candidate.letter_ref_normalized is None:
        return []
    return [
        e
        for e in existing
        if e.document_sha256 == candidate.document_sha256
        and e.letter_ref_normalized == candidate.letter_ref_normalized
    ]


def _match_by_page_overlap(candidate: CandidateLetter, existing: list[ExistingLetter]) -> list[ExistingLetter]:
    return [
        e
        for e in existing
        if e.document_sha256 == candidate.document_sha256
        and _page_ranges_overlap(candidate.page_from, candidate.page_to, e.page_from, e.page_to)
    ]


def match_reprocessed_letters(
    existing_letters: list[ExistingLetter],
    candidates: list[CandidateLetter],
) -> list[MatchResult]:
    """Match each candidate against the existing current letters for this document.

    Two passes:
      1. Per-candidate matching (ref, then page-overlap fallback), producing a
         provisional result for every candidate.
      2. Conflict detection: if two candidates both provisionally matched the SAME
         existing letter, neither can validly supersede it (only one letter can carry
         that serial forward) — both are downgraded to FLAG_CONFLICT rather than one
         being picked arbitrarily.
    """
    provisional: list[tuple[CandidateLetter, MatchAction, ExistingLetter | None, str]] = []

    for candidate in candidates:
        ref_matches = _match_by_ref(candidate, existing_letters)

        if len(ref_matches) == 1:
            provisional.append(
                (candidate, MatchAction.SUPERSEDE, ref_matches[0], "matched by exact letter_ref_normalized")
            )
            continue
        if len(ref_matches) > 1:
            # Shouldn't happen given letters_ref_lookup + one-current-serial, but this
            # is exactly the kind of anomaly PIPELINE.md says to flag, not assume away.
            provisional.append(
                (
                    candidate,
                    MatchAction.FLAG_AMBIGUOUS,
                    None,
                    f"letter_ref_normalized matched {len(ref_matches)} current letters "
                    f"(serials {sorted(e.serial for e in ref_matches)}); expected at most one",
                )
            )
            continue

        page_matches = _match_by_page_overlap(candidate, existing_letters)
        if len(page_matches) == 1:
            provisional.append(
                (
                    candidate,
                    MatchAction.SUPERSEDE,
                    page_matches[0],
                    f"no ref match; matched by page-range overlap with serial {page_matches[0].serial} "
                    "(OCR likely corrected a previously-garbled reference)",
                )
            )
            continue
        if len(page_matches) > 1:
            provisional.append(
                (
                    candidate,
                    MatchAction.FLAG_AMBIGUOUS,
                    None,
                    f"no ref match; page range overlaps {len(page_matches)} current letters "
                    f"(serials {sorted(e.serial for e in page_matches)})",
                )
            )
            continue

        provisional.append(
            (candidate, MatchAction.NEW, None, "no ref or page-range match against current letters; treated as new")
        )

    # Pass 2: detect two candidates racing for the same existing letter.
    claim_counts: dict[str, int] = {}
    for _candidate, action, matched, _reason in provisional:
        if action == MatchAction.SUPERSEDE and matched is not None:
            claim_counts[matched.id] = claim_counts.get(matched.id, 0) + 1

    results: list[MatchResult] = []
    for candidate, action, matched, reason in provisional:
        if action == MatchAction.SUPERSEDE and matched is not None and claim_counts[matched.id] > 1:
            results.append(
                MatchResult(
                    candidate_index=candidate.index,
                    action=MatchAction.FLAG_CONFLICT,
                    matched_existing_id=None,
                    matched_serial=None,
                    reason=(
                        f"{claim_counts[matched.id]} candidates in this run all matched "
                        f"existing serial {matched.serial}; cannot determine which one "
                        "should supersede it"
                    ),
                )
            )
            continue

        results.append(
            MatchResult(
                candidate_index=candidate.index,
                action=action,
                matched_existing_id=matched.id if matched else None,
                matched_serial=matched.serial if matched else None,
                reason=reason,
            )
        )

    return results
