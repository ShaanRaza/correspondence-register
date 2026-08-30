# PIPELINE.md

How a letter moves from PDF to register entry. Nine stages, each a row in `ingestion_jobs`, each resumable.

```
PDF bytes
  │
S0 INTAKE        SHA-256 → identity. Duplicate detection. Original written once, never again.
  │
S1 RASTERIZE     300 DPI, deskew, despeckle, threshold → page images
  │
S2 OCR           provider → page text + word tokens with normalized bboxes
  │
S3 EXTRACT       Claude Opus 5, strict schema, every field carries a VERBATIM substring
  │
S4 VALIDATE      deterministic. verbatim must be findable in the OCR text, or the field dies.
  │
S5 MAP           char offsets → tokens → bounding rects
  │
S6 ASSEMBLE      letters split out, serial assigned deterministically
  │
S7 LINK          citations resolved, threads materialized
  │
S8 PUBLISH       run marked current in one transaction. Register entry appears.
```

S6–S8 run in a **single transaction**. A half-extracted letter never appears in the register.

---

## S0 — Intake

```
sha256 = SHA256(bytes)
```

That hash is the document's identity for the rest of its life.

- If `documents.sha256` exists **and** is already linked to this package → duplicate. No new register entry. Recorded in the job result and surfaced, because "you sent us this letter twice" is useful.
- If it exists but is linked to a *different* package → link it here too. One set of bytes, stored once.
- Otherwise insert `documents`, write bytes to `documents/{sha256[0:2]}/{sha256}`, insert `package_documents`.

**The original is immutable from this instant.** No later stage writes to that key. Every derived artifact goes to `derived/{pipeline_version}/{sha256}/...`.

## S1 — Rasterize

Render each page at 300 DPI, then deskew, despeckle, and adaptive-threshold. On this document population — photocopied, faxed, re-scanned Authority Engineer letters — preprocessing is frequently worth more accuracy than changing OCR vendor.

Writes `document_pages` and the page rasters. Keyed by pipeline version, so re-deriving never collides with what is already there.

## S2 — OCR

```python
class OcrProvider(Protocol):
    name: str
    version: str
    def recognize(self, image: bytes, page_no: int) -> OcrPage: ...

@dataclass(frozen=True)
class OcrToken:
    text: str
    char_start: int
    char_end: int
    bbox: Rect          # normalized 0..1, resolution-independent
    confidence: float

@dataclass(frozen=True)
class OcrPage:
    text: str           # reading-order serialization
    tokens: list[OcrToken]
```

Implementations: `GoogleDocumentAiOcr`, `TesseractOcr`, `FixtureOcr`.

**The invariant every adapter must satisfy, asserted on every page:**

```python
for t in page.tokens:
    assert page.text[t.char_start:t.char_end] == t.text
```

If an adapter violates this, the adapter is wrong. Everything downstream — validation, highlighting, the click-through in job 5 — rests on this single equality. Assert it in production, not just in tests.

Persists `page_ocr`; the raw provider response goes to object storage and is referenced by `extraction_runs.ocr_response_uri`.

## S3 — LLM extraction

Model `claude-opus-5`. Verified against the official docs on 2026-08-30 — see [STACK.md](STACK.md).

Request shape:

```python
client.messages.parse(
    model="claude-opus-5",
    max_tokens=8000,
    thinking={"type": "adaptive"},
    output_config={"format": {...}, "effort": "high"},
    system=[
        {"type": "text", "text": CONTRACT_CONDITIONS,      # stable
         "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": CLAUSE_LIST_AND_PARTIES,  # stable per package
         "cache_control": {"type": "ephemeral"}},
    ],
    messages=[{"role": "user", "content": [
        {"type": "image", "source": {...}},                 # the page raster
        {"type": "text",  "text": page_ocr.text},           # VOLATILE — after the last breakpoint
    ]}],
)
```

