-- Correspondence register — PostgreSQL schema
-- Requires PostgreSQL >= 15 (UNIQUE NULLS NOT DISTINCT) and the pgvector extension.
-- NOT yet executed against a live server — see PIPELINE.md § Verification status.
-- Postgres is the single source of truth. pgvector is secondary/non-authoritative.
--
-- Revision 3 (2026-08-30): incorporates a second external review. See DATA_MODEL.md
-- § Review response, round 2 for the accept/decline reasoning behind every change below.
-- Revision 2 (2026-08-30): incorporates the first external review.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "vector";

-- ---------------------------------------------------------------- enums

CREATE TYPE party_role         AS ENUM ('contractor','authority_engineer','project_director','other');
CREATE TYPE letter_direction   AS ENUM ('inward','outward');
CREATE TYPE review_status      AS ENUM ('unverified','needs_review','verified');
-- 'human_corrected': a reviewer supplied the value directly. Distinct from exact/
-- normalized_exact, which mean "found verbatim in OCR text" — a human correction
-- may or may not be locatable, so bbox is optional for this state only (see CHECK below).
CREATE TYPE validation_kind    AS ENUM ('exact','normalized_exact','unresolved','human_corrected');
-- Field-level human review, distinct from validation (machine locatability) and from
-- letters.review_status (the 3-state gutter DESIGN.md renders). Reviewers act at this
-- granularity; the letter-level status is derived from it (see letters_review_status()).
CREATE TYPE field_review_status AS ENUM ('unreviewed','verified','rejected','corrected');
CREATE TYPE citation_state     AS ENUM ('resolved','unresolved_missing','unresolved_ambiguous');
CREATE TYPE run_status         AS ENUM ('running','succeeded','failed','superseded');
CREATE TYPE job_status         AS ENUM ('queued','running','succeeded','failed','cancelled');
CREATE TYPE job_type           AS ENUM ('intake','rasterize','ocr','extract','validate','assemble','link','embed');
CREATE TYPE review_action      AS ENUM ('verified','rejected','corrected');

-- ---------------------------------------------------------------- org

