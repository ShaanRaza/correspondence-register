# DATA_MODEL.md

PostgreSQL is the single source of truth. No Neo4j, no Redis, no separate vector store. pgvector is present but explicitly non-authoritative.

Full DDL: [db/schema.sql](db/schema.sql). This document explains the decisions.

---

## Principles the schema enforces

1. **A document's identity is the SHA-256 of its bytes.** Not a UUID, not a filename. You can prove the file behind an annexure is byte-identical to what was ingested.
2. **Originals are immutable.** Everything derived (rasters, OCR, extractions) is keyed by `(source_hash, pipeline_version)` and can be rebuilt without touching them.
3. **Every extracted value carries its provenance or it is not a value.** An extraction whose verbatim substring cannot be located in the OCR text is stored as `unresolved` with no bounding box, and its letter is flagged. It is never silently repaired.
4. **The register serial is immutable and deterministic.** Sorting the view never changes it, and rebuilding from the same documents reproduces it exactly.
5. **Thread membership is materialized and versioned.** A thread cannot silently recompute differently between two viewings of the same claim.
6. **Absence is data.** A citation to a letter we do not hold is a first-class row, not a null.

---

## Entities

### `contractors`, `packages`, `parties`

`parties` is per-package, not global: the Authority Engineer firm differs between packages, and `CTR → AE` on the register must resolve to the right legal entity for the package in front of you. Each party has a `short_code` (`CTR`, `AE`, `PD`) — that is the string DESIGN.md's `PARTIES` column renders.

Package chainage is `int4range` in **metres**. `Km 12+400` is `12400`. This is what makes job 2's chainage filter an indexed overlap query rather than application logic.

### `documents` and `package_documents`

`documents` is keyed by `sha256` globally and joined to packages through `package_documents`. That split does real work: re-ingesting the same PDF is detected as a duplicate rather than creating a second register entry, and the same letter legitimately filed against two packages is stored once.

`documents` has no `updated_at`. Nothing updates it.

### `pipeline_versions`

An extraction is only reproducible if you know the exact prompt and schema that produced it, so both are hashed:

| Column | Why |
|---|---|
| `ocr_provider`, `ocr_provider_version` | which OCR read the page |
| `llm_model` | e.g. `claude-opus-5` |
| `prompt_sha256` | hash of the exact prompt template bytes |
| `schema_sha256` | hash of the extraction JSON Schema bytes |

Change any of these and you have a new pipeline version. Derived artifacts are re-created under the new version; old ones stay, so you can always answer "which pipeline produced this value".

### `page_ocr`

OCR output is stored as **one row per page** with a `text` column (reading-order serialization) and a `tokens` JSONB array — not one row per word.

Word rows would be 240M rows at production scale for data that is only ever read a whole page at a time, to draw highlights. JSONB is compact, fetched in one read, and needs no index it would not otherwise get.

Token geometry is stored **normalized to 0..1**, not pixels. The viewer can render at any zoom or DPI without re-deriving anything, and the coordinates survive a change of raster resolution.

**Invariant, asserted in code:** for every token, `page_ocr.text[token.cs : token.ce] == token.t`. Every provider adapter must satisfy it. The entire provenance chain rests on this one equality.

### `extraction_runs`

One row per (document, pipeline_version) attempt. Carries `llm_request_id`, token usage, and status. A partial unique index enforces that at most one run per document is `is_current`; superseding a run is an explicit transition, not an overwrite.

### `letters`

The register entry. **Separate from `documents`** because a single PDF frequently contains several letters plus their enclosures — `page_from`/`page_to` locate the letter inside the document.

`dated` and `received` are separate columns and neither is backfilled from the other, per DESIGN.md. `direction` is derived from `from_party`/`to_party` relative to the contractor and stored, because DESIGN.md encodes direction by row position and the query should not have to work it out.

`serial` is the immutable register number, unique per package. See [PIPELINE.md](PIPELINE.md) § S6 for how it is assigned deterministically.

### `extracted_fields`

The heart of the system. One row per extracted value, including repeated values (`field_index` for the 2nd and 3rd chainage on a letter).

| Column | Meaning |
|---|---|
| `value_text` | the **normalized** value (`2024-06-14`, `12400`) |
| `value_verbatim` | the **exact substring** the model returned |
| `page_no`, `char_start`, `char_end` | resolved position in `page_ocr.text` |
| `bbox` | union rect **and** the per-token rects, normalized |
| `validation` | `exact` / `normalized_exact` / `unresolved` |

`bbox` keeps the individual token rectangles, not only the union. A subject line that wraps across two lines needs two rectangles; a single union box would cover the whole paragraph between them and highlight text that is not the value. That is the kind of imprecision this audience notices immediately.

`validation` is the deterministic gate made durable:

- `exact` — the verbatim string was found byte-identical in the page text.
- `normalized_exact` — found only after Unicode NFC normalization and whitespace collapse. Legitimate, recorded as weaker.
- `unresolved` — **not found.** No bounding box is stored, and the letter becomes `needs_review`.

### `citations`

Letter-to-letter, one row per `Ref:` the model found, each pointing back at the `extracted_field` that located it on the page.

`resolution` has three values and the second is a feature, not an error state:

- `resolved` — the cited reference matches a letter we hold.
- `unresolved_missing` — **the letter cites a reference that is not in the register.**
- `unresolved_ambiguous` — matches more than one letter; flagged for review.

`unresolved_missing` is the strongest completeness signal the product has: the register can tell you what is missing from itself. *"This thread cites AE/PKG3/2024/091, dated before the letter that cites it, which you have not supplied."* That is worth building the demo around, and it falls straight out of this table.

### `threads`

Materialized connected components over resolved citations, scoped to a package. `thread_key` is the `letter_ref` of the earliest member, which makes thread identity **derivable rather than random** — a rebuild produces the same threads with the same keys. `thread_version` increments on every recompute so you can tell whether two viewings of a claim saw the same threading.

### `letter_chainages`, `letter_clauses`

Denormalized from `extracted_fields` purely so job 2 can be an indexed query. `letter_chainages.chainage_m` is an `int4range` with a GiST index; the filter is a range overlap. Each row keeps its `extracted_field_id`, so a chainage you filtered on is still one click from the page it came from.

### `review_events` and `review_status`

`review_events` is the append-only audit of human action (`verified` / `rejected` / `corrected`, with old and new values). `letters.review_status` is materialized from it and from field validation, by this rule:

```
IF any field on the letter has validation = 'unresolved'
   OR any citation is 'unresolved_ambiguous'      → 'needs_review'
ELSE IF a review_event has verified the letter    → 'verified'
ELSE                                              → 'unverified'
```

Those are exactly DESIGN.md's three gutter states, including the one with no colour.

### `ingestion_jobs`

The Postgres-backed queue, claimed with `FOR UPDATE SKIP LOCKED`. It doubles as the ingestion audit trail, which this product needs to keep regardless — that is the argument for it over Redis and Celery.

### `letter_embeddings`

pgvector, in its own table, deliberately. It is not a column on `letters` because it is not authoritative evidence and the schema should say so. Nothing in the register's evidentiary path reads it.

---

## What the schema deliberately does not have

- **No `updated_at` on `documents` or `extracted_fields`.** Facts are superseded by a new run, not edited in place.
- **No soft-delete on letters.** A letter that was ingested was ingested.
- **No confidence score presented as a number to users.** OCR confidence is stored for triage; DESIGN.md forbids surfacing a score, and the schema's `validation` enum is the user-facing signal.
- **No `latency_days` column.** Elapsed days is computed in the query from two dates. The LLM extracts; the database computes.
