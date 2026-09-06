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


def ensure_schema(database_url: str) -> None:
    """Applies the schema and seeds a package if the database is blank."""
    with psycopg.connect(database_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.packages')")
            if cur.fetchone()[0] is not None:
                return  # Already provisioned -- never touch an existing database.

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