CREATE TABLE contractors (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text NOT NULL,
    short_code  text NOT NULL UNIQUE,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE packages (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    contractor_id       uuid NOT NULL REFERENCES contractors(id),
    name                text NOT NULL,                -- 'NH-44 PKG-3'
    contract_no         text NOT NULL,
    authority           text NOT NULL DEFAULT 'NHAI',
    appointed_date      date,
    scheduled_completion date,
    -- chainage in METRES, Postgres canonical [inclusive, exclusive) form.
    -- Km 12+400 to Km 14+250 displayed as inclusive-inclusive is stored as
    -- int4range(12400, 14250, '[]') so both endpoints are actually included.
    chainage_m          int4range,
    ref_pattern         text,                         -- regex letter refs must match
    next_serial         bigint NOT NULL DEFAULT 1,    -- bumped under row lock at S6, same transaction as the insert
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (contractor_id, contract_no)
);

CREATE TABLE parties (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    package_id  uuid NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
    role        party_role NOT NULL,
    name        text NOT NULL,
    short_code  text NOT NULL,                        -- 'CTR' | 'AE' | 'PD'
    UNIQUE (package_id, short_code),
    -- composite-FK target: lets letters.from_party_id/to_party_id be checked against
    -- the SAME package as the letter, not merely against parties in general.
    UNIQUE (id, package_id)
);

-- ---------------------------------------------------------------- pipeline identity

CREATE TABLE pipeline_versions (
    id                    text PRIMARY KEY,           -- 'v3'
    ocr_provider          text NOT NULL,              -- 'google_document_ai' | 'tesseract' | 'fixture'
    ocr_provider_version  text NOT NULL,
    llm_model             text NOT NULL,              -- 'claude-opus-5'
    prompt_sha256         char(64) NOT NULL,          -- hash of the prompt template bytes
    schema_sha256         char(64) NOT NULL,          -- hash of the extraction JSON Schema bytes
    -- The rest of the reproducibility envelope that isn't its own column: rasterization
    -- DPI/deskew settings, alignment-algorithm version, threading-algorithm version,
    -- normalization-rules version, serial-assignment-algorithm version, and the LLM
    -- `effort` level (never hard-code effort=high in application code — it belongs
    -- here, versioned, so a medium-vs-high benchmark is a comparison between two
    -- pipeline_versions rows, not an undocumented runtime flag). An open bucket rather
    -- than a fixed column list, so a new knob doesn't force a migration — but every key
    -- that can change the register belongs in here, not in code alone.
    config                jsonb NOT NULL DEFAULT '{}',
    notes                 text,
    created_at            timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- documents (immutable)

CREATE TABLE documents (
    sha256            char(64) PRIMARY KEY,           -- identity IS the content hash
    byte_size         bigint NOT NULL,
    mime_type         text   NOT NULL,
    original_filename text   NOT NULL,
    page_count        integer,
    storage_uri       text   NOT NULL,                -- file://... or s3://...
    ingested_at       timestamptz NOT NULL DEFAULT now(),
    source_note       text
);
-- no updated_at: nothing updates this table. Enforced below, not just by convention.

CREATE FUNCTION documents_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'documents is immutable (sha256=%): originals are never mutated. '
        'A storage migration is a DBA operation run with this trigger disabled, never app code.', OLD.sha256;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER documents_no_update BEFORE UPDATE ON documents
    FOR EACH ROW EXECUTE FUNCTION documents_immutable();
CREATE TRIGGER documents_no_delete BEFORE DELETE ON documents
    FOR EACH ROW EXECUTE FUNCTION documents_immutable();

CREATE TABLE package_documents (
    package_id       uuid     NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
    document_sha256  char(64) NOT NULL REFERENCES documents(sha256),
    filed_at         timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (package_id, document_sha256)
);

CREATE TABLE document_pages (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_sha256     char(64) NOT NULL REFERENCES documents(sha256),
    pipeline_version_id text     NOT NULL REFERENCES pipeline_versions(id),
    page_no             integer  NOT NULL CHECK (page_no >= 1),
    width_px            integer  NOT NULL,
    height_px           integer  NOT NULL,
    dpi                 integer  NOT NULL DEFAULT 300,
    raster_uri          text     NOT NULL,
    UNIQUE (document_sha256, pipeline_version_id, page_no)
);

-- ---------------------------------------------------------------- extraction runs

-- Package-scoped: the LLM prompt includes package-specific context (party names,
-- clause list, contract conditions), so the same document filed against two packages
-- can legitimately produce two different extractions. Keying only on document+pipeline
-- would silently collide them. (Review point #8.)
CREATE TABLE extraction_runs (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_sha256     char(64) NOT NULL REFERENCES documents(sha256),
    package_id          uuid     NOT NULL REFERENCES packages(id),
    pipeline_version_id text     NOT NULL REFERENCES pipeline_versions(id),
    status              run_status NOT NULL DEFAULT 'running',
    is_current          boolean  NOT NULL DEFAULT false,
    -- input_tokens/output_tokens/cache_read_tokens are the RUNNING TOTAL across every
    -- llm_requests row for this run (below) — one extraction can span several model
    -- calls (e.g. one per page, or a chunked long document). Kept as a fast denormalized
    -- sum by the ingestion worker; `SELECT sum(...) FROM llm_requests WHERE
    -- extraction_run_id = ...` is the source of truth if they're ever suspected to drift.
    ocr_response_uri    text,                          -- raw provider JSON in object store
    llm_request_id      text,                          -- last/primary Anthropic response id, for quick lookup
    input_tokens        integer,
    output_tokens       integer,
    cache_read_tokens   integer,
    error               text,
    superseded_by       uuid REFERENCES extraction_runs(id),
    started_at          timestamptz NOT NULL DEFAULT now(),
    finished_at         timestamptz,
    -- composite-FK target: lets page_ocr be checked against the SAME document as its run.
    UNIQUE (id, document_sha256),
    CHECK ((status IN ('succeeded','failed','superseded')) = (finished_at IS NOT NULL)),
    CHECK (NOT is_current OR status = 'succeeded')
);
-- at most one current run per (document, package) — see comment above
CREATE UNIQUE INDEX extraction_runs_one_current
    ON extraction_runs (document_sha256, package_id) WHERE is_current;

-- Per-model-call granularity underneath one extraction_runs row (review round 2, #8).
-- A single "extraction attempt" can issue more than one Claude request — one per page,
-- or chunked for a long document — and extraction_runs' token columns alone can't
-- represent that without losing per-call cost attribution and debuggability.
CREATE TABLE llm_requests (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    extraction_run_id   uuid NOT NULL REFERENCES extraction_runs(id) ON DELETE CASCADE,
    page_from           integer,
    page_to             integer,
    model               text NOT NULL,          -- 'claude-opus-5'
    llm_request_id      text,                    -- Anthropic response id
    input_tokens        integer,
    output_tokens       integer,
    cache_read_tokens   integer,
    cache_write_tokens  integer,
    status              text NOT NULL DEFAULT 'succeeded',
    error               text,
    created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX llm_requests_run ON llm_requests (extraction_run_id);

-- ---------------------------------------------------------------- OCR (one row per page)

CREATE TABLE page_ocr (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    extraction_run_id  uuid     NOT NULL REFERENCES extraction_runs(id) ON DELETE CASCADE,
    document_sha256    char(64) NOT NULL REFERENCES documents(sha256),
    page_no            integer  NOT NULL,
    text               text     NOT NULL,   -- reading-order serialization; offsets index into this
    -- [{text, char_start, char_end, bbox:{x,y,width,height}, confidence}, ...]
    -- bbox normalized 0..1. Spelled out rather than abbreviated (t/cs/ce/x/y/w/h) —
    -- in an evidentiary system the on-disk representation should read without a legend.
    tokens             jsonb    NOT NULL,
    provider           text     NOT NULL,
    provider_version   text     NOT NULL,
    UNIQUE (extraction_run_id, page_no),
    -- Composite FK below closes a hole two independently-valid FKs left open (review
    -- round 2, #16): without it, nothing stopped a page_ocr row from naming a
    -- document_sha256 that DIFFERS from the document its own extraction_run was
    -- actually run against. document_sha256 stays as a column (useful for direct
    -- queries) but is now checked against the run's own document, not merely a valid document.
    FOREIGN KEY (extraction_run_id, document_sha256) REFERENCES extraction_runs (id, document_sha256)
);
-- INVARIANT, asserted by every OCR adapter before this row is committed, not just in
-- code review: for every token,  text[token.char_start:token.char_end] == token.text
-- as EXACT CODE-POINT equality — not "byte-identical" (that term is reserved for the
-- SHA-256 document identity below). Two strings can be code-point-identical yet differ
-- in bytes across UTF-8/UTF-16, and Unicode normalization (NFC vs NFD) changes how
-- Devanagari matras compose, so "byte-identical" invites the wrong mental model here.
-- The entire provenance chain — validation, highlighting, job 5's click-through —
-- rests on this equality. A page failing it is never persisted. See PIPELINE.md § S2.

-- ---------------------------------------------------------------- threads

-- `threads.id` (uuid, assigned once, never reassigned) is the actual stable identity —
-- everything downstream (letters.thread_id, thread_memberships) keys on it, never on
-- thread_key. `thread_key` (letter_ref of the CURRENT earliest member) is a DISPLAY
-- LABEL, not an identity: it is recomputed on every re-threading and can change if a
-- letter dated earlier than the current earliest member later arrives (an earlier
-- draft of this document called thread_key itself "derivable, stable identity," which
-- overstated it — review round 2, #3). A labelled thread whose label shifts is not a
-- bug; a thread whose row identity shifts would be, and it can't, because nothing
-- outside this table reads thread_key as a key.
CREATE TABLE threads (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    package_id     uuid NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
    thread_key     text NOT NULL,          -- current earliest member's letter_ref — a label, not an id
    subject        text,
    first_dated    date,
    last_dated     date,
    letter_count   integer NOT NULL DEFAULT 0,
    thread_version integer NOT NULL DEFAULT 1,
    computed_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (package_id, thread_key),
    -- composite-FK target: lets letters.thread_id be checked against the SAME package.
    UNIQUE (id, package_id)
);

-- Append-only membership audit. `letters.thread_id` is the fast pointer to CURRENT
-- membership; this table answers "what did the tribunal see when" — which letters
-- belonged to this thread at a past thread_version. Never updated, only inserted.
CREATE TABLE thread_memberships (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id      uuid NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    letter_id      uuid NOT NULL,   -- FK to letters(id) added below, once that table exists
    thread_version integer NOT NULL,
    added_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (thread_id, letter_id, thread_version)
);

-- ---------------------------------------------------------------- letters (the register)

-- Letters are versioned exactly like extracted_fields, for exactly the same reason
-- (review round 2, #1 — the biggest gap in revision 2): a letter is derived from ONE
-- extraction_run, but a document can legitimately be re-extracted (a pipeline/prompt
-- improvement, a fix for a garbled reference). Without versioning, re-extraction had
-- nowhere to put the new letters except as brand-new rows with no relationship to the
-- old ones — the register view (below) had no `is_current` filter at all, so
-- reprocessing a document would have silently DUPLICATED every register entry it
-- touched. The fix mirrors extraction_runs/extracted_fields rather than introducing a
-- third, differently-shaped identity system: `id` is a version row, `(package_id,
-- serial)` is the immutable LOGICAL identity carried forward across versions, and
-- is_current/superseded_by mark which version is live. See PIPELINE.md § "Reprocessing
-- an already-published document" for how a new run's candidate letters are matched
-- against existing logical letters (by serial) rather than always minting a new one.
CREATE TABLE letters (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    package_id            uuid     NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
    document_sha256       char(64) NOT NULL REFERENCES documents(sha256),
    extraction_run_id     uuid     NOT NULL REFERENCES extraction_runs(id),
    serial                bigint   NOT NULL,           -- immutable LOGICAL identity, carried across versions
    letter_ref            text,
    letter_ref_normalized text,
    dated                 date,                        -- date on the letterhead
    received              date,                        -- date of the inward stamp
    from_party_id         uuid REFERENCES parties(id),
    to_party_id           uuid REFERENCES parties(id),
    direction             letter_direction,
    subject               text,
    page_from             integer NOT NULL DEFAULT 1,
    page_to               integer NOT NULL DEFAULT 1,
    thread_id             uuid REFERENCES threads(id),
    review_status         review_status NOT NULL DEFAULT 'unverified',
    -- Append-only versioning (see comment above). A re-extraction that matches an
    -- existing logical letter inserts a NEW row carrying the SAME serial, is_current=true,
    -- and marks the old row is_current=false / superseded_by=new.id — same pattern,
    -- same ordering constraints, as record_field_correction() below.
    is_current            boolean NOT NULL DEFAULT true,
    superseded_by         uuid REFERENCES letters(id),
    -- A letter version is never deleted. If ingestion later determines it was a
    -- duplicate or misfiled, it is voided: the serial is permanently retired (never
    -- reused, never renumbered — 17, 18, 20 with 19 voided, not 17, 18, 19), and the
    -- row stays for audit.
    voided_at             timestamptz,
    void_reason           text,
    created_at            timestamptz NOT NULL DEFAULT now(),
    CHECK ((voided_at IS NULL) = (void_reason IS NULL)),
    CHECK (page_from <= page_to),
    -- composite-FK targets for extracted_fields, citations, thread membership below
    UNIQUE (id, extraction_run_id),
    UNIQUE (id, package_id)
    -- NOTE: the `received >= dated` CHECK from revision 1 is deliberately removed.
    -- An evidentiary register must never let the database REJECT messy real evidence
    -- (a misapplied stamp, a retrospective receipt). S4 validation flags the anomaly
    -- and routes the letter to needs_review instead. See PIPELINE.md § S4.
);

-- At most one current version per logical letter. NOT a plain UNIQUE(package_id,
-- serial) — a superseded version legitimately shares its serial with its replacement.
CREATE UNIQUE INDEX letters_one_current_serial ON letters (package_id, serial) WHERE is_current;
-- Full version history for one logical letter, oldest to newest via created_at.
CREATE INDEX letters_serial_history ON letters (package_id, serial);

ALTER TABLE thread_memberships
    ADD CONSTRAINT thread_memberships_letter_fk
    FOREIGN KEY (letter_id) REFERENCES letters(id) ON DELETE CASCADE;

ALTER TABLE letters
    -- composite FKs: a letter's thread/parties must belong to the SAME package as the
    -- letter itself. Two individually-valid FKs (thread_id -> threads.id, package_id ->
    -- packages.id) don't stop a letter from pointing at a thread that belongs to a
    -- DIFFERENT package — these do. Nullable columns are unchecked when null, so an
    -- unthreaded or party-less letter is unaffected. (Review round 2, #4.)
    ADD FOREIGN KEY (thread_id, package_id) REFERENCES threads (id, package_id),
    ADD FOREIGN KEY (from_party_id, package_id) REFERENCES parties (id, package_id),
    ADD FOREIGN KEY (to_party_id, package_id) REFERENCES parties (id, package_id);

-- `letters.dated`, `received`, `letter_ref`, `subject`, `from_party_id`, `to_party_id`
-- are a MATERIALIZED PROJECTION of the letter's current extracted_fields, refreshed by
-- refresh_letter_projection() below. A human correction never hand-edits these columns
-- directly — it corrects the underlying extracted_field (preserving the original machine
-- value, see extracted_fields below) and the projection is recomputed from that.

-- These four serve the register's hot path (read the live view), so they're scoped to
-- is_current — a superseded letter version doesn't need to be fast to find via the
-- register's own filters; it's reached via letters_serial_history or superseded_by instead.
CREATE INDEX letters_package_dated   ON letters (package_id, dated) WHERE is_current;
CREATE INDEX letters_thread          ON letters (thread_id, dated) WHERE is_current;
CREATE INDEX letters_review          ON letters (package_id, review_status) WHERE is_current;
CREATE INDEX letters_ref_trgm        ON letters USING gin (letter_ref_normalized gin_trgm_ops) WHERE is_current;
-- NOT unique. Revision 1 made (package_id, letter_ref_normalized) a hard UNIQUE index,
-- which means the database would REJECT a genuinely duplicate reference at ingestion —
-- exactly the reject-the-evidence failure mode this schema otherwise avoids. Real OCR
-- data produces duplicate/near-duplicate refs (re-scans, misassigned numbers, revision
-- letters). S6 assembly detects a collision and routes BOTH letters to needs_review
-- with a review_events note, rather than the database throwing at ingestion time.
CREATE INDEX letters_ref_lookup ON letters (package_id, letter_ref_normalized)
    WHERE letter_ref_normalized IS NOT NULL AND is_current;

-- Immutability: identity columns never change once a letter VERSION exists. Field-level
-- corrections happen on extracted_fields (which projects back onto dated/subject/etc
-- via refresh_letter_projection); a whole-letter re-extraction happens by inserting a
-- new version row (is_current/superseded_by, unrestricted by this trigger — it's the
-- same sanctioned transition as extracted_fields' supersede). serial, package_id,
-- document_sha256 and extraction_run_id can never change on an existing row either way.
CREATE FUNCTION letters_prevent_identity_mutation() RETURNS trigger AS $$
BEGIN
    IF NEW.serial IS DISTINCT FROM OLD.serial
       OR NEW.package_id IS DISTINCT FROM OLD.package_id
       OR NEW.document_sha256 IS DISTINCT FROM OLD.document_sha256
       OR NEW.extraction_run_id IS DISTINCT FROM OLD.extraction_run_id THEN
        RAISE EXCEPTION 'letters.% is immutable once assigned (letter id=%)',
            'serial/package_id/document_sha256/extraction_run_id', OLD.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER letters_identity_immutable BEFORE UPDATE ON letters
    FOR EACH ROW EXECUTE FUNCTION letters_prevent_identity_mutation();

-- ---------------------------------------------------------------- extracted fields + provenance

CREATE TABLE extracted_fields (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    extraction_run_id uuid NOT NULL REFERENCES extraction_runs(id) ON DELETE CASCADE,
    letter_id         uuid REFERENCES letters(id) ON DELETE CASCADE,
    field_key         text NOT NULL,      -- letter_ref | dated | received | subject
                                          -- | chainage | clause | cited_ref | from_party | to_party
    field_index       integer NOT NULL DEFAULT 0,
    value_text        text,               -- NORMALIZED value ('2024-06-14', '12400')
    value_verbatim    text,               -- EXACT substring the model returned (or the reviewer's text)
    page_no           integer,
    char_start        integer,
    char_end          integer,
    bbox              jsonb,              -- {union:{x,y,w,h}, rects:[{x,y,w,h}...]} normalized 0..1
    validation        validation_kind NOT NULL,
    ocr_confidence    real,
    -- Field-level human review, orthogonal to `validation` (see field_review_status comment above).
    review_status     field_review_status NOT NULL DEFAULT 'unreviewed',
    -- Append-only versioning, mirroring extraction_runs. A correction INSERTS a new row
    -- (is_current=true) and marks the old one is_current=false / superseded_by=new.id.
    -- The original machine extraction is never overwritten and never disappears —
    -- it stays queryable forever as history. Enforced by trigger below, not convention.
    is_current        boolean NOT NULL DEFAULT true,
    superseded_by     uuid REFERENCES extracted_fields(id),
    created_at        timestamptz NOT NULL DEFAULT now(),
    -- an unresolved field carries no geometry; human_corrected geometry is optional
    -- (a reviewer may or may not have selected a region); every other state requires
    -- full geometry or it is not a locatable fact. char_end > char_start whenever both
    -- are present, closing an ordering hole the original CHECK left open (round 2, #17).
    CHECK (
        (validation = 'unresolved' AND bbox IS NULL AND char_start IS NULL)
        OR (validation = 'human_corrected')
        OR (validation IN ('exact','normalized_exact') AND bbox IS NOT NULL
            AND char_start IS NOT NULL AND char_end IS NOT NULL AND page_no IS NOT NULL
            AND char_end > char_start)
    ),
    -- Composite FKs (round 2, #4): two individually-valid foreign keys don't stop a
    -- field from claiming a letter that belongs to a DIFFERENT extraction_run than the
    -- field's own, or naming a page_no that has no OCR text under this run at all.
    -- Nullable columns (letter_id, page_no) are unchecked when null, so document-level
    -- fields and unresolved fields are unaffected.
    FOREIGN KEY (letter_id, extraction_run_id) REFERENCES letters (id, extraction_run_id),
    FOREIGN KEY (extraction_run_id, page_no) REFERENCES page_ocr (extraction_run_id, page_no)
);

-- Uniqueness applies only among CURRENT rows — a superseded original and its correction
-- legitimately share (extraction_run_id, letter_id, field_key, field_index).
CREATE UNIQUE INDEX extracted_fields_one_current ON extracted_fields
    (extraction_run_id, letter_id, field_key, field_index) WHERE is_current;

CREATE INDEX extracted_fields_letter ON extracted_fields (letter_id, field_key) WHERE is_current;
CREATE INDEX extracted_fields_unres  ON extracted_fields (extraction_run_id)
    WHERE is_current AND validation = 'unresolved';
CREATE INDEX extracted_fields_history ON extracted_fields (superseded_by) WHERE superseded_by IS NOT NULL;

-- Content is append-only: a correction is a new row, never a rewrite of an existing one.
-- The only permitted UPDATE is the supersede transition itself (is_current -> false,
-- superseded_by -> new row) and review_status, both performed only by
-- record_field_correction() / record_field_verification() below, which also write
-- the matching review_events row in the same transaction. Direct UPDATE of content
-- columns is rejected here, closing the gap the review flagged (#3): today nothing
-- stopped `UPDATE extracted_fields SET value_text = ...` from bypassing the audit.
CREATE FUNCTION extracted_fields_prevent_content_mutation() RETURNS trigger AS $$
BEGIN
    IF NEW.value_text     IS DISTINCT FROM OLD.value_text
       OR NEW.value_verbatim IS DISTINCT FROM OLD.value_verbatim
       OR NEW.page_no        IS DISTINCT FROM OLD.page_no
       OR NEW.char_start     IS DISTINCT FROM OLD.char_start
       OR NEW.char_end       IS DISTINCT FROM OLD.char_end
       OR NEW.bbox           IS DISTINCT FROM OLD.bbox
       OR NEW.validation     IS DISTINCT FROM OLD.validation THEN
        RAISE EXCEPTION 'extracted_fields content is append-only (id=%). '
            'Use record_field_correction() to supersede it with a new row.', OLD.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER extracted_fields_content_immutable BEFORE UPDATE ON extracted_fields
    FOR EACH ROW EXECUTE FUNCTION extracted_fields_prevent_content_mutation();

-- ---------------------------------------------------------------- citations (letter -> letter)

-- Relationship table: one row per (citing letter, cited reference) PAIR, deduplicated.
-- Occurrence provenance (where on the page each mention was found) lives in
-- citation_occurrences below — a letter citing the same reference twice keeps both
-- locations. (Review point #10: occurrence vs. relationship were conflated in rev 1,
-- which meant a second mention's exact page location was silently discarded.)
CREATE TABLE citations (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    package_id            uuid NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
    citing_letter_id      uuid NOT NULL REFERENCES letters(id) ON DELETE CASCADE,
    cited_ref_text        text NOT NULL,          -- as printed, first occurrence
    cited_ref_normalized  text NOT NULL,
    cited_letter_id       uuid REFERENCES letters(id),
    resolution            citation_state NOT NULL,
    UNIQUE (citing_letter_id, cited_ref_normalized),
    CHECK ((resolution = 'resolved') = (cited_letter_id IS NOT NULL)),
    -- Composite FKs (round 2, #4): citing_letter_id and cited_letter_id must belong to
    -- THIS citation's own package — without them, two individually-valid FKs would let
    -- a citation link letters across two different packages. cited_letter_id is
    -- nullable (unresolved_missing/ambiguous), so it's unchecked in those cases.
    FOREIGN KEY (citing_letter_id, package_id) REFERENCES letters (id, package_id),
    FOREIGN KEY (cited_letter_id, package_id) REFERENCES letters (id, package_id)
);

CREATE INDEX citations_cited  ON citations (cited_letter_id);
CREATE INDEX citations_citing ON citations (citing_letter_id);
-- completeness signal: references cited but not held
CREATE INDEX citations_missing ON citations (citing_letter_id)
    WHERE resolution = 'unresolved_missing';

-- Every place on the page a citation's reference was actually mentioned. One
-- citation can have several occurrences; each occurrence points at the extracted_field
-- (and therefore the exact bbox) that located that one mention.
CREATE TABLE citation_occurrences (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    citation_id        uuid NOT NULL REFERENCES citations(id) ON DELETE CASCADE,
    extracted_field_id uuid NOT NULL REFERENCES extracted_fields(id) ON DELETE CASCADE,
    UNIQUE (citation_id, extracted_field_id)
);
CREATE INDEX citation_occurrences_citation ON citation_occurrences (citation_id);

-- When resolution = 'unresolved_ambiguous', the candidate set a reviewer needs to
-- disambiguate. Without this, "ambiguous" is a dead end for job 6 triage — the
-- database said ambiguous but discarded exactly the information a human needs to
-- resolve it. (Review point #11.)
CREATE TABLE citation_candidates (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    citation_id        uuid NOT NULL REFERENCES citations(id) ON DELETE CASCADE,
    package_id         uuid NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
    candidate_letter_id uuid NOT NULL REFERENCES letters(id),
    match_method       text NOT NULL,     -- 'exact_ref' | 'trgm_fuzzy' | 'date_proximity'
    match_score        real,
    UNIQUE (citation_id, candidate_letter_id),
    FOREIGN KEY (candidate_letter_id, package_id) REFERENCES letters (id, package_id)
);
CREATE INDEX citation_candidates_citation ON citation_candidates (citation_id);

-- ---------------------------------------------------------------- filter projections

CREATE TABLE letter_chainages (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    letter_id          uuid NOT NULL REFERENCES letters(id) ON DELETE CASCADE,
    extracted_field_id uuid NOT NULL REFERENCES extracted_fields(id) ON DELETE CASCADE,
    chainage_m         int4range NOT NULL,      -- metres, '[]' bound mode (see packages.chainage_m)
    UNIQUE (letter_id, extracted_field_id)
);
CREATE INDEX letter_chainages_gist ON letter_chainages USING gist (chainage_m);

CREATE TABLE letter_clauses (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    letter_id          uuid NOT NULL REFERENCES letters(id) ON DELETE CASCADE,
    extracted_field_id uuid NOT NULL REFERENCES extracted_fields(id) ON DELETE CASCADE,
    clause             text NOT NULL,           -- '10.3.2' as printed
    UNIQUE (letter_id, extracted_field_id)
);
CREATE INDEX letter_clauses_clause ON letter_clauses (clause);
-- NOTE: when a correction supersedes an extracted_field that a letter_chainages or
-- letter_clauses row points to, the derivation step re-projects from the new current
-- field and repoints these rows at it. They always reference a CURRENT field.

-- ---------------------------------------------------------------- review audit

CREATE TABLE review_events (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    letter_id          uuid NOT NULL REFERENCES letters(id) ON DELETE CASCADE,
    extracted_field_id uuid REFERENCES extracted_fields(id),
    actor              text NOT NULL,
    action             review_action NOT NULL,
    old_value          text,
    new_value          text,
    note               text,
    created_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX review_events_letter ON review_events (letter_id, created_at);

-- The only two sanctioned entry points for human review. Both write review_events
-- in the same transaction as the state change they record, closing the gap where a
-- direct UPDATE could silently change a value with no audit trail (review point #3).
-- extracted_fields_content_immutable (above) blocks every other path.

CREATE FUNCTION record_field_verification(
    p_field_id uuid, p_actor text, p_action review_action, p_note text DEFAULT NULL
) RETURNS void AS $$
DECLARE
    v_letter_id uuid;
BEGIN
    IF p_action NOT IN ('verified','rejected') THEN
        RAISE EXCEPTION 'record_field_verification handles verified/rejected only; use record_field_correction for corrected';
    END IF;
    SELECT letter_id INTO v_letter_id FROM extracted_fields WHERE id = p_field_id AND is_current;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'no current extracted_field %', p_field_id;
    END IF;
    UPDATE extracted_fields SET review_status = p_action::text::field_review_status
        WHERE id = p_field_id;
    INSERT INTO review_events (letter_id, extracted_field_id, actor, action, note)
        VALUES (v_letter_id, p_field_id, p_actor, p_action, p_note);
    PERFORM refresh_letter_review_status(v_letter_id);
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION record_field_correction(
    p_field_id uuid, p_actor text, p_new_value text, p_new_verbatim text, p_note text DEFAULT NULL
) RETURNS uuid AS $$
DECLARE
    v_old extracted_fields;
    v_new_id uuid := gen_random_uuid();
BEGIN
    SELECT * INTO v_old FROM extracted_fields WHERE id = p_field_id AND is_current FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'no current extracted_field %', p_field_id;
    END IF;

    -- Three ordered steps, forced by two constraints that can't both be satisfied by a
    -- naive two-step insert-then-update (both discovered by running this against a live
    -- Postgres 18, not by inspection): (1) extracted_fields_one_current is a plain,
    -- non-deferrable partial unique index — Postgres has no deferrable partial-unique
    -- constraint, since ADD CONSTRAINT doesn't accept a WHERE clause — so the old row
    -- must stop being current before the new one can become current; (2) superseded_by
    -- has a plain FK, so it can't point at a row that doesn't exist yet. Insert not-yet-
    -- current first (satisfies neither constraint's ordering problem), then flip old off,
    -- then flip new on — each step satisfies both constraints at the point it runs.
    INSERT INTO extracted_fields (
        id, extraction_run_id, letter_id, field_key, field_index,
        value_text, value_verbatim, validation, review_status, is_current
    ) VALUES (
        v_new_id, v_old.extraction_run_id, v_old.letter_id, v_old.field_key, v_old.field_index,
        p_new_value, p_new_verbatim, 'human_corrected', 'corrected', false
    );

    UPDATE extracted_fields SET is_current = false, superseded_by = v_new_id WHERE id = p_field_id;
    UPDATE extracted_fields SET is_current = true WHERE id = v_new_id;

    INSERT INTO review_events (letter_id, extracted_field_id, actor, action, old_value, new_value, note)
        VALUES (v_old.letter_id, v_new_id, p_actor, 'corrected', v_old.value_text, p_new_value, p_note);

    PERFORM refresh_letter_projection(v_old.letter_id);
    PERFORM refresh_letter_review_status(v_old.letter_id);
    RETURN v_new_id;
END;
$$ LANGUAGE plpgsql;

-- Recomputes letters.dated/received/letter_ref/subject/from_party_id/to_party_id from
-- that letter's current extracted_fields. Called after any correction. Left as a stub
-- here — the field_key -> column mapping belongs with the extraction schema in code,
-- not duplicated in SQL.
CREATE FUNCTION refresh_letter_projection(p_letter_id uuid) RETURNS void AS $$
BEGIN
    -- application-implemented: SELECT current fields for p_letter_id, map field_key
    -- to the corresponding letters column, UPDATE letters (permitted: this touches
    -- only projection columns, never serial/package_id/document_sha256/extraction_run_id,
    -- so letters_identity_immutable does not fire).
    NULL;
END;
$$ LANGUAGE plpgsql;

-- Materializes letters.review_status — the 3-state gutter DESIGN.md renders — from the
-- finer-grained state that actually changes: field-level validation and review_status,
-- plus citation ambiguity. This was previously described in prose (DATA_MODEL.md) as
-- "materialized" with no function actually doing it — a real gap, not just missing
-- glue (round 2, #6). Called from both review entry points, so the gutter is never
-- stale relative to the field-level facts that determine it.
CREATE FUNCTION refresh_letter_review_status(p_letter_id uuid) RETURNS void AS $$
DECLARE
    v_status review_status;
BEGIN
    IF EXISTS (
        SELECT 1 FROM extracted_fields
        WHERE letter_id = p_letter_id AND is_current AND validation = 'unresolved'
    ) OR EXISTS (
        SELECT 1 FROM citations
        WHERE citing_letter_id = p_letter_id AND resolution = 'unresolved_ambiguous'
    ) THEN
        v_status := 'needs_review';
    ELSIF EXISTS (
        SELECT 1 FROM extracted_fields
        WHERE letter_id = p_letter_id AND is_current AND review_status = 'verified'
    ) THEN
        v_status := 'verified';
    ELSE
        v_status := 'unverified';
    END IF;
    UPDATE letters SET review_status = v_status WHERE id = p_letter_id;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------- ingestion queue / audit trail

CREATE TABLE ingestion_jobs (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    package_id          uuid REFERENCES packages(id) ON DELETE CASCADE,
    document_sha256     char(64) REFERENCES documents(sha256),
    pipeline_version_id text REFERENCES pipeline_versions(id),
    job_type            job_type   NOT NULL,
    status              job_status NOT NULL DEFAULT 'queued',
    attempts            integer NOT NULL DEFAULT 0,
    max_attempts        integer NOT NULL DEFAULT 3,
    run_after           timestamptz NOT NULL DEFAULT now(),
    locked_at           timestamptz,
    locked_by           text,
    -- Lease expiry for crash recovery. A worker that dies mid-job leaves its row
    -- 'running' forever without this (review point #18). The reaper query below
    -- returns it to the queue once the lease lapses.
    lease_until         timestamptz,
    payload             jsonb NOT NULL DEFAULT '{}',
    result              jsonb,
    error               text,
    created_at          timestamptz NOT NULL DEFAULT now(),
    started_at          timestamptz,
    finished_at         timestamptz
);
CREATE INDEX ingestion_jobs_claim ON ingestion_jobs (status, run_after)
    WHERE status = 'queued';

-- Idempotency: the same (package, document, pipeline, stage) must never be queued or
-- running twice concurrently — a retry after a transient failure should not race a
-- still-in-flight attempt.
CREATE UNIQUE INDEX ingestion_jobs_idempotent ON ingestion_jobs
    (package_id, document_sha256, pipeline_version_id, job_type)
    WHERE status IN ('queued','running');

-- Claim pattern (no Redis, no Celery):
--   SELECT * FROM ingestion_jobs
--    WHERE status='queued' AND run_after <= now()
--    ORDER BY created_at
--    FOR UPDATE SKIP LOCKED LIMIT 1;
--   -- on claim: SET status='running', locked_at=now(), locked_by=<worker>,
--   --           lease_until=now() + interval '10 minutes'
--
-- Reaper (run on a schedule, or opportunistically before claiming):
--   UPDATE ingestion_jobs SET status='queued', locked_by=NULL, lease_until=NULL
--    WHERE status='running' AND lease_until < now();

-- ---------------------------------------------------------------- pgvector (SECONDARY, non-authoritative)

-- PRIMARY KEY (letter_id) alone (revision 2) meant only one embedding could ever exist
-- per letter — which blocks the Devanagari embedding-model benchmark this schema
-- already says is pending (STACK.md), since a benchmark needs several candidate
-- embeddings per letter to compare. is_current marks the one live for retrieval; the
-- rest are benchmark history. (Round 2, #15.)
CREATE TABLE letter_embeddings (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    letter_id           uuid NOT NULL REFERENCES letters(id) ON DELETE CASCADE,
    embedding           vector(1024),   -- PLACEHOLDER dimension pending the Devanagari benchmark, see STACK.md
    model               text NOT NULL,
    pipeline_version_id text NOT NULL REFERENCES pipeline_versions(id),
    is_current          boolean NOT NULL DEFAULT true,
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (letter_id, model, pipeline_version_id)
);
-- exactly one live embedding per letter for pgvector to search
CREATE UNIQUE INDEX letter_embeddings_one_current ON letter_embeddings (letter_id) WHERE is_current;
CREATE INDEX letter_embeddings_hnsw ON letter_embeddings
    USING hnsw (embedding vector_cosine_ops) WHERE is_current;
-- Deliberately its own table, not a column on `letters`.
-- Nothing in the evidentiary path reads this. Results from it are labelled in the UI
-- and never enter an annexure bundle without a human selecting them.

-- ---------------------------------------------------------------- views

-- Register row. Latency is COMPUTED here, never stored, and always with both endpoints.
--
-- `WHERE l.is_current` is not optional decoration — its absence in revision 2 was the
-- sharpest gap either review found (round 2, #1): with no filter, reprocessing a
-- document would have shown BOTH the old and new letter rows, duplicating the register.
-- Every prior letters.* query in this file already had a filter or a join that made
-- the gap invisible; this view was the one place it would have surfaced as a visible bug.
--
-- REPLY IN is the immediately preceding letter in the SAME THREAD by dated order —
-- not "the most recently cited letter" (revision 1's definition). A letter can cite
-- several earlier letters; picking the latest-dated one is a guess presented as fact,
-- which DESIGN.md explicitly forbids ("no inferred value at the same weight as an
-- extracted one"). Thread-order precedence is deterministic and requires no inference:
-- it is defined entirely by dated ordering within thread_id. (Round 1, #16.)
CREATE VIEW register AS
SELECT
    l.id, l.package_id, l.serial, l.review_status,
    l.dated, l.received, l.letter_ref, l.subject, l.direction,
    fp.short_code AS from_code, tp.short_code AS to_code,
    t.thread_key,
    prev.letter_ref AS replies_to_ref,
    prev.dated      AS replies_to_dated,
    (l.dated - prev.dated) AS reply_in_days
FROM letters l
LEFT JOIN parties fp ON fp.id = l.from_party_id
LEFT JOIN parties tp ON tp.id = l.to_party_id
LEFT JOIN threads t  ON t.id  = l.thread_id
LEFT JOIN LATERAL (
    SELECT p.letter_ref, p.dated
    FROM letters p
    WHERE p.thread_id = l.thread_id AND p.dated < l.dated AND p.is_current AND p.voided_at IS NULL
    ORDER BY p.dated DESC
    LIMIT 1
) prev ON l.thread_id IS NOT NULL
WHERE l.is_current AND l.voided_at IS NULL;

-- Completeness: references cited by letters we hold, that we do not hold. Grouped by
-- cited_ref_normalized, not cited_ref_text (round 2, #12) — the same logical reference
-- can appear as "AE/PKG3/2024/091" in one letter and "AE / PKG3 / 2024 / 091" in
-- another; grouping on the verbatim text would fragment one missing letter into two
-- rows. `first_cited_text` is a representative rendering for display, not identity.
CREATE VIEW missing_references AS
SELECT l.package_id, c.cited_ref_normalized,
       min(c.cited_ref_text) AS first_cited_text,
       count(*) AS cited_by_count,
       min(l.dated) AS first_cited_on
FROM citations c
JOIN letters l ON l.id = c.citing_letter_id AND l.is_current
WHERE c.resolution = 'unresolved_missing'
GROUP BY l.package_id, c.cited_ref_normalized;

-- "What did the system have when this register was generated." Answers the audit
-- question directly instead of requiring a four-table join every time. (Review point #22.)
CREATE VIEW package_manifest AS
SELECT
    pd.package_id, d.sha256, d.original_filename, d.byte_size, d.ingested_at,
    er.id AS extraction_run_id, er.status AS extraction_status, er.is_current,
    pv.id AS pipeline_version_id, pv.ocr_provider, pv.llm_model
FROM package_documents pd
JOIN documents d ON d.sha256 = pd.document_sha256
LEFT JOIN extraction_runs er ON er.document_sha256 = d.sha256
    AND er.package_id = pd.package_id AND er.is_current
LEFT JOIN pipeline_versions pv ON pv.id = er.pipeline_version_id;
