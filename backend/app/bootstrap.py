"""First-boot database bootstrap for a hosted deployment.

A hosted Postgres starts empty, and there is no shell on the container to run
psql from. Applying the schema on startup makes the deployment self-contained:
the same image works against any empty database it is pointed at, and a database
reset needs no manual step to recover from.

Strictly guarded and idempotent -- it does nothing at all once the schema
exists, so this is a bootstrap, not a migration runner. Schema CHANGES to an
existing deployment are a separate, deliberate act; this only ever fills a
blank database.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg

# The pgvector block the schema itself labels "SECONDARY, non-authoritative":
# nothing in the evidentiary path reads it, and no code currently writes it.
_PGVECTOR_START = "-- ---------------------------------------------------------------- pgvector"
_PGVECTOR_END = "-- ---------------------------------------------------------------- views"


def _schema_path() -> Path:
    env = os.environ.get("SCHEMA_PATH")
    if env:
        return Path(env)
    # backend/app/bootstrap.py -> backend -> repo root -> db/schema.sql, and the
    # image's own layout (/app/db/schema.sql) as the fallback.
    here = Path(__file__).resolve().parent.parent
    for candidate in (here.parent / "db" / "schema.sql", here / "db" / "schema.sql"):
        if candidate.is_file():
            return candidate
    return here / "db" / "schema.sql"


def _strip_pgvector(sql: str) -> str:
    start = sql.find(_PGVECTOR_START)
    end = sql.find(_PGVECTOR_END)
    if start == -1 or end == -1 or end < start:
        return sql
    stripped = sql[:start] + sql[end:]
    return stripped.replace('CREATE EXTENSION IF NOT EXISTS "vector";', "")


# Additive, idempotent changes applied on every boot. Kept deliberately tiny and
# explicitly enumerated: this is not a general migration runner, and nothing here
# may drop, rename, or rewrite existing data. Anything beyond adding an optional
# column or a new table belongs in a considered migration, not a startup hook.
_ADDITIVE_MIGRATIONS = (
    """
    ALTER TABLE citations ADD COLUMN IF NOT EXISTS resolution_source text
        NOT NULL DEFAULT 'pipeline'
    """,
    """
    CREATE TABLE IF NOT EXISTS citation_aliases (
        id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        package_id           uuid NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
        cited_ref_normalized text NOT NULL,
        letter_id            uuid NOT NULL REFERENCES letters(id) ON DELETE CASCADE,
        created_at           timestamptz NOT NULL DEFAULT now(),
        UNIQUE (package_id, cited_ref_normalized)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS citation_aliases_lookup
        ON citation_aliases (package_id, cited_ref_normalized)
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
        id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        email         text NOT NULL UNIQUE,
        password_hash text NOT NULL,
        created_at    timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        token_hash text PRIMARY KEY,
        user_id    uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at timestamptz NOT NULL DEFAULT now(),
        expires_at timestamptz NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS sessions_user ON sessions (user_id)",
    "CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions (expires_at)",
    """
    ALTER TABLE packages ADD COLUMN IF NOT EXISTS owner_user_id uuid
        REFERENCES users(id) ON DELETE CASCADE
    """,
    "CREATE INDEX IF NOT EXISTS packages_owner ON packages (owner_user_id)",
    "ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS google_sub text",
    """
    CREATE UNIQUE INDEX IF NOT EXISTS users_google_sub
        ON users (google_sub) WHERE google_sub IS NOT NULL
    """,
)


def apply_additive_migrations(database_url: str) -> None:
    """Brings an already-provisioned database up to the current schema for the
    additive changes above. A fresh database gets these from schema.sql itself;
    this exists for databases created before they were added."""
    with psycopg.connect(database_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'citations' AND column_name = 'resolution_source'
                """
            )
            had_source_column = cur.fetchone() is not None

            for statement in _ADDITIVE_MIGRATIONS:
                cur.execute(statement)

            if not had_source_column:
                # Citations resolved BEFORE this column existed cannot be
                # attributed retroactively -- the database never recorded who
                # decided them. Treating them as human is the safe direction:
                # it protects real confirmations from being overwritten by a
                # later mechanical pass, at the cost of freezing a few links the
                # pipeline could have derived anyway. Losing a person's decision
                # is the worse error, so it is the one this avoids.
                cur.execute(
                    "UPDATE citations SET resolution_source = 'human' "
                    "WHERE resolution = 'resolved'"
                )
                print(
                    f"[bootstrap] marked {cur.rowcount} pre-existing resolved "
                    "citation(s) as human-confirmed (unattributable, protected)",
                    flush=True,
                )


def ensure_schema(database_url: str) -> None:
    """Applies the schema and seeds a package if the database is blank."""
    with psycopg.connect(database_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.packages')")
            if cur.fetchone()[0] is not None:
                # Provisioned already: apply only the additive changes and stop.
                # The schema itself is never re-applied over existing data.
                apply_additive_migrations(database_url)
                return

            path = _schema_path()
            if not path.is_file():
                print(f"[bootstrap] no schema at {path}; skipping", flush=True)
                return
            sql = path.read_text()

            # Ask whether pgvector exists rather than applying and reading the
            # failure out of an error string.
            cur.execute("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")
            if cur.fetchone() is None:
                print(
                    "[bootstrap] pgvector unavailable on this server; applying schema "
                    "without the letter_embeddings table. The register is unaffected -- "
                    "the schema marks that table secondary and non-authoritative, and "
                    "nothing in the evidentiary path reads it.",
                    flush=True,
                )
                sql = _strip_pgvector(sql)

            print(f"[bootstrap] empty database; applying {path}", flush=True)
            cur.execute(sql)
            print("[bootstrap] schema applied", flush=True)

    _seed_package(database_url)


def _seed_package(database_url: str) -> None:
    """Creates the single package uploads land in. Idempotent, and the id is
    never hard-coded -- /api/config hands whatever this created to the frontend."""
    with psycopg.connect(database_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO contractors (name, short_code)
                VALUES ('Uploaded Documents Contractor', 'UPLOAD')
                ON CONFLICT (short_code) DO UPDATE SET name = EXCLUDED.name
                RETURNING id
                """
            )
            (contractor_id,) = cur.fetchone()
            cur.execute(
                """
                INSERT INTO packages (contractor_id, name, contract_no, authority)
                VALUES (%s, 'Correspondence Register', 'PKG-1', 'NHAI')
                ON CONFLICT (contractor_id, contract_no) DO UPDATE SET name = EXCLUDED.name
                RETURNING id
                """,
                (contractor_id,),
            )
            (package_id,) = cur.fetchone()
            # Generic party pair so real letters can be attributed inward/outward.
            # ingest.py's party resolution is a best-effort substring match against
            # these names, not a real party directory; letters it cannot confidently
            # match are flagged unresolved rather than guessed.
            for role, name, short_code in (
                ("contractor", "Contractor", "CTR"),
                ("authority_engineer", "Authority Engineer", "AE"),
            ):
                cur.execute(
                    """
                    INSERT INTO parties (package_id, role, name, short_code)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (package_id, short_code) DO NOTHING
                    """,
                    (package_id, role, name, short_code),
                )
            print(f"[bootstrap] package ready: {package_id}", flush=True)
