"""FastAPI app. One real endpoint for this phase: upload a PDF, run the real
pipeline (S0-S8) against it synchronously, return what got written to the register.

Synchronous-per-request is a deliberate scope decision, not an oversight: this
endpoint exists to let one person upload ~10 real documents and see genuine
pipeline output, one at a time. It is not the design for concurrent multi-user
ingestion -- `pipeline/jobs.py`'s lease-based queue exists for that and is unused
here on purpose.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from google import genai
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from .config import get_settings
from .pipeline.ingest import IngestResult, ingest_pdf
from .pipeline.link import recompute_threads
from .pipeline.storage import LocalBlobStore

app = FastAPI(title="Correspondence Register API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().allowed_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def require_app_password(request: Request, call_next):
    """Shared-password gate for when this is deployed somewhere reachable by
    more than just you -- there is no real user model here, this only stops a
    random link-holder from touching an exposed instance. A no-op locally
    (APP_PASSWORD unset means the gate is off, which is the default).

    `@app.middleware("http")` registers AFTER CORSMiddleware but runs BEFORE it
    on the way in (Starlette wraps middleware in reverse-registration order) --
    this must let OPTIONS preflight through untouched, or a browser's preflight
    gets a 401 with no Access-Control-Allow-Origin header at all and the real
    request never gets sent. Preflight carries no custom headers by design, so
    there's nothing to check here anyway; CORSMiddleware's own allow_origins
    still gates who the browser lets the real request return a response to."""
    if request.method == "OPTIONS":
        return await call_next(request)
    settings = get_settings()
    path = request.url.path
    # Only the API is gated. When this process also serves the built frontend
    # (FRONTEND_DIST, used for single-origin tunnelling), the HTML and asset
    # requests are ordinary browser navigations that cannot carry a custom
    # header -- gating them would make the page unloadable and leave nowhere to
    # type the password. The bundle is not the secret; the register data is,
    # and every route that returns it still requires the header.
    if not settings.app_password or not path.startswith("/api/") or path == "/api/health":
        return await call_next(request)
    if request.headers.get("x-app-password") != settings.app_password:
        return Response(status_code=401, content='{"detail":"Missing or incorrect app password."}',
                         media_type="application/json")
    return await call_next(request)

DEFAULT_CONTRACT_CONDITIONS = (
    "No package-specific contract conditions have been loaded for this package yet. "
    "Extract only what is literally stated in the correspondence."
)
DEFAULT_PACKAGE_CONTEXT = (
    "This document belongs to a package whose contractors, parties, and reference-"
    "number conventions have not yet been configured. Do not assume any specific "
    "party names beyond what appears in the letter itself."
)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


def _ingest_blocking(
    *,
    settings,
    package_id: str,
    pdf_bytes: bytes,
    original_filename: str,
    gemini_api_key: str,
) -> IngestResult:
    """Every blocking step of an ingest, isolated so it can be handed to a
    threadpool. HTTPExceptions raised here propagate out of run_in_threadpool
    normally and are handled by FastAPI exactly as if raised inline."""
    store = LocalBlobStore(settings.storage_root)
    client = genai.Client(api_key=gemini_api_key)

    with psycopg.connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM packages WHERE id = %s", (package_id,))
            if cur.fetchone() is None:
                raise HTTPException(status_code=404, detail=f"Unknown package_id {package_id!r}")

        try:
            return ingest_pdf(
                conn,
                store,
                client,
                package_id=package_id,
                pdf_bytes=pdf_bytes,
                original_filename=original_filename,
                contract_conditions=DEFAULT_CONTRACT_CONDITIONS,
                package_context=DEFAULT_PACKAGE_CONTEXT,
            )
        except AssertionError as e:
            # The OCR offset invariant failing is a real, actionable pipeline bug --
            # surface it plainly rather than a generic 500.
            raise HTTPException(status_code=500, detail=f"OCR invariant violation: {e}") from e


@app.post("/api/packages/{package_id}/documents")
async def upload_document(
    package_id: str,
    file: UploadFile = File(...),
    gemini_api_key: str | None = Form(None),
) -> dict:
    if file.content_type not in ("application/pdf", "application/octet-stream") and not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    settings = get_settings()
    # A key typed into the browser (per-request, from Form) takes priority over
    # the server's own .env -- this lets a second person use their own Gemini
    # quota against a shared instance without ever touching the server's
    # environment. It's used for this one request only and never persisted:
    # not written to disk, not put in the database, not logged.
    effective_key = gemini_api_key or settings.gemini_api_key
    if not effective_key:
        raise HTTPException(
            status_code=500,
            detail=(
                "No Gemini API key available. Enter one in the Upload panel, or set "
                "GEMINI_API_KEY on the backend via `export GEMINI_API_KEY=...` or backend/.env."
            ),
        )

    pdf_bytes = await file.read()

    # Off the event loop, not on it. ingest_pdf() is entirely blocking work --
    # poppler and tesseract subprocesses, a synchronous Gemini HTTP call, and
    # psycopg queries -- and running it directly inside `async def` froze the
    # single uvicorn worker (Render sets WEB_CONCURRENCY=1 on a 0.1-CPU
    # instance) for the whole ingest. Nothing else could be served meanwhile,
    # including the platform's own health checks, so the service was killed and
    # restarted mid-upload: every request 500'd or hung and the site appeared
    # down. Confirmed from logs -- an upload POST logged no response at all,
    # followed by a service restart. A threadpool keeps the loop free.
    result: IngestResult = await run_in_threadpool(
        _ingest_blocking,
        settings=settings,
        package_id=package_id,
        pdf_bytes=pdf_bytes,
        original_filename=file.filename,
        gemini_api_key=effective_key,
    )

    if result.error:
        raise HTTPException(status_code=502, detail=f"Extraction failed: {result.error}")

    return {
        "document_sha256": result.document_sha256,
        "is_duplicate": result.is_duplicate,
        "extraction_run_id": result.extraction_run_id,
        "letter_ids": result.letter_ids,
        "letters_found": len(result.letter_ids),
        "matched_existing": result.matched_existing or [],
    }


@app.get("/api/packages/{package_id}")
def get_package(package_id: str) -> dict:
    settings = get_settings()
    with psycopg.connect(settings.database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT name, contract_no FROM packages WHERE id = %s",
            (package_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Unknown package_id {package_id!r}")
        name, contract_no = row

        cur.execute(
            "SELECT count(DISTINCT document_sha256) FROM package_documents WHERE package_id = %s",
            (package_id,),
        )
        (documents_ingested,) = cur.fetchone()

    return {
        "name": name,
        "contractNo": contract_no,
        "documentsIngested": documents_ingested,
        "documentsTotal": documents_ingested,
    }


@app.get("/api/packages/{package_id}/letters")
def list_letters(package_id: str) -> list[dict]:
    settings = get_settings()
    with psycopg.connect(settings.database_url) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT l.id, l.serial, l.letter_ref, l.dated, l.received,
                   fp.short_code, tp.short_code, l.direction,
                   l.subject, l.review_status, t.thread_key,
                   l.document_sha256, l.page_from, l.page_to,
                   d.original_filename
            FROM letters l
            LEFT JOIN parties fp ON fp.id = l.from_party_id
            LEFT JOIN parties tp ON tp.id = l.to_party_id
            LEFT JOIN threads t ON t.id = l.thread_id
            LEFT JOIN documents d ON d.sha256 = l.document_sha256
            WHERE l.package_id = %s AND l.is_current
            ORDER BY l.serial
            """,
            (package_id,),
        )
        rows = cur.fetchall()
        letter_ids = [str(r[0]) for r in rows]

        chainage_by_letter: dict[str, str] = {}
        clause_by_letter: dict[str, str] = {}
        missing_citation_by_letter: dict[str, str] = {}
        if letter_ids:
            cur.execute(
                """
                SELECT letter_id, field_key, value_text
                FROM extracted_fields
                WHERE letter_id = ANY(%s) AND field_key IN ('chainage', 'clause') AND field_index = 0
                """,
                (letter_ids,),
            )
            for letter_id, field_key, value_text in cur.fetchall():
                target = chainage_by_letter if field_key == "chainage" else clause_by_letter
                target[str(letter_id)] = value_text

            cur.execute(
                """
                SELECT DISTINCT ON (citing_letter_id) citing_letter_id, cited_ref_text
                FROM citations
                WHERE citing_letter_id = ANY(%s) AND resolution = 'unresolved_missing'
                ORDER BY citing_letter_id, id
                """,
                (letter_ids,),
            )
            for citing_letter_id, cited_ref_text in cur.fetchall():
                missing_citation_by_letter[str(citing_letter_id)] = cited_ref_text

    results = []
    for (letter_id, serial, letter_ref, dated, received, from_code, to_code,
         direction, subject, review_status, thread_key,
         document_sha256, page_from, page_to, original_filename) in rows:
        lid = str(letter_id)
        unresolved = "parties" if direction is None else None
        results.append(
            {
                "id": lid,
                "serial": serial,
                "letterRef": letter_ref or "—",
                "dated": dated.isoformat() if dated else None,
                "received": received.isoformat() if received else None,
                "from": from_code or "UNK",
                "to": to_code or "UNK",
                "direction": direction or "inward",
                "subject": subject or "",
                "chainage": chainage_by_letter.get(lid),
                "clause": clause_by_letter.get(lid),
                "threadKey": thread_key or letter_ref or lid,
                "reviewStatus": review_status,
                "repliesToRef": None,
                "repliesToDated": None,
                "unresolvedField": unresolved,
                "missingCitation": missing_citation_by_letter.get(lid),
                "documentSha256": document_sha256,
                "pageFrom": page_from,
                "pageTo": page_to,
                "originalFilename": original_filename,
            }
        )
    return results


