"""S3 — LLM extraction. Gemini 3.6 Flash (free tier), structured output, every field
carries a VERBATIM substring the model claims to have copied from the OCR text. This
module never decides whether that claim is true — that's S4's job (validate.py). The
model proposes; only deterministic code locates.

Originally built against Claude Opus 5 (see STACK.md's reasoning for that choice —
still the better fit for an evidentiary extraction task). Switched to Gemini so
testing isn't blocked on Anthropic billing; swap back by restoring the Anthropic
call if/when that matters more than free-tier access.

Model name verified live against this account's actual API access, not assumed:
gemini-2.5-flash returned a 404 ("no longer available to new users"), and the
error response itself named gemini-3.6-flash as the replacement -- confirmed
against `client.models.list()` as a real, current, non-preview model before using it.

Verified against the installed `google-genai` 2.20.0 package directly (introspecting
GenerateContentConfig / GenerateContentResponse / usage-metadata field names locally)
rather than trusted from docs, since a fetched summary of Google's docs during this
session produced fabricated model/method names (`gemini-3.7-flash`,
`client.interactions.create`) that don't exist in the real SDK.

The schema below is written as plain, fully-inlined JSON Schema (no $ref/$defs) for
`response_json_schema` — $ref support in Gemini's schema validator is unconfirmed,
so this avoids relying on it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from google import genai
from google.genai import types

MODEL = "gemini-3.6-flash"

_FIELD_STR = {
    "type": "object",
    "additionalProperties": False,
    "required": ["value", "verbatim", "page"],
    "properties": {
        "value": {"type": "string", "description": "Normalized value, e.g. ISO date"},
        "verbatim": {
            "type": "string",
            "description": "EXACT substring copied character-for-character from the supplied OCR text. Never paraphrased.",
        },
        "page": {"type": "integer"},
    },
}

_LETTER_ITEM = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "page_from", "page_to", "letter_ref", "dated", "from_party", "to_party",
        "subject", "chainage", "clause", "cited_refs",
    ],
    "properties": {
        "page_from": {"type": "integer"},
        "page_to": {"type": "integer"},
        "letter_ref": _FIELD_STR,
        "dated": _FIELD_STR,
        "received": _FIELD_STR,
        "from_party": _FIELD_STR,
        "to_party": _FIELD_STR,
        "subject": _FIELD_STR,
        "chainage": {"type": "array", "items": _FIELD_STR},
        "clause": {"type": "array", "items": _FIELD_STR},
        "cited_refs": {"type": "array", "items": _FIELD_STR},
    },
}

EXTRACTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["letters"],
    "properties": {
        "letters": {
            "type": "array",
            "description": (
                "One entry per distinct correspondence letter found in this document. "
                "A single PDF may contain more than one letter (a covering letter plus "
                "enclosures) — split them."
            ),
            "items": _LETTER_ITEM,
        }
    },
}

SYSTEM_PROMPT = """You extract structured data from scanned Indian highway EPC \
correspondence for an evidentiary register. This output may be used to argue an \
extension-of-time claim before an arbitral tribunal — accuracy and honesty about \
uncertainty matter more than completeness.

Rules, non-negotiable:
1. Every "verbatim" field must be copied character-for-character from the supplied \
OCR text for that page. Do not paraphrase, correct spelling, expand abbreviations, \
fix OCR errors, or normalize formatting in the verbatim field — normalization \
happens downstream, deterministically, never by you.
2. If you cannot find a value in the supplied text, or are not confident it is \
present, omit that field entirely rather than guessing. A missing field is honest; \
a fabricated one is not.
3. "value" is your normalized reading (e.g. dated as YYYY-MM-DD, chainage as \
"Km 12+400"), but "verbatim" is always the literal source text you read it from — \
these can differ (e.g. value "2024-03-12", verbatim "12.03.2024"). Normalization \
applies ONLY to dates and chainage. For letter_ref and cited_refs, "value" must be \
IDENTICAL to "verbatim", character for character — a reference number is an \
identifier, not something to reformat, "clean up", or re-type from memory. If you \
are not certain of every character in a reference number, lower your confidence \
and copy exactly what you see rather than producing a plausible-looking one.
4. cited_refs are any other letter/document reference numbers this letter mentions \
(e.g. "with reference to AE/PKG3/2024/091").
5. A single document may contain more than one physical letter (a covering letter \
plus enclosures) — return one array entry per distinct letter, with its own page range."""


@dataclass(frozen=True)
class ExtractionUsage:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int


@dataclass(frozen=True)
class ExtractionResult:
    raw: dict
    usage: ExtractionUsage
    request_id: str | None


def build_page_content(page_texts: dict[int, str]) -> str:
    parts = []
    for page_no in sorted(page_texts):
        parts.append(f"--- PAGE {page_no} ---\n{page_texts[page_no]}")
    return "\n\n".join(parts)


def extract_document(
    client: genai.Client,
    *,
    contract_conditions: str,
    package_context: str,
    page_texts: dict[int, str],
) -> ExtractionResult:
    """One Gemini call per document (not per page) — batches pages together so the
    model can see cross-page context (a letter spanning pages 1-2). See
    PIPELINE.md § S3. No prompt caching: Gemini's context caching has a minimum
    token threshold that a single-letter document won't reliably clear, and it
    isn't available the same way on the free tier, so it's skipped rather than
    silently assumed to be saving anything."""
    system_instruction = (
        f"{SYSTEM_PROMPT}\n\nCONTRACT CONDITIONS:\n{contract_conditions}\n\n"
        f"PACKAGE CONTEXT:\n{package_context}"
    )

    response = client.models.generate_content(
        model=MODEL,
        contents=build_page_content(page_texts),
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_json_schema=EXTRACTION_SCHEMA,
        ),
    )

    parsed = json.loads(response.text) if response.text else {}
    um = response.usage_metadata
    usage = ExtractionUsage(
        input_tokens=um.prompt_token_count or 0 if um else 0,
        output_tokens=um.candidates_token_count or 0 if um else 0,
        cache_read_tokens=(um.cached_content_token_count or 0) if um else 0,
        cache_creation_tokens=0,
    )
    return ExtractionResult(raw=parsed, usage=usage, request_id=response.response_id)
