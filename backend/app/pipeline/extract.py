"""S3 — LLM extraction. OpenAI structured outputs. Every field carries a VERBATIM
substring the model claims to have copied from the OCR text. This module never
decides whether that claim is true — that's S4's job (validate.py). The model
proposes; only deterministic code locates.

Provider history, kept because it explains the shape of this file: originally
Claude Opus 5 (see STACK.md), then Gemini when Anthropic billing wasn't
available, now OpenAI. The pipeline contract has never changed — one call per
document, strict JSON schema, verbatim required for every value — so swapping
providers only touches this module plus the client construction in main.py.

API shape verified against the installed openai SDK (3.6.0) by introspecting
`chat.completions.create` and `CompletionUsage`, not from memory: assumptions
about provider APIs have already gone stale once in this project.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

from openai import OpenAI

# Overridable per deployment without a code change. gpt-4o-mini is the default
# because this task is extraction rather than reasoning -- the model is copying
# spans out of supplied text, and a small fast model keeps per-document latency
# (the dominant cost of a batch upload) low.
DEFAULT_MODEL = "gpt-4o-mini"

# Any OpenAI-compatible gateway works, OpenRouter included: it speaks the same
# /chat/completions contract, so only the base URL and the model naming change.
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def resolve_base_url(api_key: str) -> str | None:
    """Where to send requests. Explicit config wins; otherwise an OpenRouter key
    is recognised by its own prefix so a key pasted into the browser upload panel
    reaches the right host without any server-side configuration -- that path has
    no env vars to set."""
    explicit = os.environ.get("OPENAI_BASE_URL")
    if explicit:
        return explicit.rstrip("/")
    if api_key.startswith("sk-or-"):
        return OPENROUTER_BASE_URL
    return None  # the SDK's own default (api.openai.com)


def resolve_model(base_url: str | None) -> str:
    """OpenRouter namespaces every model by provider ('openai/gpt-4o-mini'); a
    bare name is rejected there. Prefixing a name that has no '/' keeps one
    OPENAI_MODEL value working against either backend, and an explicitly
    namespaced value (including a non-OpenAI one) is passed through untouched."""
    model = os.environ.get("OPENAI_MODEL") or DEFAULT_MODEL
    if base_url and "openrouter.ai" in base_url and "/" not in model:
        return f"openai/{model}"
    return model


def make_client(api_key: str) -> OpenAI:
    base_url = resolve_base_url(api_key)
    return OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)

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

# Nullable rather than omitted: OpenAI's strict json_schema mode requires EVERY
# property to appear in `required`, so "this letter has no inward stamp" has to
# be expressed as an explicit null instead of a missing key.
_FIELD_STR_NULLABLE = {
    "type": ["object", "null"],
    "additionalProperties": False,
    "required": ["value", "verbatim", "page"],
    "properties": {
        "value": {"type": "string"},
        "verbatim": {"type": "string"},
        "page": {"type": "integer"},
    },
}

_LETTER_ITEM = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "page_from", "page_to", "letter_ref", "dated", "received",
        "from_party", "to_party", "subject", "chainage", "clause", "cited_refs",
    ],
    "properties": {
        "page_from": {"type": "integer"},
        "page_to": {"type": "integer"},
        "letter_ref": _FIELD_STR,
        "dated": _FIELD_STR,
        "received": _FIELD_STR_NULLABLE,
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
present, use null for that field (or an empty array) rather than guessing. A \
missing field is honest; a fabricated one is not.
3. "value" is your normalized reading (e.g. dated as YYYY-MM-DD, chainage as \
"Km 12+400"), but "verbatim" is always the literal source text you read it from — \
these can differ (e.g. value "2024-03-12", verbatim "12.03.2024"). Normalization \
applies ONLY to dates and chainage. For letter_ref and cited_refs, "value" must be \
IDENTICAL to "verbatim", character for character — a reference number is an \
identifier, not something to reformat, "clean up", or re-type from memory. If you \
are not certain of every character in a reference number, copy exactly what you \
see rather than producing a plausible-looking one.
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
    model: str
    # Wall-clock seconds for the LLM call alone. Recorded because "uploads feel
    # slow" is not actionable without knowing whether the time went to OCR
    # (local CPU) or to the model provider (network + queue), and the two have
    # completely different fixes.
    llm_seconds: float


def build_page_content(page_texts: dict[int, str]) -> str:
    parts = []
    for page_no in sorted(page_texts):
        parts.append(f"--- PAGE {page_no} ---\n{page_texts[page_no]}")
    return "\n\n".join(parts)


def extract_document(
    client: OpenAI,
    *,
    model: str,
    contract_conditions: str,
    package_context: str,
    page_texts: dict[int, str],
) -> ExtractionResult:
    """One call per document (not per page) — batches pages together so the model
    can see cross-page context, e.g. a letter spanning pages 1-2. See
    PIPELINE.md § S3."""
    system = (
        f"{SYSTEM_PROMPT}\n\nCONTRACT CONDITIONS:\n{contract_conditions}\n\n"
        f"PACKAGE CONTEXT:\n{package_context}"
    )

    started = time.monotonic()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": build_page_content(page_texts)},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "correspondence_extraction",
                "strict": True,
                "schema": EXTRACTION_SCHEMA,
            },
        },
    )

    llm_seconds = time.monotonic() - started
    content = response.choices[0].message.content
    parsed = json.loads(content) if content else {}

    u = response.usage
    # cached_tokens lives under prompt_tokens_details when the provider reports
    # it; absent on many responses, so read defensively rather than assume.
    cached = 0
    if u is not None and getattr(u, "prompt_tokens_details", None) is not None:
        cached = getattr(u.prompt_tokens_details, "cached_tokens", 0) or 0

    usage = ExtractionUsage(
        input_tokens=(u.prompt_tokens if u else 0) or 0,
        output_tokens=(u.completion_tokens if u else 0) or 0,
        cache_read_tokens=cached,
        cache_creation_tokens=0,
    )
    print(
        f"[llm] model={model} {llm_seconds:.2f}s "
        f"in={usage.input_tokens} out={usage.output_tokens}",
        flush=True,
    )
    return ExtractionResult(
        raw=parsed, usage=usage, request_id=response.id, model=model,
        llm_seconds=llm_seconds,
    )
