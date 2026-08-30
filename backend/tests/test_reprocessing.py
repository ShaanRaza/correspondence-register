"""Tests for the S6 reprocessing-match heuristic (app.pipeline.reprocessing).

Each test name states the scenario from PIPELINE.md § "Reprocessing an already-
published document" that it proves, so a failure here points straight back at which
documented rule broke.
"""

from app.pipeline.reprocessing import (
    CandidateLetter,
    ExistingLetter,
    MatchAction,
    match_reprocessed_letters,
)

DOC_A = "a" * 64
DOC_B = "b" * 64


def existing(serial, ref, page_from=1, page_to=1, doc=DOC_A, id_=None):
    return ExistingLetter(
        id=id_ or f"existing-{serial}",
        serial=serial,
        document_sha256=doc,
        letter_ref_normalized=ref,
        page_from=page_from,
        page_to=page_to,
    )


def candidate(index, ref, page_from=1, page_to=1, doc=DOC_A):
    return CandidateLetter(
        index=index, document_sha256=doc, letter_ref_normalized=ref, page_from=page_from, page_to=page_to
    )


def test_exact_ref_match_supersedes_and_carries_the_serial():
    existing_letters = [existing(serial=17, ref="CTR/PKG3/001")]
    candidates = [candidate(0, ref="CTR/PKG3/001")]

    [result] = match_reprocessed_letters(existing_letters, candidates)

    assert result.action == MatchAction.SUPERSEDE
    assert result.matched_serial == 17
    assert result.matched_existing_id == "existing-17"


def test_no_ref_match_falls_back_to_page_range_overlap():
    # OCR fixed a previously-garbled reference, so the ref no longer matches, but the
    # candidate covers the same pages of the same document as an existing letter.
    existing_letters = [existing(serial=17, ref="CTR/PKG3/OO1", page_from=3, page_to=4)]
    candidates = [candidate(0, ref="CTR/PKG3/001", page_from=3, page_to=4)]

    [result] = match_reprocessed_letters(existing_letters, candidates)

    assert result.action == MatchAction.SUPERSEDE
    assert result.matched_serial == 17
    assert "page-range overlap" in result.reason


def test_partial_page_overlap_still_counts_as_a_match():
    existing_letters = [existing(serial=17, ref="X", page_from=4, page_to=6)]
    candidates = [candidate(0, ref="Y", page_from=2, page_to=4)]  # overlaps only at page 4

    [result] = match_reprocessed_letters(existing_letters, candidates)

    assert result.action == MatchAction.SUPERSEDE
    assert result.matched_serial == 17


def test_disjoint_pages_and_different_ref_is_a_new_logical_letter():
    existing_letters = [existing(serial=17, ref="X", page_from=1, page_to=2)]
    candidates = [candidate(0, ref="Y", page_from=5, page_to=6)]

    [result] = match_reprocessed_letters(existing_letters, candidates)

    assert result.action == MatchAction.NEW
    assert result.matched_existing_id is None
    assert result.matched_serial is None


def test_candidate_never_matches_a_letter_from_a_different_document():
    existing_letters = [existing(serial=17, ref="CTR/PKG3/001", page_from=1, page_to=1, doc=DOC_B)]
    candidates = [candidate(0, ref="CTR/PKG3/001", page_from=1, page_to=1, doc=DOC_A)]

    [result] = match_reprocessed_letters(existing_letters, candidates)

    assert result.action == MatchAction.NEW


def test_null_ref_candidate_skips_straight_to_page_overlap():
    existing_letters = [existing(serial=17, ref="X", page_from=2, page_to=2)]
    candidates = [candidate(0, ref=None, page_from=2, page_to=2)]

    [result] = match_reprocessed_letters(existing_letters, candidates)

    assert result.action == MatchAction.SUPERSEDE
    assert result.matched_serial == 17


def test_ref_matching_more_than_one_current_letter_is_flagged_not_guessed():
    # Shouldn't happen given the schema's letters_ref_lookup + one-current-serial
    # constraints, but the algorithm must not silently pick one if it does.
    existing_letters = [
        existing(serial=17, ref="CTR/PKG3/001", id_="e17"),
        existing(serial=18, ref="CTR/PKG3/001", id_="e18"),
    ]
    candidates = [candidate(0, ref="CTR/PKG3/001")]

    [result] = match_reprocessed_letters(existing_letters, candidates)

    assert result.action == MatchAction.FLAG_AMBIGUOUS
    assert result.matched_existing_id is None
    assert "17" in result.reason and "18" in result.reason


def test_page_overlap_matching_more_than_one_current_letter_is_flagged():
    existing_letters = [
        existing(serial=17, ref="A", page_from=1, page_to=3, id_="e17"),
        existing(serial=18, ref="B", page_from=2, page_to=4, id_="e18"),
    ]
    candidates = [candidate(0, ref="C", page_from=2, page_to=2)]  # overlaps both

    [result] = match_reprocessed_letters(existing_letters, candidates)

    assert result.action == MatchAction.FLAG_AMBIGUOUS


def test_two_candidates_matching_the_same_existing_letter_are_both_flagged_as_conflict():
    existing_letters = [existing(serial=17, ref="CTR/PKG3/001")]
    candidates = [
        candidate(0, ref="CTR/PKG3/001", page_from=1, page_to=1),
        candidate(1, ref=None, page_from=1, page_to=1),  # matches the same letter via page overlap
    ]

    results = match_reprocessed_letters(existing_letters, candidates)

    assert {r.action for r in results} == {MatchAction.FLAG_CONFLICT}
    assert {r.candidate_index for r in results} == {0, 1}
    assert all(r.matched_existing_id is None for r in results)


def test_empty_existing_letters_means_every_candidate_is_new():
    candidates = [candidate(0, ref="CTR/PKG3/001"), candidate(1, ref="CTR/PKG3/002")]

    results = match_reprocessed_letters([], candidates)

    assert all(r.action == MatchAction.NEW for r in results)


def test_mixed_batch_each_candidate_resolved_independently():
    existing_letters = [
        existing(serial=1, ref="CTR/PKG3/001", page_from=1, page_to=1, id_="e1"),
        existing(serial=2, ref="AE/PKG3/002", page_from=2, page_to=2, id_="e2"),
    ]
    candidates = [
        candidate(0, ref="CTR/PKG3/001", page_from=1, page_to=1),  # supersedes serial 1
        candidate(1, ref="AE/PKG3/003", page_from=9, page_to=9),  # genuinely new
    ]

    results = {r.candidate_index: r for r in match_reprocessed_letters(existing_letters, candidates)}

    assert results[0].action == MatchAction.SUPERSEDE
    assert results[0].matched_serial == 1
    assert results[1].action == MatchAction.NEW
