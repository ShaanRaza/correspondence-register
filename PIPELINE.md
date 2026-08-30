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

S6–S8 run in a **single transaction**, and that transaction contains only fast, deterministic database operations — assembling letters from already-validated fields, resolving citations, computing threads, flipping `is_current`. **No OCR call, no LLM call, and no object-storage upload ever happens inside it** (those are S1–S3, separate jobs that complete beforehand). A half-extracted letter never appears in the register, and the transaction never holds a lock for the duration of a network call.

`ingestion_jobs.job_type` (S0 intake, S1 rasterize, S2 ocr, S3 extract, S4 validate, S5 assemble, S6 link, S7 embed) is not a 1:1 mirror of the nine stages above, deliberately: S5 (map) is folded into the `validate` job — it's cheap, deterministic, and runs in the same worker invocation as S4, with no separate queue hop earning its keep — and S8 (publish) is the transaction boundary at the end of the `link` job, not an independently queued unit of work, since a publish is a database commit, not a task that can retry or fail independently of the link step it closes. `embed` (pgvector) has no corresponding S-stage above because it's off the critical evidentiary path entirely — optional, deferred to production per STACK.md, and can run whenever convenient without affecting the register.

---

## S0 — Intake

```
sha256 = SHA256(bytes)
```

That hash is the document's identity for the rest of its life.

- If `documents.sha256` exists **and** is already linked to this package → duplicate. No new register entry. Recorded in the job result and surfaced, because "you sent us this letter twice" is useful.
- If it exists but is linked to a *different* package → link it here too. One set of bytes, stored once.
- Otherwise insert `documents`, write bytes to `documents/{sha256[0:2]}/{sha256}`, insert `package_documents`.

**The original is immutable from this instant.** No later stage writes to that key, and the database enforces it — `documents` rejects every `UPDATE` and `DELETE` via trigger, not just by convention. Every derived artifact goes to `derived/{pipeline_version}/{sha256}/...`.

**Before ever serving a document as evidence — display, download, or annexure — re-verify `SHA256(fetched bytes) == documents.sha256`.** The stored `storage_uri` is a hint about where to look, not the authority on what the bytes are; only the hash is. This check is cheap and belongs in the serving path, not just at ingestion.

## S1 — Rasterize

Render each page at 300 DPI. **Preprocessing beyond that (deskew, despeckle, adaptive-threshold) is a policy to benchmark, not a pipeline to apply blindly.** Google Document AI already does its own rotation correction and image-quality handling, and aggressive thresholding on this document population can destroy exactly the things that matter — faint stamps, signatures, coloured annotations, marginal notes, thin Devanagari strokes. Before locking a default, run raw / deskew-only / deskew+despeckle / deskew+threshold against the same 10–20 real documents and pick the one that actually extracts better, not the one that looks cleaner to a human. Whatever is chosen becomes a named key in `pipeline_versions.config`, so a policy change is a new pipeline version, not a silent behavior change.

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

This is **exact code-point equality**, not byte-identity — the two are not the same thing here. Two Unicode strings can be code-point-identical and still differ in bytes depending on encoding, and Devanagari specifically has NFC/NFD normalization ambiguity (matra composition differs between forms). "Byte-identical" is the right word for the SHA-256 document check in S0; it's the wrong word for this OCR/text equality, and using it here invites comparing raw bytes instead of decoded strings. If an adapter violates the assertion above, the adapter is wrong. Everything downstream — validation, highlighting, the click-through in job 5 — rests on this single equality. Assert it in production, not just in tests.

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
6. Cross-field checks, all **flags, never rejections** — an evidentiary register must not let the database refuse messy real evidence: `received < dated` (a misapplied stamp or retrospective receipt does happen); `dated` outside the contract period; a citation to a reference dated *after* the citing letter. Each sets the letter to `needs_review` with a `review_events` note naming the anomaly; none blocks ingestion. (Revision 2 removed the `received >= dated` CHECK constraint that used to enforce this at the database level — rejecting the row was the wrong failure mode.)

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

- Split the document into letters. A PDF routinely holds a covering letter plus enclosures; a new letter is detected by a fresh reference-header block. `page_from`/`page_to` locate each within the document — this is the document-to-letter cardinality, one document producing many letter rows, and it needs no separate table.
- Derive `direction` from `from_party`/`to_party` relative to the contractor party.
- **Detect duplicate `letter_ref` within the package.** `(package_id, letter_ref_normalized)` is *not* a database-enforced unique constraint (revision 2 dropped it) — real OCR output produces genuine duplicates: re-scans, misassigned reference numbers, revision letters sharing a base reference. A collision routes **both** letters to `needs_review` with a `review_events` note identifying the conflict. The database records the fact; it never decides which one is right.
- **Assign serials deterministically.** Sort candidate letters by `(dated, letter_ref_normalized, document_sha256, page_from)` and assign from `packages.next_serial` in that order, under a row lock on `packages`, in the **same transaction** as the letter insert.