- **Cache the prefix.** Contract conditions, clause list and party roster are byte-identical for every letter in a package. Render order is `tools` → `system` → `messages`, and volatile content must sit after the last breakpoint. Verify `usage.cache_read_input_tokens` is non-zero across consecutive calls; a timestamp anywhere in the prefix silently destroys the benefit.
- **Strict structured output.** `strict: true`, `additionalProperties: false`, `required` on every object.
- **The page image goes alongside the OCR text, not instead of it.** The image helps with tables, stamps and marginalia. The OCR text is the anchor, because it is what carries geometry.

Every field is returned as an object, never a bare scalar:

```json
{
  "letter_ref": {"value": "NHAI/PKG3/2024/117", "verbatim": "NHAI/PKG3/2024/117", "page": 1},
  "dated":      {"value": "2024-03-12",         "verbatim": "12.03.2024",         "page": 1},
  "chainage":  [{"value": "12400-14250",        "verbatim": "Km 12+400 to Km 14+250", "page": 2}],
  "cited_ref": [{"value": "AE/PKG3/2024/091",   "verbatim": "AE/PKG3/2024/091",   "page": 1}]
}
```

The prompt states the rule directly:

> Copy `verbatim` character-for-character from the supplied page text. Do not paraphrase, correct spelling, expand abbreviations, or normalize formatting — normalization happens downstream. If you cannot find the value in the supplied text, return null.

`llm_request_id` and token usage are written to `extraction_runs` for audit.

## S4 — Deterministic validation

**No model is involved in this stage.** This is the gate that makes the product evidentiary rather than generative.

For each returned field:

1. `verbatim` non-empty, `page` in range.
2. `page_text.find(verbatim)` → hit ⇒ `validation = 'exact'`.
3. Miss ⇒ normalize both sides (Unicode NFC, collapse whitespace, strip zero-width joiners) and retry, carrying an index map so offsets resolve back to the original text ⇒ `validation = 'normalized_exact'`.
4. Still a miss ⇒ `validation = 'unresolved'`. **No bounding box is stored**, and the letter becomes `needs_review`.
5. Type validation on `value`: dates parse to a real calendar date; chainage matches `Km\s*\d+\+\d{3}`; clause exists in the package's clause list; `letter_ref` matches `packages.ref_pattern`.
6. Cross-field checks: `received >= dated` (enforced by a table CHECK too); `dated` within the contract period (warn, don't reject); a citation to a reference dated *after* the citing letter is flagged.

Any failure flags. Nothing is silently repaired. The schema enforces the consequence — an `unresolved` row is forbidden by CHECK constraint from carrying geometry, so an unlocatable value cannot accidentally acquire a highlight.

Step 3 deserves care with this content: Devanagari normalization is not cosmetic. NFC vs NFD changes matra composition, and a careless `strip()` on a line ending in a combining mark corrupts it. Normalize with `unicodedata.normalize("NFC", s)` and never regex over Devanagari with `\w`.

## S5 — Provenance mapping

```
(page_no, char_start, char_end)
   → tokens whose [cs, ce) overlaps that span
   → their normalized rects
   → {union: <bounding rect>, rects: [<per-token rects>]}
```

**Both are stored.** The per-token rects matter: a subject line wrapping across two lines needs two rectangles. A single union box would span the full width between them and highlight text that is not the value — precisely the imprecision this audience notices first.

Written to `extracted_fields.bbox`, normalized 0..1, so the viewer renders at any zoom without re-deriving.

## S6 — Assembly and serial assignment

- Split the document into letters. A PDF routinely holds a covering letter plus enclosures; a new letter is detected by a fresh reference-header block. `page_from`/`page_to` locate each within the document.
- Derive `direction` from `from_party`/`to_party` relative to the contractor party.
- **Assign serials deterministically.** Sort candidate letters by `(dated, letter_ref_normalized, document_sha256, page_from)` and assign from `packages.next_serial` in that order, under a row lock on `packages`.

That sort key is what makes the whole thing reproducible: the same document set produces the same serials on every rebuild, regardless of the order files were processed or how many workers ran. Serials are never reused and never reordered — sorting the register changes the view, never the `SR` column.

## S7 — Citation resolution and threading

- Normalize each `cited_ref` and look it up in `letters.letter_ref_normalized` within the package.
- Exactly one match ⇒ `resolved`. No match ⇒ `unresolved_missing`. More than one ⇒ `unresolved_ambiguous`, and the letter goes to review.
- Compute connected components over resolved citations, scoped to the package, with a recursive CTE. Materialize `thread_id`; `thread_key` is the `letter_ref` of the earliest member, so thread identity is **derived, not random**. Bump `thread_version`.

`unresolved_missing` is not an error state — it is the product's strongest completeness signal, exposed through the `missing_references` view. The register can report what is missing from itself: *"This thread cites AE/PKG3/2024/091, which you have not supplied."* For a tool whose claim is that nothing is missed, that is the most convincing thing on the screen.

## S8 — Publish

Mark the run `is_current`, mark any previous run for that document `superseded` with `superseded_by` set. A partial unique index guarantees only one current run per document. The register entry becomes visible.

---

## Demo: offline and reproducible

```
fixtures/
  documents/                     # the 10 source PDFs
  ocr/{sha256}/page-{n}.json     # frozen OCR output
  llm/{sha256}.json              # frozen extraction responses
  manifest.json                  # sha256 → filename, pipeline_version
  expected/register.json         # committed snapshot of the resulting register
```

`FixtureOcrProvider` and `FixtureLlmClient` implement the same protocols as the live ones and are selected by `PIPELINE_MODE=fixture|live`. Nothing else in the codebase knows which is in use.

**Only S2 and S3 are replayed. S0, S1 and S4–S8 run for real.** The demo therefore exercises hashing, validation, offset mapping, bbox derivation, serial assignment, citation resolution and threading — all the logic where correctness actually lives — while making zero network calls.

```bash
make ingest          # runs the real pipeline against fixture providers
make verify-fixtures # re-runs and diffs against fixtures/expected/register.json
```

`verify-fixtures` is the guard that a refactor did not change the register. Serials, thread keys, field values, validation states and bounding boxes are all compared.

The fixtures were themselves produced by a live run and committed. Switching to production is `PIPELINE_MODE=live` plus credentials — no code path changes.

### Storage interface

```python
class BlobStore(Protocol):
    def put(self, key: str, data: bytes, *, immutable: bool = True) -> str: ...
    def get(self, key: str) -> bytes: ...
    def uri(self, key: str) -> str: ...
```

`LocalBlobStore` for the demo, `S3BlobStore` for production, identical key layout. Migration is a directory copy; `immutable=True` becomes an Object Lock retention header instead of a no-op.

### Demo posture

Ingest ahead of time and ship the results. A demo that runs OCR and an LLM live over meeting-room wifi is a demo that fails in front of the one prospect who matters. The pipeline should be demonstrable on request, not load-bearing during the meeting.

Leave two or three documents genuinely `needs_review`, and at least one `unresolved_missing` citation. A register claiming 10 of 10 perfect extractions on scanned Indian highway correspondence is *less* credible than one that says `3 documents need review` and shows exactly why.

---

## Verification status

Honest accounting of what has and has not been checked.

| Item | Status |
|---|---|
| Model ID, context, pricing | **Verified** against platform.claude.com models overview and pricing pages, 2026-08-30 |
| `db/schema.sql` executes | **Not verified.** No Postgres server or Docker on this machine — libpq client tools only. Reviewed by hand; two defects found and fixed (unnecessary `btree_gist`; `UNIQUE` needing `NULLS NOT DISTINCT` for nullable `letter_id`). Run it against PG ≥ 15 with pgvector before trusting it. |
| Pipeline stages | Design only. No code written yet. |

