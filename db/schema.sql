-- Correspondence register — PostgreSQL schema
-- Requires PostgreSQL >= 15 (UNIQUE NULLS NOT DISTINCT) and the pgvector extension.
-- NOT yet executed against a live server — see PIPELINE.md § Verification status.
-- Postgres is the single source of truth. pgvector is secondary/non-authoritative.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "vector";

-- ---------------------------------------------------------------- enums

CREATE TYPE party_role      AS ENUM ('contractor','authority_engineer','project_director','other');
CREATE TYPE letter_direction AS ENUM ('inward','outward');
CREATE TYPE review_status   AS ENUM ('unverified','needs_review','verified');
CREATE TYPE validation_kind AS ENUM ('exact','normalized_exact','unresolved');
CREATE TYPE citation_state  AS ENUM ('resolved','unresolved_missing','unresolved_ambiguous');
CREATE TYPE run_status      AS ENUM ('running','succeeded','failed','superseded');
CREATE TYPE job_status      AS ENUM ('queued','running','succeeded','failed','cancelled');
CREATE TYPE job_type        AS ENUM ('intake','rasterize','ocr','extract','validate','assemble','link','embed');
CREATE TYPE review_action   AS ENUM ('verified','rejected','corrected');

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
    -- chainage in METRES. Km 12+400 -> 12400.
    chainage_m          int4range,
    ref_pattern         text,                         -- regex letter refs must match
    next_serial         bigint NOT NULL DEFAULT 1,    -- bumped under row lock at S6
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (contractor_id, contract_no)
);

CREATE TABLE parties (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    package_id  uuid NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
    role        party_role NOT NULL,
    name        text NOT NULL,
    short_code  text NOT NULL,                        -- 'CTR' | 'AE' | 'PD'
    UNIQUE (package_id, short_code)
);

-- ---------------------------------------------------------------- pipeline identity