@app.get("/api/letters/{letter_id}/fields")
def get_letter_fields(letter_id: str) -> list[dict]:
    """Per-field provenance for one letter: the exact page, bounding box, and
    validation outcome behind every extracted value -- the citation data
    PIPELINE.md's click-to-locate feature is built on. `bbox` is null when
    validation is 'unresolved' (nothing to point at) and always normalized 0..1
    against the page image, not pixels, so it works at any raster resolution."""
    settings = get_settings()
    with psycopg.connect(settings.database_url) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT ef.field_key, ef.field_index, ef.value_text, ef.value_verbatim,
                   ef.page_no, ef.bbox, ef.validation
            FROM extracted_fields ef
            JOIN letters l ON l.extraction_run_id = ef.extraction_run_id
            WHERE l.id = %s AND ef.letter_id = %s
            ORDER BY ef.field_key, ef.field_index
            """,
            (letter_id, letter_id),
        )
        rows = cur.fetchall()
    return [
        {
            "fieldKey": field_key,
            "fieldIndex": field_index,
            "valueText": value_text,
            "valueVerbatim": value_verbatim,
            "pageNo": page_no,
            "bbox": bbox,
            "validation": validation,
        }
        for field_key, field_index, value_text, value_verbatim, page_no, bbox, validation in rows
    ]


@app.get("/api/documents/{sha256}/pages/{page_no}/raster")
def get_page_raster(sha256: str, page_no: int):
    """Serves the actual rasterized scan for one page -- the real source image
    the register's extracted values were read from, not a placeholder."""
    settings = get_settings()
    with psycopg.connect(settings.database_url) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT raster_uri FROM document_pages
            WHERE document_sha256 = %s AND page_no = %s
            ORDER BY pipeline_version_id DESC LIMIT 1
            """,
            (sha256, page_no),
        )
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"No raster for {sha256!r} page {page_no}")

    path = Path(row[0].removeprefix("file://"))
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Raster file missing on disk")
    return Response(content=path.read_bytes(), media_type="image/png")


@app.get("/api/packages/{package_id}/citations/ambiguous")
def list_ambiguous_citations(package_id: str) -> list[dict]:
    """Citations that fuzzy-matched a candidate but were never auto-resolved --
    see link.py's reasoning: the exact digits that would tell two real letters
    apart are the part most vulnerable to OCR noise, so a plausible-looking
    match is not the same thing as a confirmed one. This is the review queue a
    human works through to actually confirm (or leave alone) each one."""
    settings = get_settings()
    with psycopg.connect(settings.database_url) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.id, c.citing_letter_id, cl.letter_ref, cl.serial, c.cited_ref_text
            FROM citations c
            JOIN letters cl ON cl.id = c.citing_letter_id
            WHERE c.package_id = %s AND c.resolution = 'unresolved_ambiguous'
            ORDER BY cl.serial
            """,
            (package_id,),
        )
        rows = cur.fetchall()
        citation_ids = [str(r[0]) for r in rows]

        candidates_by_citation: dict[str, list[dict]] = {}
        if citation_ids:
            cur.execute(
                """
                SELECT cc.citation_id, l.id, l.letter_ref, l.serial, cc.match_method, cc.match_score
                FROM citation_candidates cc
                JOIN letters l ON l.id = cc.candidate_letter_id
                WHERE cc.citation_id = ANY(%s)
                ORDER BY cc.match_score DESC NULLS LAST
                """,
                (citation_ids,),
            )
            for citation_id, cand_id, cand_ref, cand_serial, method, score in cur.fetchall():
                candidates_by_citation.setdefault(str(citation_id), []).append(
                    {
                        "candidateLetterId": str(cand_id),
                        "candidateLetterRef": cand_ref,
                        "candidateSerial": cand_serial,
                        "matchMethod": method,
                        "matchScore": score,
                    }
                )

    return [
        {
            "citationId": str(cid),
            "citingLetterId": str(citing_letter_id),
            "citingLetterRef": citing_ref,
            "citingSerial": citing_serial,
            "citedRefText": cited_ref_text,
            "candidates": candidates_by_citation.get(str(cid), []),
        }
        for cid, citing_letter_id, citing_ref, citing_serial, cited_ref_text in rows
    ]


