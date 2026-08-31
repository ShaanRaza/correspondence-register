"""Creates one contractor + one package for real uploaded documents to ingest against.

Deliberately NOT named after the fictional "NH-44 PKG-3" fixture used elsewhere in
this project for UI screenshots -- that identity is made up, and conflating real
uploaded correspondence with it would misrepresent what the register is showing.
Run once; safe to re-run (idempotent on short_code / contract_no).

    python -m scripts.seed_upload_package
"""

from __future__ import annotations

import psycopg

from app.config import get_settings


def main() -> None:
    settings = get_settings()
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
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
                VALUES (%s, 'Real Upload Test Package', 'UPLOAD-TEST-1', 'NHAI')
                ON CONFLICT (contractor_id, contract_no) DO UPDATE SET name = EXCLUDED.name
                RETURNING id
                """,
                (contractor_id,),
            )
            (package_id,) = cur.fetchone()

            # Generic party pair so real letters can be attributed inward/outward.
            # Real correspondence rarely names parties exactly this way -- ingest.py's
            # party resolution is a best-effort substring match against these names,
            # not a real party directory. Letters it can't confidently match are
            # flagged unresolved rather than guessed.
            cur.execute(
                """
                INSERT INTO parties (package_id, role, name, short_code)
                VALUES (%s, 'contractor', 'Contractor', 'CTR')
                ON CONFLICT (package_id, short_code) DO NOTHING
                """,
                (package_id,),
            )
            cur.execute(
                """
                INSERT INTO parties (package_id, role, name, short_code)
                VALUES (%s, 'authority_engineer', 'Authority Engineer', 'AE')
                ON CONFLICT (package_id, short_code) DO NOTHING
                """,
                (package_id,),
            )

        print(f"package_id={package_id}")


if __name__ == "__main__":
    main()