CREATE TABLE pipeline_versions (
    id                    text PRIMARY KEY,           -- 'v3'
    ocr_provider          text NOT NULL,              -- 'google_document_ai' | 'tesseract' | 'fixture'
    ocr_provider_version  text NOT NULL,
    llm_model             text NOT NULL,              -- 'claude-opus-5'
    prompt_sha256         char(64) NOT NULL,          -- hash of the prompt template bytes
    schema_sha256         char(64) NOT NULL,          -- hash of the extraction JSON Schema bytes
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
-- no updated_at: nothing updates this table.

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

CREATE TABLE extraction_runs (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_sha256     char(64) NOT NULL REFERENCES documents(sha256),
    pipeline_version_id text     NOT NULL REFERENCES pipeline_versions(id),
    status              run_status NOT NULL DEFAULT 'running',
    is_current          boolean  NOT NULL DEFAULT false,
    ocr_response_uri    text,                          -- raw provider JSON in object store
    llm_request_id      text,                          -- Anthropic response id, for audit
    input_tokens        integer,
    output_tokens       integer,
    cache_read_tokens   integer,
    error               text,
    superseded_by       uuid REFERENCES extraction_runs(id),
    started_at          timestamptz NOT NULL DEFAULT now(),
    finished_at         timestamptz
);
-- at most one current run per document
CREATE UNIQUE INDEX extraction_runs_one_current
    ON extraction_runs (document_sha256) WHERE is_current;

-- ---------------------------------------------------------------- OCR (one row per page)

CREATE TABLE page_ocr (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    extraction_run_id  uuid     NOT NULL REFERENCES extraction_runs(id) ON DELETE CASCADE,
    document_sha256    char(64) NOT NULL REFERENCES documents(sha256),
    page_no            integer  NOT NULL,
    text               text     NOT NULL,   -- reading-order serialization; offsets index into this
    tokens             jsonb    NOT NULL,   -- [{t, cs, ce, x, y, w, h, conf}] bbox normalized 0..1
    provider           text     NOT NULL,
    provider_version   text     NOT NULL,
    UNIQUE (extraction_run_id, page_no)
);
-- INVARIANT (asserted in code, not enforceable here):
--   for every token:  text[t.cs : t.ce] == t.t
-- The whole provenance chain rests on this equality.

-- ---------------------------------------------------------------- threads

CREATE TABLE threads (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    package_id     uuid NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
    thread_key     text NOT NULL,          -- letter_ref of earliest member: derivable, not random
    subject        text,
    first_dated    date,
    last_dated     date,
    letter_count   integer NOT NULL DEFAULT 0,
    thread_version integer NOT NULL DEFAULT 1,
    computed_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (package_id, thread_key)
);

-- ---------------------------------------------------------------- letters (the register)

CREATE TABLE letters (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    package_id            uuid     NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
    document_sha256       char(64) NOT NULL REFERENCES documents(sha256),
    extraction_run_id     uuid     NOT NULL REFERENCES extraction_runs(id),
    serial                bigint   NOT NULL,           -- immutable register serial
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
    created_at            timestamptz NOT NULL DEFAULT now(),
    UNIQUE (package_id, serial),
    CHECK (received IS NULL OR dated IS NULL OR received >= dated)
);

CREATE INDEX letters_package_dated   ON letters (package_id, dated);
CREATE INDEX letters_thread          ON letters (thread_id, dated);
CREATE INDEX letters_review          ON letters (package_id, review_status);
CREATE INDEX letters_ref_trgm        ON letters USING gin (letter_ref_normalized gin_trgm_ops);
CREATE UNIQUE INDEX letters_ref_uniq ON letters (package_id, letter_ref_normalized)
    WHERE letter_ref_normalized IS NOT NULL;

-- ---------------------------------------------------------------- extracted fields + provenance

CREATE TABLE extracted_fields (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    extraction_run_id uuid NOT NULL REFERENCES extraction_runs(id) ON DELETE CASCADE,
    letter_id         uuid REFERENCES letters(id) ON DELETE CASCADE,
    field_key         text NOT NULL,      -- letter_ref | dated | received | subject
                                          -- | chainage | clause | cited_ref | from_party | to_party
    field_index       integer NOT NULL DEFAULT 0,
    value_text        text,               -- NORMALIZED value ('2024-06-14', '12400')
    value_verbatim    text,               -- EXACT substring the model returned
    page_no           integer,
    char_start        integer,
    char_end          integer,
    bbox              jsonb,              -- {union:{x,y,w,h}, rects:[{x,y,w,h}...]} normalized 0..1
    validation        validation_kind NOT NULL,
    ocr_confidence    real,
    -- NULLS NOT DISTINCT: letter_id is nullable for document-level fields;
    -- default UNIQUE semantics would let duplicates through. Requires PG >= 15.
    UNIQUE NULLS NOT DISTINCT (extraction_run_id, letter_id, field_key, field_index),
    -- an unresolved field must carry no geometry; a resolved one must carry all of it
    CHECK (
        (validation = 'unresolved' AND bbox IS NULL AND char_start IS NULL)
        OR
        (validation <> 'unresolved' AND bbox IS NOT NULL
         AND char_start IS NOT NULL AND char_end IS NOT NULL AND page_no IS NOT NULL)
    )
);

CREATE INDEX extracted_fields_letter ON extracted_fields (letter_id, field_key);
CREATE INDEX extracted_fields_unres  ON extracted_fields (extraction_run_id)
    WHERE validation = 'unresolved';

-- ---------------------------------------------------------------- citations (letter -> letter)

CREATE TABLE citations (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    citing_letter_id      uuid NOT NULL REFERENCES letters(id) ON DELETE CASCADE,
    cited_ref_text        text NOT NULL,          -- as printed in the citing letter
    cited_ref_normalized  text NOT NULL,
    cited_letter_id       uuid REFERENCES letters(id),
    extracted_field_id    uuid REFERENCES extracted_fields(id),  -- where on the page it was found
    resolution            citation_state NOT NULL,
    UNIQUE (citing_letter_id, cited_ref_normalized),
    CHECK ((resolution = 'resolved') = (cited_letter_id IS NOT NULL))
);

CREATE INDEX citations_cited  ON citations (cited_letter_id);
CREATE INDEX citations_citing ON citations (citing_letter_id);
-- completeness signal: references cited but not held
CREATE INDEX citations_missing ON citations (citing_letter_id)
    WHERE resolution = 'unresolved_missing';

-- ---------------------------------------------------------------- filter projections

CREATE TABLE letter_chainages (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    letter_id          uuid NOT NULL REFERENCES letters(id) ON DELETE CASCADE,
    extracted_field_id uuid NOT NULL REFERENCES extracted_fields(id) ON DELETE CASCADE,
    chainage_m         int4range NOT NULL,      -- metres
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
    payload             jsonb NOT NULL DEFAULT '{}',
    result              jsonb,
    error               text,
    created_at          timestamptz NOT NULL DEFAULT now(),
    started_at          timestamptz,
    finished_at         timestamptz
);
CREATE INDEX ingestion_jobs_claim ON ingestion_jobs (status, run_after)
    WHERE status = 'queued';

-- Claim pattern (no Redis, no Celery):
--   SELECT * FROM ingestion_jobs
--    WHERE status='queued' AND run_after <= now()
--    ORDER BY created_at
--    FOR UPDATE SKIP LOCKED LIMIT 1;

-- ---------------------------------------------------------------- pgvector (SECONDARY, non-authoritative)

CREATE TABLE letter_embeddings (
    letter_id           uuid PRIMARY KEY REFERENCES letters(id) ON DELETE CASCADE,
    embedding           vector(1024),
    model               text NOT NULL,
    pipeline_version_id text NOT NULL REFERENCES pipeline_versions(id)
);
CREATE INDEX letter_embeddings_hnsw ON letter_embeddings
    USING hnsw (embedding vector_cosine_ops);
-- Deliberately its own table, not a column on `letters`.
-- Nothing in the evidentiary path reads this. Results from it are labelled in the UI
-- and never enter an annexure bundle without a human selecting them.

-- ---------------------------------------------------------------- views

-- Register row. Latency is COMPUTED here, never stored, and always with both endpoints.
CREATE VIEW register AS
SELECT
    l.id, l.package_id, l.serial, l.review_status,
    l.dated, l.received, l.letter_ref, l.subject, l.direction,
    fp.short_code AS from_code, tp.short_code AS to_code,
    t.thread_key,
    reply.letter_ref AS replies_to_ref,
    reply.dated      AS replies_to_dated,
    (l.dated - reply.dated) AS reply_in_days
FROM letters l
LEFT JOIN parties fp ON fp.id = l.from_party_id
LEFT JOIN parties tp ON tp.id = l.to_party_id
LEFT JOIN threads t  ON t.id  = l.thread_id
LEFT JOIN LATERAL (
    SELECT c2.dated, c2.letter_ref
    FROM citations ct
    JOIN letters c2 ON c2.id = ct.cited_letter_id
    WHERE ct.citing_letter_id = l.id AND ct.resolution = 'resolved'
    ORDER BY c2.dated DESC
    LIMIT 1
) reply ON true;

-- Completeness: references cited by letters we hold, that we do not hold.
CREATE VIEW missing_references AS
SELECT l.package_id, c.cited_ref_text, count(*) AS cited_by_count,
       min(l.dated) AS first_cited_on
FROM citations c
JOIN letters l ON l.id = c.citing_letter_id
WHERE c.resolution = 'unresolved_missing'
GROUP BY l.package_id, c.cited_ref_text;
