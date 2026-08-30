# DATA_MODEL.md

PostgreSQL is the single source of truth. No Neo4j, no Redis, no separate vector store. pgvector is present but explicitly non-authoritative.

Full DDL: [db/schema.sql](db/schema.sql). This document explains the decisions.

---

## Principles the schema enforces

1. **A document's identity is the SHA-256 of its bytes.** Not a UUID, not a filename. You can prove the file behind an annexure is byte-identical to what was ingested.
2. **Originals are immutable.** Everything derived (rasters, OCR, extractions) is keyed by `(source_hash, pipeline_version)` and can be rebuilt without touching them.
3. **Every extracted value carries its provenance or it is not a value.** An extraction whose verbatim substring cannot be located in the OCR text is stored as `unresolved` with no bounding box, and its letter is flagged. It is never silently repaired.
4. **The register serial is immutable once assigned — permanently, regardless of what arrives later.** Sorting the view never changes it. A *batch* rebuild over a fixed, complete document set reproduces the same mapping; incremental day-by-day ingestion does not retroactively renumber anything when a late, earlier-dated letter arrives — it gets the next available serial, not a slot implied by its date. Immutability is the guarantee that matters; batch-reproducibility is a narrower, secondary property. (Corrected — an earlier draft conflated the two. See § Review response, round 2, #2.)
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

`config` (JSONB) holds the rest of the reproducibility envelope that isn't its own column — rasterization DPI/preprocessing policy, alignment/threading/normalization algorithm versions, and the LLM `effort` level. An open bucket rather than a fixed column list, so a new knob doesn't force a migration; a `medium`-vs-`high` effort benchmark is then a comparison between two `pipeline_versions` rows, not an undocumented runtime flag.

### `page_ocr`

OCR output is stored as **one row per page** with a `text` column (reading-order serialization) and a `tokens` JSONB array — not one row per word.

Word rows would be 240M rows at production scale for data that is only ever read a whole page at a time, to draw highlights. JSONB is compact, fetched in one read, and needs no index it would not otherwise get.

Token geometry is stored **normalized to 0..1**, not pixels. The viewer can render at any zoom or DPI without re-deriving anything, and the coordinates survive a change of raster resolution.

**Invariant, asserted in code:** for every token, `page_ocr.text[token.cs : token.ce] == token.t`. Every provider adapter must satisfy it. The entire provenance chain rests on this one equality.

### `extraction_runs` and `llm_requests`

One row per (document, **package**, pipeline_version) attempt — package-scoped, not just document-scoped, because the LLM prompt embeds package-specific context (party names, clause list, contract conditions), so the same document filed against two packages can legitimately produce two different extractions. A partial unique index enforces that at most one run per (document, package) is `is_current`; superseding a run is an explicit transition, not an overwrite.

A single extraction attempt can issue more than one Claude request — one per page, or a chunked long document — so per-call cost and status live in `llm_requests` underneath the run; `extraction_runs.input_tokens`/`output_tokens`/`cache_read_tokens` are the running total across those calls, kept as a fast denormalized sum.

### `letters`

The register entry. **Separate from `documents`** because a single PDF frequently contains several letters plus their enclosures — `page_from`/`page_to` locate the letter inside the document; one document producing many `letters` rows through one `extraction_run` is the entire document-to-letter cardinality story, and needs no separate table.

`dated` and `received` are separate columns and neither is backfilled from the other, per DESIGN.md. `direction` is derived from `from_party`/`to_party` relative to the contractor and stored, because DESIGN.md encodes direction by row position and the query should not have to work it out.

**Versioned, the same way `extracted_fields` is.** `id` identifies one version of a letter; `(package_id, serial)` is the immutable *logical* identity, carried forward across versions by an `is_current`/`superseded_by` pair. This exists because a document can be re-extracted (a pipeline improvement, a fix for a garbled reference), and without it the register had no way to represent "this is a better version of a letter already on file" — it would have shown both the old and new extraction as separate register rows. See [PIPELINE.md](PIPELINE.md) § "Reprocessing an already-published document" for how a new run's candidates are matched against existing logical letters, and § S6 for how a brand-new logical letter's serial is assigned.

Composite foreign keys tie `thread_id` and `from_party_id`/`to_party_id` to the *same* `package_id` as the letter itself — two independently-valid foreign keys don't stop a letter from pointing at a thread or party belonging to a different package; these do.

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

- `exact` — the verbatim string was found as an exact code-point match in the page text. (Not "byte-identical" — that phrase is reserved for the SHA-256 document check; two code-point-identical strings can differ in raw bytes depending on encoding, and Devanagari's NFC/NFD ambiguity makes the distinction concrete here, not pedantic.)
- `normalized_exact` — found only after Unicode NFC normalization and whitespace collapse. Legitimate, recorded as weaker.
- `unresolved` — **not found.** No bounding box is stored, and the letter becomes `needs_review`.
- `human_corrected` — a reviewer supplied the value directly; geometry is optional, since a correction may not be locatable on the page at all.

Composite foreign keys tie a field to `(letter_id, extraction_run_id)` on `letters` and to `(extraction_run_id, page_no)` on `page_ocr` — closing the same class of hole as `letters`' composite FKs above: without them, a field could claim a letter from one run while pointing at another, or name a page with no OCR text under that run.

Versioned append-only, like `letters`: a correction inserts a new current row and marks the old one superseded; the machine's original value is never overwritten, only outranked. A trigger blocks any direct `UPDATE` to a content column, so the only way to change a value is through `record_field_correction()`, which writes the matching `review_events` row in the same transaction.

### `citations`, `citation_occurrences`, `citation_candidates`

`citations` is the deduplicated relationship — one row per (citing letter, cited reference) pair. Where on the page each mention actually appears lives separately, in `citation_occurrences`: a letter citing the same reference twice keeps both locations, each with its own `extracted_field` and therefore its own bounding box, rather than the relationship table silently keeping only one.

`resolution` has three values and the second is a feature, not an error state:

- `resolved` — the cited reference matches a letter we hold.
- `unresolved_missing` — **the letter cites a reference that is not in the register.**
- `unresolved_ambiguous` — matches more than one letter; the candidate set survives in `citation_candidates` (letter, match method, match score) so a reviewer has something to disambiguate from, rather than the database saying "ambiguous" and discarding exactly the information needed to resolve it.

`unresolved_missing` is the strongest completeness signal the product has: the register can tell you what is missing from itself. *"This thread cites AE/PKG3/2024/091, first referenced on 12 Mar 2024, which you have not supplied."* (The date is the citing letter's — the missing letter's own date is, definitionally, unknown.) That is worth building the demo around, and it falls straight out of this table. `missing_references` groups by `cited_ref_normalized`, not the verbatim text, so the same reference rendered two different ways in two different letters doesn't fragment into two "missing" rows.

Composite FKs tie `citing_letter_id`/`cited_letter_id`/`candidate_letter_id` to the citation's own `package_id`, for the same reason as `letters`' composite FKs: a citation must not be able to link letters across two different packages.

### `threads` and `thread_memberships`

Materialized connected components over resolved citations, scoped to a package. `threads.id` (a uuid, assigned once and never reassigned) is the actual stable identity — it's what `letters.thread_id` and `thread_memberships` key on. `thread_key` (the `letter_ref` of the *current* earliest member) is a recomputed **display label**, not an identity — it changes if a letter dated earlier than every existing member later arrives, and that's correct behavior, not instability. (An earlier draft described `thread_key` itself as the stable, derivable identity, which overstated it; nothing outside `threads` ever reads `thread_key` as a key.) `thread_version` increments on every recompute, and `thread_memberships` records every member at every version, append-only — so "what did this thread look like as of version 2" is always answerable, not just "what version number was it.

### `letter_chainages`, `letter_clauses`

Denormalized from `extracted_fields` purely so job 2 can be an indexed query. `letter_chainages.chainage_m` is an `int4range` with a GiST index; the filter is a range overlap. Each row keeps its `extracted_field_id`, so a chainage you filtered on is still one click from the page it came from.

### `review_events` and the two review statuses

`review_events` is the append-only audit of human action (`verified` / `rejected` / `corrected`, with old and new values), written by `record_field_verification()` / `record_field_correction()` — the *only* two entry points for review; a trigger blocks any other write to `extracted_fields`' content, so an audit event can't be bypassed.

Two distinct review statuses exist, at two different grains, and they are not the same axis wearing two names:

- `extracted_fields.review_status` (`unreviewed`/`verified`/`rejected`/`corrected`) — one field's human review state.
- `letters.review_status` (`unverified`/`needs_review`/`verified`) — the 3-state gutter DESIGN.md renders, **materialized from the field-level facts** by `refresh_letter_review_status()`, called at the end of both review functions:

```
IF any current field has validation = 'unresolved'
   OR any citation is 'unresolved_ambiguous'         → 'needs_review'
ELSE IF any current field has review_status='verified' → 'verified'
ELSE                                                   → 'unverified'
```

This function is what makes "materialized" a fact rather than a description — an earlier draft stated the rule in prose with no code actually computing it.

### `ingestion_jobs`

The Postgres-backed queue, claimed with `FOR UPDATE SKIP LOCKED`. It doubles as the ingestion audit trail, which this product needs to keep regardless — that is the argument for it over Redis and Celery.

### `letter_embeddings`

pgvector, in its own table, deliberately. It is not a column on `letters` because it is not authoritative evidence and the schema should say so. Nothing in the register's evidentiary path reads it.

Keyed by `(letter_id, model, pipeline_version_id)`, not `letter_id` alone, with an `is_current` flag marking the one embedding pgvector actually searches. This supports the embedding-model benchmark this document already says is pending (STACK.md needs a real Devanagari comparison) — a benchmark needs several candidate embeddings per letter to compare, and a bare `letter_id` primary key would have allowed only one to ever exist.

---

## What the schema deliberately does not have

- **No `updated_at` on `documents` or `extracted_fields`.** Facts are superseded by a new run, not edited in place.
- **No soft-delete on letters.** A letter that was ingested was ingested.
- **No confidence score presented as a number to users.** OCR confidence is stored for triage; DESIGN.md forbids surfacing a score, and the schema's `validation` enum is the user-facing signal.
- **No `latency_days` column.** Elapsed days is computed in the query from two dates. The LLM extracts; the database computes.

---

## Review response (2026-08-30)

An external review of revision 1 raised 23 points. This section records what changed and what didn't, and why. The schema, functions, and views described elsewhere in this document reflect revision 2, below, already applied.

**Verified by actually running it.** Revision 2 was applied to a live PostgreSQL 18 instance with pgvector 0.8.6 and exercised with a smoke-test script covering every trigger, function, and view changed here — not just read for syntax. Two real bugs surfaced only by running it, both in `record_field_correction`: the new row was being inserted before the old one stopped being current, which the partial unique index correctly rejected; and `superseded_by` was set to a row that didn't exist yet, which the foreign key correctly rejected. Both are fixed in `db/schema.sql` with the ordering explained inline. This is the reason the verification status below can say "verified," not "reviewed."

### Accepted

| # | Issue | Fix |
|---|---|---|
| 2 | `letters.serial`/`package_id`/`document_sha256`/`extraction_run_id` had no enforcement — a bare `UPDATE` could move them | `letters_prevent_identity_mutation()` trigger rejects any change to those four columns. Proven: the smoke test's attempt to move a serial and to change a `package_id` both fail with that trigger's exact message. |
| 2 (documents) | `documents` was "immutable" by convention only | `documents_immutable()` trigger rejects every `UPDATE` and `DELETE`. A storage migration is a DBA operation that disables the trigger explicitly, never an app-code path. |
| 3 | A direct `UPDATE extracted_fields SET value_text = ...` bypassed `review_events` entirely | Content columns (`value_text`, `value_verbatim`, `page_no`, `char_start`, `char_end`, `bbox`, `validation`) are now append-only, enforced by `extracted_fields_prevent_content_mutation()`. The only sanctioned paths are `record_field_verification()` and `record_field_correction()`, each of which writes the matching `review_events` row in the same transaction as the state change. |
| 4 | `validation` (machine locatability) and human review were one axis pretending to be two | Added `extracted_fields.review_status` (`unreviewed`/`verified`/`rejected`/`corrected`), a `field_review_status` enum distinct from `validation_kind`. `letters.review_status` — the 3-state gutter DESIGN.md renders — is unchanged; it's a coarser, letter-level derivation, not the same thing. |
| 8 | Extraction is package-contextual (party names, clause list, contract conditions are in the cached prompt prefix) but `extraction_runs` keyed only on `(document_sha256, pipeline_version)` — a document filed against two packages would collide | `extraction_runs.package_id` added. `extraction_runs_one_current` is now unique on `(document_sha256, package_id)`. Proven: the smoke test files one document against two packages and gets two independent current runs; a second current run for the *same* document+package is correctly rejected. |
| 10 | One citation row per `(citing_letter, cited_ref)` discarded a second mention's exact page location | Split into `citations` (the deduplicated relationship) and `citation_occurrences` (every page location a reference was actually mentioned, each pointing at its own `extracted_field`). Proven: two occurrences of the same reference in one fixture letter both survive with independent provenance. |
| 11 | `unresolved_ambiguous` had nowhere to keep the candidate set a reviewer needs to disambiguate | Added `citation_candidates` (candidate letter, match method, match score). |
| 12 | Hard `UNIQUE (package_id, letter_ref_normalized)` meant the database would *reject* a genuinely duplicate reference — the wrong failure mode for a tool whose job is to keep messy real evidence | Dropped the unique index; kept a plain lookup index. Real duplicates (re-scans, misassigned numbers, revision letters) are detected at S6 assembly and routed to `needs_review`, never rejected at ingestion. See PIPELINE.md § S6. |
| 13 | `CHECK (received >= dated)` would reject a letter with a misapplied stamp or a retrospective receipt — evidence, not a bug | Removed. S4 validation flags the anomaly and routes to `needs_review` instead. See PIPELINE.md § S4. |
| 14 | `packages.chainage_m` bound semantics undocumented | Documented: Postgres canonical `[inclusive, exclusive)`; `Km 12+400 – Km 14+250` displayed as inclusive-inclusive is stored via `int4range(12400, 14250, '[]')`. |
| 15 | Serial gaps under worker-crash conditions were unaddressed | Serial assignment and the letter insert are one transaction (§ S6); a crash rolls back both, so no gap is created by a crash. A gap *can* still occur if a letter is later found to be a duplicate — it is voided (`letters.voided_at`/`void_reason`), never renumbered and never deleted. `17, 18, 20` with `19` permanently voided, not `17, 18, 19`. |
| 16 | `register`'s `REPLY IN` picked "the most recently cited letter," which is an inference presented as fact — the exact thing DESIGN.md forbids | Redefined as the immediately preceding letter in the *same thread* by dated order — deterministic, requires no guess about which citation is "the" reply target. Proven: the fixture's two-letter thread returns the correct 94-day gap under the new definition. |
| 18 | `ingestion_jobs` had `locked_at`/`locked_by` but no lease expiry — a crashed worker's job stayed `running` forever | Added `lease_until`. Reaper query documented inline: `UPDATE ... SET status='queued' WHERE status='running' AND lease_until < now()`. Also added an idempotency index so the same `(package, document, pipeline, job_type)` can't be queued or running twice concurrently. |
| 20 | `storage_uri` was implicitly trusted | Not a schema change — a process rule, in PIPELINE.md: re-verify `SHA256(fetched bytes) == documents.sha256` before ever serving a document as evidence. The hash is the authority, not the URI. |
| 22 | No single query answers "what did the system have when this register was generated" | Added the `package_manifest` view. |

### Declined, with reasoning

| # | Issue | Why declined |
|---|---|---|
| 6 | "No explicit document → letter cardinality decision" | Already solved, not missing: `letters.document_sha256` + `page_from`/`page_to`, with one `extraction_run` per document producing many `letters` rows, **is** the one-document-many-letters model. PIPELINE.md § S6 states it directly ("A PDF routinely holds a covering letter plus enclosures"). A `document_units` table would duplicate what `page_from`/`page_to` already expresses. |
| 7 | `pipeline_versions` should have a dedicated column for every reproducibility input (rasterization DPI, deskew params, alignment version, threading version, ...) | Real concern, lighter fix: added `pipeline_versions.config jsonb`, an open bucket for exactly that envelope. A fixed column list forces a migration for every new knob; the review's own goal (nothing that can change the register is untracked) is served just as well by a documented convention for what belongs in `config`. |
| 15 (partial) | Full versioned thread-membership history with a query surface over past states | Added the lighter version: an append-only `thread_memberships` table (`thread_id, letter_id, thread_version, added_at`), which answers "what did the tribunal see when" without building a history query API nobody has asked for yet. |
| 21 | Four-way completeness taxonomy (cited-not-supplied vs. sequence-gap vs. extraction-failed vs. classified-non-correspondence) | Good future direction, not built. Sequence-gap detection needs a notion of "expected sequence" that doesn't cleanly exist across parties in EPC correspondence — worth solving once `missing_references` (cited-not-supplied, already built) is validated against real usage, not before. |

### Verification status (supersedes the PIPELINE.md table for the schema row)

`db/schema.sql` revision 2 was applied clean to PostgreSQL 18.6 with pgvector 0.8.6, `pg_trgm`, and `pgcrypto`, and exercised end to end: package-scoped extraction-run uniqueness, letter and document immutability triggers, the `extracted_fields` CHECK constraint in both failure directions, the content-immutability trigger, `record_field_correction()` (after fixing the two ordering bugs above), citation occurrences, and both the `register` and `package_manifest` views. Not yet exercised: a full pipeline run end to end (S0–S8) against this schema, and load at production row counts.

---

## Review response, round 2 (2026-08-30)

A second external review examined `db/schema.sql`, this file, `PIPELINE.md`, and `STACK.md` as one architecture. Several of its findings describe revision 2's schema *before* round 1's fixes were applied — those are noted as stale below, with the live-database proof that they're already resolved. The rest are new, and split the same way as round 1: accepted and applied (revision 3), or declined with reasoning.

**Verified the same way as round 1.** Every accepted schema change was applied to a live PostgreSQL 18.6 + pgvector 0.8.6 instance and exercised, not just read. New coverage: composite FK rejection (a letter's thread from a different package, a field claiming a letter from a different run, a page_no with no OCR text yet), the `letters` versioning supersede path end to end — insert not-current, flip old off, flip new on, confirmed via the `register` view returning **exactly one row** for a reprocessed letter (not two) and the full version history remaining queryable — and `refresh_letter_review_status()` actually materializing `verified` after a call to `record_field_verification()`.

### Stale — already fixed in round 1, this review describes the pre-fix schema

| # | Claim | Why it's stale |
|---|---|---|
| 5 | "Human corrections don't actually correct anything — `extracted_fields` remains unchanged" | This describes revision 1. Revision 2's `record_field_correction()` does exactly this correctly, and it's what the round-1 smoke test proved: after calling it, the current row's `value_text` **is** the corrected value, with `review_status='corrected'` and a `review_events` row carrying old/new. |
| 11 | "One citation row per pair loses a second mention's page location" | Revision 2 already split this into `citations` (relationship) + `citation_occurrences` (every mention, each with its own `extracted_field`). The round-1 smoke test inserted two occurrences of one citation and confirmed both survive. |
| 14 | "Thread versioning isn't real historical versioning — a single row is overwritten" | Revision 2 already added `thread_memberships`, append-only, `(thread_id, letter_id, thread_version)`. |
| 26 | "Queue needs a lease model and idempotency key" | Revision 2 already added `ingestion_jobs.lease_until` and the `ingestion_jobs_idempotent` partial unique index. |

### Accepted and applied (revision 3)

| # | Issue | Fix |
|---|---|---|
| 1 | **The real P0.** `letters` had no versioning at all — a re-extraction of an already-published document had nowhere to go except a brand-new, unrelated row, and the `register` view had no `is_current` filter, so reprocessing would have silently duplicated every register entry it touched | Applied the same append-only pattern already proven on `extraction_runs`/`extracted_fields` to `letters`: `is_current`/`superseded_by`, with `(package_id, serial)` as the immutable logical identity carried across versions — not the reviewer's separate `logical_letter`/`letter_version` table pair, since the pattern already in use achieves the same guarantee without a third parallel identity shape. Proven: the register shows one row, not two, for a reprocessed letter; the full history remains queryable. See PIPELINE.md § "Reprocessing an already-published document" for the matching algorithm. |
| 2 | "Same document set produces the same serials on every rebuild" overstated the guarantee — false under incremental, out-of-order arrival | Corrected the claim, not the mechanism: serial is immutable once assigned, permanently; batch-reproducibility is a narrower property that holds only for a full rebuild over a fixed, complete set. See PIPELINE.md § S6 and this file's Principle 4. |
| 3 | `thread_key` described as a stable, derivable identity — untrue under incremental arrival (an earlier-dated letter arriving late changes the "earliest member") | Corrected the claim: `threads.id` (uuid, never reassigned) was always the real identity everything keys on; `thread_key` is a recomputed display label. No schema change needed — the FK structure was already right, only the prose overstated `thread_key`'s permanence. |
| 4 | Two individually-valid foreign keys don't stop cross-object contamination (a field claiming a letter from a different run; a citation linking letters across packages; a letter's thread or party belonging to a different package) | Added composite FKs: `extracted_fields → letters(id, extraction_run_id)`, `extracted_fields → page_ocr(extraction_run_id, page_no)`, `citations/citation_candidates → letters(id, package_id)` (citing, cited, and candidate, each scoped to the citation's own package), `letters → threads(id, package_id)`, `letters → parties(id, package_id)` for both from/to party. All nullable-tolerant — an unthreaded or party-less letter, or an unresolved citation, is unaffected. Proven: a cross-package thread assignment and a cross-run field claim were both rejected in the smoke test. |
| 6 | `letters.review_status` was described as "materialized" with no function actually computing it | Added `refresh_letter_review_status()`, called from both review entry points. Proven: calling `record_field_verification()` on a field correctly flipped its letter's `review_status` to `verified`. |
| 7 | `PIPELINE.md`'s nine narrative stages and `job_type`'s eight enum values don't line up 1:1 (`map`/`publish` missing, `embed` unexplained) | Documented, not changed: S5 (map) folds into the `validate` job (no separate queue hop earns its keep for a cheap deterministic step); S8 (publish) is the transaction boundary at the end of `link`, not an independently queued unit; `embed` has no corresponding S-stage because it's off the critical evidentiary path, deferred to production. |
| 8 | `extraction_runs` assumed one LLM call per attempt; S3 can issue one call per page or a chunked call for a long document | Added `llm_requests` under `extraction_runs` for per-call token/status/error granularity; `extraction_runs`' totals become a denormalized sum. |
| 12 | `missing_references` grouped by verbatim `cited_ref_text`, fragmenting one logical missing reference across differently-rendered mentions; PIPELINE.md's worked example attributed a date to a letter that, being missing, has no known date | Regrouped the view by `cited_ref_normalized`; fixed the example to cite the *citing* letter's date, the only one the system actually has. |
| 15 | `letter_embeddings` primary-keyed on `letter_id` alone, blocking the Devanagari embedding-model benchmark this document already says is pending (a benchmark needs several candidate embeddings per letter) | Rekeyed to `(letter_id, model, pipeline_version_id)` with an `is_current` flag marking the one embedding pgvector actually searches. |
| 16 | `page_ocr.document_sha256` and `page_ocr.extraction_run_id` were two independently-valid FKs with nothing tying them to the *same* document | Added composite FK `page_ocr(extraction_run_id, document_sha256) → extraction_runs(id, document_sha256)`. Kept the column (useful for direct queries) rather than removing it, per the reviewer's own alternative. |
| 17 (partial) | Several invariants lived only in comments and could be real constraints | Added `CHECK (page_from <= page_to)` on `letters`; tightened the `extracted_fields` CHECK to require `char_end > char_start`; added `extraction_runs` CHECKs correlating `status`/`finished_at`/`is_current`. |
| 19 | "Deskew, despeckle, adaptive-threshold" was stated as a fixed pipeline rather than a policy to justify — aggressive thresholding can destroy stamps, signatures, faint annotations, thin Devanagari strokes | Softened to: benchmark raw / deskew-only / deskew+despeckle / deskew+threshold against 10–20 real documents before locking a default; whatever wins becomes a named `pipeline_versions.config` key, not silent behavior. |
| 20 (sub-point) | `effort` risked being a hard-coded runtime flag rather than a versioned, benchmarkable decision | Named as an explicit example key inside `pipeline_versions.config`. |
| 22 | "Byte-identical" used for both the SHA-256 document check and the OCR/text substring match — imprecise for the second, since Unicode code-point equality and byte equality aren't the same thing, and Devanagari's NFC/NFD ambiguity makes the gap concrete | Reserved "byte-identical" for the SHA-256 check; the OCR invariant is now "exact code-point match." |
| 27 | Confirm the S6–S8 transaction contains no OCR/LLM/upload calls | Was already true; made it explicit rather than implicit in PIPELINE.md's opening paragraph. |

### Declined, with reasoning

| # | Issue | Why declined |
|---|---|---|
| 1 (alternative) | Reviewer's proposed fix for the P0 was a separate `logical_letter` + `letter_versions` table pair | Functionally equivalent guarantees achieved by extending the `is_current`/`superseded_by` pattern already in use for `extraction_runs` and `extracted_fields` to `letters` — one fewer parallel identity system for the same result, and it's the pattern this schema has already committed to and proven twice. |
| 9 | `pipeline_versions` bundles raster/OCR/LLM/prompt/schema into one version id — changing only the prompt shouldn't force re-rasterization | Real efficiency observation, not a correctness bug. Splitting into independent `raster_version`/`ocr_version`/`extraction_version` is a legitimate future optimization; at 10-document demo scale the wasted re-derivation cost is negligible, and decomposing now is exactly the premature abstraction this codebase's own conventions warn against. Revisit if reprocessing cadence at production scale makes the coupling expensive. |
| 10 | REPLY IN should be typed (`reply_to`/`reference`/`follow_up`/`supersedes`), not just "previous letter in thread by date" | The thing this critique originally found — an *inferred* reply target presented as fact — was already fixed in round 1 by switching to a fully deterministic definition (previous letter in the same thread, by date; no guess about intent). Typing citation *intent* is additional LLM-extraction scope (the model would need to classify why a letter cites another), not a fix to a bug in the current, already-deterministic definition, and Job 4's actual requirement (elapsed days between successive letters) doesn't need it. |
| 13 | "Immutable" tables are enforced by trigger, not by revoking `UPDATE`/`DELETE` at the database-role level | Valid defense-in-depth for production (a role without trigger-bypass privilege is a stronger guarantee than a trigger alone). Premature before any database roles or deployment infrastructure exist — noted as a production-hardening item in STACK.md rather than built against a schema with a single application role. |
| 18 | Normalize `bbox` geometry into a `field_locations` table instead of JSONB | The reviewer's own review concedes this isn't a blocker for the 10-document demo. Accepted-but-deferred on that basis; JSONB stays until real usage shows the normalized shape is worth the join. |
| 17 (bbox numeric bounds) | Add a CHECK constraining `bbox`'s `x`/`y`/`w`/`h` to `[0,1]` | JSONB structural CHECKs are fragile — a key rename or a schema evolution silently stops validating rather than failing loudly. This validation belongs in the application layer (Pydantic, at the FastAPI boundary), where a broken shape is a typed error, not a silent CHECK that stopped matching. |

### Verification status (supersedes PIPELINE.md's table for the schema row)

`db/schema.sql` revision 3 was applied clean to the same PostgreSQL 18.6 + pgvector 0.8.6 instance used for round 1, then exercised with a second smoke-test script covering: `extraction_runs` status/finished_at/is_current CHECK constraints (both directions), `letters`' page-range CHECK, all four new composite FKs (thread-by-package, party-by-package, field-by-run, field-by-page), the full letter-versioning supersede sequence with the register view confirmed to show one current row and the complete history still queryable, `refresh_letter_review_status()`, and `letter_embeddings`' multi-model uniqueness (including its partial HNSW index, which pgvector 0.8.6 accepted without complaint). Not yet exercised: the S6 reprocessing-match heuristic (letter_ref / page-range matching) described in PIPELINE.md, which has no code yet, and `llm_requests` (created, not yet exercised with real multi-call data).