**What "deterministic" actually guarantees, precisely.** That sort key makes a *batch* assignment reproducible: re-running the algorithm over the same, complete, fixed set of documents (a full package reprocessing, or the initial demo load) always produces the same serial-to-letter mapping, regardless of worker count or execution order. It does **not** mean the global sequence is stable under incremental, real-world ingestion — a letter dated 12 Mar that arrives on a Tuesday *after* letters dated 13 Apr were already serialed on Monday gets the next available serial (Tuesday's), not a slot ahead of Monday's letters. An earlier version of this document overstated the guarantee. The actual, load-bearing guarantee is the one the schema enforces: **serial is immutable once assigned, forever, regardless of what arrives later.** Reproducibility means replaying history reproduces the same serials, not that a full re-sort of today's complete document set would put every serial back where a hypothetical from-scratch run would have. Serials are never reused and never reordered — sorting the register changes the view, never the `SR` column.

**On gaps.** Because serial assignment and the letter insert share one transaction, a crash mid-assignment rolls back both — a crashed worker cannot leave a gap. A gap can still appear later, deliberately: if a letter is found to be a duplicate or misfiled after its serial was assigned, it is **voided** (`letters.voided_at`, `void_reason`), never deleted and never renumbered. `17, 18, 20` with `19` permanently voided is correct; silently collapsing `20` back to `19` is not — that would be re-numbering evidence after the fact.

## S7 — Citation resolution and threading

- Normalize each `cited_ref` and look it up in `letters.letter_ref_normalized` within the package.
- Exactly one match ⇒ `resolved`. No match ⇒ `unresolved_missing`. More than one ⇒ `unresolved_ambiguous`, and the letter goes to review.
- Compute connected components over resolved citations, scoped to the package, with a recursive CTE. Materialize into `threads.id` (a uuid, assigned once) — **that** is the actual stable identity everything else keys on (`letters.thread_id`, `thread_memberships`). `thread_key` (the `letter_ref` of the *current* earliest member) is a recomputed **display label**, not an identity: if a letter dated earlier than every existing member later arrives, the label changes to reflect the new earliest member, exactly as it should. An earlier version of this document called `thread_key` itself "derived, not random" in a way that implied permanence it doesn't have — the permanence lives in `thread_id`, which nothing here ever reassigns. Bump `thread_version` and insert a `thread_memberships` row for every member on every recompute, so a past version's exact membership is always reconstructable even after the label has moved on.

`unresolved_missing` is not an error state — it is the product's strongest completeness signal, exposed through the `missing_references` view. The register can report what is missing from itself: *"This thread cites AE/PKG3/2024/091, first referenced on 12 Mar 2024, which you have not supplied."* (The date attached is the **citing** letter's date — the only date the system actually has; the missing letter's own date is, definitionally, unknown. An earlier draft of this example attributed a date to the missing letter itself, which is not something the system can know.) For a tool whose claim is that nothing is missed, that is the most convincing thing on the screen.

## S8 — Publish

Mark the run `is_current`, mark any previous run for that document+package `superseded` with `superseded_by` set. A partial unique index guarantees only one current run per (document, package). The register entry becomes visible.

## Reprocessing an already-published document

This is new behavior this document didn't previously describe, added because the schema didn't previously support it correctly: revision 2's `register` view had no `is_current` filter on `letters` at all, so reprocessing a document — a prompt improvement, a fix for a garbled reference — would have shown **both** the old and the new letter rows, silently duplicating the register. Fixed by applying the same append-only pattern already used for `extraction_runs` and `extracted_fields` to `letters` itself: `is_current`/`superseded_by`, with `(package_id, serial)` as the immutable **logical** identity carried across versions.

What's genuinely new, and can't be a database constraint because it requires judgment, is **matching**: when a new extraction run produces a candidate letter, S6 must decide whether it's a new version of an existing logical letter or a brand-new one.

1. **Primary match: exact `letter_ref_normalized` within the package**, scoped to `is_current` letters only. A match means "same logical letter" — the new candidate inherits that letter's `serial`.
2. **Fallback: page-range overlap on the same `document_sha256`.** Covers the case the new OCR fixed a previously-garbled reference, so the ref no longer matches, but the candidate demonstrably covers the same pages of the same document as an existing current letter.
3. **No confident match by either rule → flag, don't guess.** Insert as a new logical letter with a freshly-assigned serial, but mark it `needs_review` with a note that it arrived from a reprocessing run and could not be matched to prior history — a human confirms whether it's genuinely new or should be merged. This mirrors the letter_ref-collision handling in S6 above: the database records the ambiguity, it never resolves it silently.

Once matched (or confirmed new), the actual supersede is three ordered statements — proven necessary by running the equivalent operation on `extracted_fields` against a live Postgres 18 and hitting both failure modes a naive two-step version doesn't anticipate:

```sql
INSERT INTO letters (..., is_current) VALUES (..., false);  -- not yet current: satisfies the FK and the partial unique index
UPDATE letters SET is_current = false, superseded_by = :new_id WHERE id = :old_id;  -- vacate the slot
UPDATE letters SET is_current = true WHERE id = :new_id;                            -- take it
```

The old letter's `extracted_fields`, `citations`, and `review_events` all remain exactly as they were — fully queryable as history — because nothing about a supersede deletes or rewrites them. Only the `register` view (which filters `WHERE l.is_current`) and any other live-facing query stop showing the old version once the new one takes its place.

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
| `db/schema.sql` executes (revision 2) | **Verified.** `brew install postgresql@18 pgvector` provisioned a real server; schema applied clean to PG 18.6 + pgvector 0.8.6. See DATA_MODEL.md § Review response for the full account, including two bugs in `record_field_correction()` that only surfaced by running it. |
| `db/schema.sql` executes (revision 3) | **Verified**, same server. Composite FKs (letter↔run, letter↔thread/party by package, field↔page_ocr), the letter-versioning supersede path, `refresh_letter_review_status`, and the multi-embedding `letter_embeddings` shape were each exercised directly — not just applied — including the register view actually returning one row, not two, for a reprocessed letter. See DATA_MODEL.md § Review response, round 2. |
| Job lease recovery | Reaper query documented in `db/schema.sql`; not yet run under an actual worker crash. |
| Pipeline stages (S0–S8) | Design only. No pipeline code written yet. |
| Reprocessing / letter-versioning matching logic (S6) | Design only. The supersede mechanics are schema-verified; the letter_ref/page-range matching heuristic is not yet implemented or tested against real reprocessing data. |

