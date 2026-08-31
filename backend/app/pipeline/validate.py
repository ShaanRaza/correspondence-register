"""S4 — Deterministic validation. No model is involved in this stage. This is the
gate that makes the product evidentiary rather than generative: a value the model
claimed is only accepted once code proves it exists, character-for-character, in
the OCR text this pipeline actually produced.

Three outcomes, matching validation_kind in db/schema.sql:
  exact             — verbatim found as an exact code-point match in the raw OCR text
  normalized_exact  — found only after NFC normalization + whitespace-run collapse
  unresolved        — not found by either rule; no geometry, letter flagged
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class ValidationResult:
    validation: str  # 'exact' | 'normalized_exact' | 'unresolved'
    char_start: int | None
    char_end: int | None


def _normalized_with_mapping(nfc_text: str) -> tuple[str, list[int]]:
    """Collapse whitespace runs to a single space, tracking which NFC-text index
    produced each output character. mapping[j] = index into nfc_text.

    Built as an explicit single pass rather than via `" ".join(s.split())` +
    re-normalizing growing prefixes to find offsets — that approach (tried first)
    has no way to know, after the fact, which original index a collapsed match
    boundary actually corresponds to, and silently produced off-by-one boundaries
    that clipped a leading digit. Caught by running it against a real
    multiple-spaces case, not by inspection.
    """
    out_chars: list[str] = []
    mapping: list[int] = []
    i = 0
    n = len(nfc_text)
    started = False
    while i < n:
        c = nfc_text[i]
        if c.isspace():
            run_start = i
            while i < n and nfc_text[i].isspace():
                i += 1
            if started:
                out_chars.append(" ")
                mapping.append(run_start)
            continue
        out_chars.append(c)
        mapping.append(i)
        started = True
        i += 1
    while out_chars and out_chars[-1] == " ":
        out_chars.pop()
        mapping.pop()
    return "".join(out_chars), mapping


def validate_verbatim(page_text: str, verbatim: str) -> ValidationResult:
    if not verbatim:
        return ValidationResult("unresolved", None, None)

    idx = page_text.find(verbatim)
    if idx >= 0:
        return ValidationResult("exact", idx, idx + len(verbatim))

    nfc_page = unicodedata.normalize("NFC", page_text)
    nfc_verbatim = unicodedata.normalize("NFC", verbatim)
    norm_page, mapping = _normalized_with_mapping(nfc_page)
    norm_verbatim, _ = _normalized_with_mapping(nfc_verbatim)

    norm_idx = norm_page.find(norm_verbatim)
    if norm_idx < 0 or not norm_verbatim:
        return ValidationResult("unresolved", None, None)

    start = mapping[norm_idx]
    end = mapping[norm_idx + len(norm_verbatim) - 1] + 1

    # nfc_page may differ in length from the original page_text if NFC composition
    # changed character counts (rare, but real for some Devanagari combining
    # sequences) -- guard rather than silently return a wrong span into page_text.
    if len(nfc_page) != len(page_text):
        return ValidationResult("unresolved", None, None)

    return ValidationResult("normalized_exact", start, end)