class ConfirmCitationBody(BaseModel):
    candidate_letter_id: str


@app.post("/api/citations/{citation_id}/confirm")
def confirm_citation(citation_id: str, body: ConfirmCitationBody) -> dict:
    """Links a citation to the human-confirmed candidate and re-threads the
    package. This is the ONLY path that turns a fuzzy match into a resolved
    one -- the pipeline itself never does this automatically."""
    settings = get_settings()
    with psycopg.connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT package_id, citing_letter_id FROM citations WHERE id = %s AND resolution = 'unresolved_ambiguous'",
                (citation_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="No ambiguous citation with that id")
            package_id, citing_letter_id = row

            cur.execute(
                """
                SELECT 1 FROM citation_candidates
                WHERE citation_id = %s AND candidate_letter_id = %s
                """,
                (citation_id, body.candidate_letter_id),
            )
            if cur.fetchone() is None:
                raise HTTPException(
                    status_code=400,
                    detail="That letter was not one of this citation's recorded candidates.",
                )

            cur.execute(
                "UPDATE citations SET resolution = 'resolved', cited_letter_id = %s WHERE id = %s",
                (body.candidate_letter_id, citation_id),
            )

        recompute_threads(conn, str(package_id))
        conn.commit()

    return {"status": "confirmed"}


# Optionally serve the built frontend from this same process. Set FRONTEND_DIST
# to a Vite build output directory to put the UI and the API on ONE origin,
# which is what makes a single tunnel (cloudflared/ngrok) work: no CORS to
# configure, and no rebuilding the frontend every time the tunnel hands out a
# new random hostname, because the bundle calls the API with relative URLs.
#
# Mounted last on purpose: a Mount at "/" matches anything not already claimed
# by a route, so every /api/... route above still wins. html=True serves
# index.html for unknown paths, which the hash-based router needs.
_frontend_dist = os.environ.get("FRONTEND_DIST")
if _frontend_dist and Path(_frontend_dist).is_dir():
    app.mount("/", StaticFiles(directory=_frontend_dist, html=True), name="frontend")
