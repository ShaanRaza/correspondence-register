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
import secrets
import urllib.parse
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import psycopg
from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from .auth import (
    SESSION_COOKIE, assert_owns_package, create_session, delete_session,
    assert_owns_citation, assert_owns_document, assert_owns_letter,
    hash_password, normalize_email, package_for_user, require_user,
    user_for_token, verify_password,
)
from .bootstrap import ensure_schema
from .pipeline.extract import make_client, resolve_base_url, resolve_model
from .config import get_settings
from .pipeline.ingest import IngestResult, ingest_pdf
from .pipeline.link import recompute_threads, reresolve_package
from .pipeline.storage import LocalBlobStore

@asynccontextmanager
async def lifespan(_: FastAPI):
    """Provision a blank database on first boot (see bootstrap.ensure_schema).

    Deliberately non-fatal: if this fails the app still starts, so the failure is
    readable in the platform's logs and on the health endpoint instead of a
    container that crash-loops before printing why.
    """
    try:
        ensure_schema(get_settings().database_url)
    except Exception as e:  # noqa: BLE001 -- surfaced, not swallowed
        print(f"[bootstrap] FAILED: {type(e).__name__}: {e}", flush=True)
    yield


app = FastAPI(title="Correspondence Register API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().allowed_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)


# Routes reachable without a session. Everything else requires one.
#   health/config - needed before sign-in (config carries no register content)
#   auth/*        - the way in
_PUBLIC_API_PATHS = {
    "/api/health", "/api/config",
    "/api/auth/signup", "/api/auth/login", "/api/auth/logout", "/api/auth/me",
    # The OAuth round-trip happens BEFORE a session exists -- gating these would
    # make Google sign-in impossible for anyone not already signed in.
    "/api/auth/google/start", "/api/auth/google/callback",
}


@app.middleware("http")
async def require_session(request: Request, call_next):
    """Blanket "must be signed in" for the API.

    This is a coarse gate only. It proves a request HAS a session; it says
    nothing about which register that session may read, so every route
    returning register content additionally checks ownership. Registers are
    private per account, and an id in a URL must never be enough to reach one.

    Non-/api/ paths are unauthenticated on purpose: this process also serves the
    built frontend, and those are ordinary browser navigations for the HTML and
    JS. The bundle is not the secret -- the register is, and it stays behind
    this gate.
    """
    if request.method == "OPTIONS":
        return await call_next(request)
    path = request.url.path
    if not path.startswith("/api/") or path in _PUBLIC_API_PATHS:
        return await call_next(request)

    settings = get_settings()
    with psycopg.connect(settings.database_url) as conn:
        user = user_for_token(conn, request.cookies.get(SESSION_COOKIE))
    if user is None:
        return Response(status_code=401, content='{"detail":"Not signed in."}',
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


@app.get("/api/config")
def config(request: Request) -> dict:
    """The signed-in account's own register id, or null when signed out.

    Registers are private per account, so there is no longer a single global
    package to hand out -- this returns only the caller's own. It stays reachable
    without a session because the frontend loads before anyone has signed in;
    signed out it discloses nothing.
    """
    settings = get_settings()
    with psycopg.connect(settings.database_url) as conn:
        user = user_for_token(conn, request.cookies.get(SESSION_COOKIE))
        google = bool(settings.google_client_id and settings.google_client_secret)
        if user is None:
            return {"packageId": None, "email": None, "signedIn": False, "googleEnabled": google}
        user_id, email = user
        return {"packageId": package_for_user(conn, user_id), "email": email,
                "signedIn": True, "googleEnabled": google}


class SignupBody(BaseModel):
    email: str
    password: str
    inviteCode: str | None = None


class LoginBody(BaseModel):
    email: str
    password: str


def _set_session_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE, raw_token,
        httponly=True,      # unreadable from JavaScript, so XSS cannot steal it
        secure=True,        # HTTPS only; Railway terminates TLS
        samesite="lax",     # blocks cross-site use while keeping normal navigation
        max_age=60 * 60 * 24 * 30,
        path="/",
    )


def _create_register_for(conn: psycopg.Connection, user_id: str, email: str) -> str:
    """Gives a new account its own empty register.

    An existing UNOWNED package is adopted rather than left orphaned -- that is
    the register uploaded before accounts existed, and it would otherwise become
    unreachable. Only the first account can inherit it; everyone after gets a
    fresh one.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM packages WHERE owner_user_id IS NULL ORDER BY created_at LIMIT 1"
        )
        orphan = cur.fetchone()
        if orphan is not None:
            cur.execute("UPDATE packages SET owner_user_id = %s WHERE id = %s", (user_id, orphan[0]))
            return str(orphan[0])

        # Its own contractor row, so the (contractor_id, contract_no) uniqueness
        # never collides between two accounts.
        cur.execute(
            "INSERT INTO contractors (name, short_code) VALUES (%s, %s) RETURNING id",
            (f"Register owner {email}", f"U{user_id.replace('-', '')[:10]}"),
        )
        (contractor_id,) = cur.fetchone()
        cur.execute(
            """
            INSERT INTO packages (contractor_id, name, contract_no, authority, owner_user_id)
            VALUES (%s, 'Correspondence Register', 'PKG-1', 'NHAI', %s) RETURNING id
            """,
            (contractor_id, user_id),
        )
        (package_id,) = cur.fetchone()
        for role, name, code in (
            ("contractor", "Contractor", "CTR"),
            ("authority_engineer", "Authority Engineer", "AE"),
        ):
            cur.execute(
                "INSERT INTO parties (package_id, role, name, short_code) VALUES (%s,%s,%s,%s) "
                "ON CONFLICT DO NOTHING",
                (package_id, role, name, code),
            )
    return str(package_id)


@app.post("/api/auth/signup")
def signup(body: SignupBody, response: Response) -> dict:
    settings = get_settings()
    email = normalize_email(body.email)
    if "@" not in email or len(email) < 3:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Use a password of at least 8 characters.")
    # APP_PASSWORD doubles as the invite code: without it anyone who finds the
    # URL could create an account on this instance. Unset means open signup,
    # which is the local-development default.
    if settings.app_password and body.inviteCode != settings.app_password:
        raise HTTPException(status_code=403, detail="That invite code is not correct.")

    with psycopg.connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM users WHERE email = %s", (email,))
            if cur.fetchone() is not None:
                raise HTTPException(status_code=409, detail="An account already exists for that email.")
            cur.execute(
                "INSERT INTO users (email, password_hash) VALUES (%s, %s) RETURNING id",
                (email, hash_password(body.password)),
            )
            (user_id,) = cur.fetchone()
        package_id = _create_register_for(conn, str(user_id), email)
        raw_token, _ = create_session(conn, str(user_id))
        conn.commit()

    _set_session_cookie(response, raw_token)
    return {"email": email, "packageId": package_id}


@app.post("/api/auth/login")
def login(body: LoginBody, response: Response) -> dict:
    settings = get_settings()
    email = normalize_email(body.email)
    with psycopg.connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, password_hash FROM users WHERE email = %s", (email,))
            row = cur.fetchone()
        # One message for both "no such account" and "wrong password", so this
        # cannot be used to discover which emails have accounts.
        if row is None or not verify_password(row[1], body.password):
            raise HTTPException(status_code=401, detail="Email or password is incorrect.")
        user_id = str(row[0])
        raw_token, _ = create_session(conn, user_id)
        package_id = package_for_user(conn, user_id)
        if package_id is None:
            package_id = _create_register_for(conn, user_id, email)
        conn.commit()

    _set_session_cookie(response, raw_token)
    return {"email": email, "packageId": package_id}


# --- Google sign-in (OAuth 2.0 authorization code flow) ----------------------
#
# Optional: with GOOGLE_CLIENT_ID/SECRET unset the option simply does not appear
# and email + password continues to work.
#
# The code is exchanged server-side and the profile read from Google's userinfo
# endpoint over TLS, so the browser never handles a token and there is no JWT
# signature to verify in our own code -- one less thing to get subtly wrong.
_GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO = "https://www.googleapis.com/oauth2/v3/userinfo"
_OAUTH_STATE_COOKIE = "cr_oauth_state"


def _public_base(request: Request) -> str:
    settings = get_settings()
    if settings.public_base_url:
        return settings.public_base_url
    # Behind Railway's proxy the app itself speaks http; the forwarded header is
    # what says the public URL is https. Getting this wrong makes the redirect
    # URI mismatch what Google has registered.
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    return f"{proto}://{host}"


def _redirect_uri(request: Request) -> str:
    return f"{_public_base(request)}/api/auth/google/callback"


@app.get("/api/auth/google/start")
def google_start(request: Request, invite: str = "") -> Response:
    settings = get_settings()
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(status_code=404, detail="Google sign-in is not configured.")

    # The state is echoed back by Google and compared against a cookie: that is
    # what stops a third party from replaying a callback into someone's session.
    # The invite code rides along so a NEW account can still be gated by it --
    # there is no form to carry it on once the browser leaves for Google.
    nonce = secrets.token_urlsafe(24)
    state = f"{nonce}:{urllib.parse.quote(invite, safe='')}"
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": _redirect_uri(request),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    }
    response = RedirectResponse(f"{_GOOGLE_AUTH}?{urllib.parse.urlencode(params)}", status_code=302)
    response.set_cookie(_OAUTH_STATE_COOKIE, nonce, httponly=True, secure=True,
                        samesite="lax", max_age=600, path="/")
    return response


@app.get("/api/auth/google/callback")
def google_callback(request: Request, code: str = "", state: str = "") -> Response:
    settings = get_settings()
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(status_code=404, detail="Google sign-in is not configured.")

    expected = request.cookies.get(_OAUTH_STATE_COOKIE)
    nonce, _, invite_quoted = state.partition(":")
    if not expected or not secrets.compare_digest(expected, nonce):
        raise HTTPException(status_code=400, detail="Sign-in could not be verified. Try again.")
    invite = urllib.parse.unquote(invite_quoted)

    with httpx.Client(timeout=20) as client:
        token_res = client.post(_GOOGLE_TOKEN, data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": _redirect_uri(request),
            "grant_type": "authorization_code",
        })
        if token_res.status_code != 200:
            raise HTTPException(status_code=400, detail="Google rejected the sign-in.")
        access_token = token_res.json().get("access_token")
        info_res = client.get(_GOOGLE_USERINFO, headers={"Authorization": f"Bearer {access_token}"})
        if info_res.status_code != 200:
            raise HTTPException(status_code=400, detail="Could not read the Google profile.")
        info = info_res.json()

    email = normalize_email(info.get("email") or "")
    google_sub = info.get("sub")
    # An unverified address must not be trusted: it would let someone claim an
    # account belonging to an email they do not control.
    if not email or not info.get("email_verified") or not google_sub:
        raise HTTPException(status_code=400, detail="That Google account has no verified email.")

    with psycopg.connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM users WHERE google_sub = %s OR email = %s", (google_sub, email)
            )
            row = cur.fetchone()
            if row is None:
                # Signing in is open: a new account gets an empty private
                # register and can do nothing that costs anything. The gate that
                # matters sits on UPLOAD, which is what spends model credits.
                # An invite in the link still unlocks uploading immediately, so
                # an invited person never sees a prompt at all.
                unlocked = bool(settings.app_password) and invite == settings.app_password
                cur.execute(
                    "INSERT INTO users (email, google_sub, upload_unlocked) "
                    "VALUES (%s, %s, %s) RETURNING id",
                    (email, google_sub, unlocked or not settings.app_password),
                )
                (user_id,) = cur.fetchone()
                _create_register_for(conn, str(user_id), email)
            else:
                (user_id,) = row
                # Links Google to an account first created with a password, so
                # the same person does not end up with two registers.
                cur.execute(
                    "UPDATE users SET google_sub = %s WHERE id = %s AND google_sub IS NULL",
                    (google_sub, user_id),
                )
        raw_token, _ = create_session(conn, str(user_id))
        conn.commit()

    # location.replace, not a 302. A redirect leaves THIS callback URL in the
    # browser's history, so pressing Back from the register re-entered it -- and
    # its one-time state cookie is already spent, so the user landed on an error
    # after successfully signing in. Replacing the entry means Back skips over
    # the whole sign-in round trip entirely.
    html = (
        "<!doctype html><meta charset=utf-8><title>Signing you in…</title>"
        "<script>location.replace('/')</script>"
        "<noscript><meta http-equiv=refresh content='0;url=/'></noscript>"
    )
    response = Response(content=html, media_type="text/html")
    _set_session_cookie(response, raw_token)
    response.delete_cookie(_OAUTH_STATE_COOKIE, path="/")
    return response


@app.post("/api/auth/logout")
def logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        settings = get_settings()
        with psycopg.connect(settings.database_url) as conn:
            delete_session(conn, token)
            conn.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"signedIn": False}


def _upload_unlocked(conn: psycopg.Connection, user_id: str) -> bool:
    """Whether this account may upload. Uploading spends the server's model
    credits, so it is the one action worth gating; reading your own (empty)
    register is not."""
    settings = get_settings()
    if not settings.app_password:
        return True  # no code configured: nothing to unlock
    with conn.cursor() as cur:
        cur.execute("SELECT upload_unlocked FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
    return bool(row and row[0])


class UnlockBody(BaseModel):
    code: str


@app.post("/api/auth/unlock")
def unlock_uploads(body: UnlockBody, request: Request) -> dict:
    """Exchanges the access code for a permanent unlock on THIS account.

    Recorded against the account, not the browser, so it is entered once and
    never again -- on any device, after any sign-out.
    """
    settings = get_settings()
    with psycopg.connect(settings.database_url) as conn:
        user_id, _ = require_user(request, conn)
        if not settings.app_password:
            return {"uploadUnlocked": True}
        if body.code.strip() != settings.app_password:
            raise HTTPException(status_code=403, detail="That code is not correct.")
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET upload_unlocked = true WHERE id = %s", (user_id,))
        conn.commit()
    return {"uploadUnlocked": True}


@app.get("/api/auth/me")
def me(request: Request) -> dict:
    settings = get_settings()
    # The sign-in screen reads this to decide whether to offer Google at all,
    # so it has to report availability even when signed out.
    google = bool(settings.google_client_id and settings.google_client_secret)
    with psycopg.connect(settings.database_url) as conn:
        user = user_for_token(conn, request.cookies.get(SESSION_COOKIE))
        if user is None:
            return {"signedIn": False, "email": None, "packageId": None,
                    "googleEnabled": google, "uploadUnlocked": False}
        user_id, email = user
        return {"signedIn": True, "email": email,
                "packageId": package_for_user(conn, user_id), "googleEnabled": google,
                "uploadUnlocked": _upload_unlocked(conn, user_id)}


def _ingest_blocking(
    *,
    settings,
    package_id: str,
    pdf_bytes: bytes,
    original_filename: str,
    openai_api_key: str,
) -> IngestResult:
    """Every blocking step of an ingest, isolated so it can be handed to a
    threadpool. HTTPExceptions raised here propagate out of run_in_threadpool
    normally and are handled by FastAPI exactly as if raised inline."""
    store = LocalBlobStore(settings.storage_root)
    # Works against OpenAI or any OpenAI-compatible gateway (OpenRouter):
    # see extract.resolve_base_url / resolve_model.
    client = make_client(openai_api_key)
    llm_model = resolve_model(resolve_base_url(openai_api_key))

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
                llm_model=llm_model,
            )
        except AssertionError as e:
            # The OCR offset invariant failing is a real, actionable pipeline bug --
            # surface it plainly rather than a generic 500.
            raise HTTPException(status_code=500, detail=f"OCR invariant violation: {e}") from e


@app.post("/api/packages/{package_id}/documents")
async def upload_document(
    package_id: str,
    request: Request,
    file: UploadFile = File(...),
    openai_api_key: str | None = Form(None),
) -> dict:
    if file.content_type not in ("application/pdf", "application/octet-stream") and not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    settings = get_settings()
    with psycopg.connect(settings.database_url) as conn:
        user_id, _ = require_user(request, conn)
        assert_owns_package(conn, user_id, package_id)
        if not _upload_unlocked(conn, user_id):
            # Signing in is open, but uploading spends the server's model
            # credits, so this is where the access code is required. The
            # "upload_locked:" prefix is a stable marker the UI keys on to show
            # the code prompt rather than a generic error.
            raise HTTPException(
                status_code=403,
                detail="upload_locked: enter the access code to enable uploads for this account.",
            )
    # A key typed into the browser (per-request, from Form) takes priority over
    # the server's own .env -- this lets a second person use their own OpenAI
    # quota against a shared instance without ever touching the server's
    # environment. It's used for this one request only and never persisted:
    # not written to disk, not put in the database, not logged.
    effective_key = openai_api_key or settings.openai_api_key
    if not effective_key:
        raise HTTPException(
            status_code=500,
            detail=(
                "No OpenAI API key available. Enter one in the Upload panel, or set "
                "OPENAI_API_KEY on the backend via `export OPENAI_API_KEY=...` or backend/.env."
            ),
        )

    pdf_bytes = await file.read()

    # Off the event loop, not on it. ingest_pdf() is entirely blocking work --
    # poppler and tesseract subprocesses, a synchronous LLM HTTP call, and
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
        openai_api_key=effective_key,
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
def get_package(package_id: str, request: Request) -> dict:
    settings = get_settings()
    with psycopg.connect(settings.database_url) as conn:
        user_id, _ = require_user(request, conn)
        assert_owns_package(conn, user_id, package_id)
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
def list_letters(package_id: str, request: Request) -> list[dict]:
    settings = get_settings()
    with psycopg.connect(settings.database_url) as conn:
        user_id, _ = require_user(request, conn)
        assert_owns_package(conn, user_id, package_id)
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


@app.get("/api/packages/{package_id}/documents")
def list_documents(package_id: str, request: Request) -> list[dict]:
    """Upload history: what went in, when, and what came of it.

    Without this a document that failed extraction is simply ABSENT from the
    register, which looks identical to never having been uploaded. Showing the
    failure and its reason is the difference between a register you can trust to
    be complete and one you merely hope is.
    """
    settings = get_settings()
    with psycopg.connect(settings.database_url) as conn:
        user_id, _ = require_user(request, conn)
        assert_owns_package(conn, user_id, package_id)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT d.sha256, d.original_filename, d.byte_size, d.ingested_at,
                       (SELECT count(*) FROM document_pages dp
                         WHERE dp.document_sha256 = d.sha256) AS pages,
                       (SELECT count(*) FROM letters l
                         WHERE l.document_sha256 = d.sha256 AND l.package_id = %s
                           AND l.is_current) AS letters,
                       er.status, er.error
                FROM package_documents pd
                JOIN documents d ON d.sha256 = pd.document_sha256
                LEFT JOIN extraction_runs er
                       ON er.document_sha256 = d.sha256
                      AND er.package_id = pd.package_id AND er.is_current
                WHERE pd.package_id = %s
                ORDER BY d.ingested_at DESC
                """,
                (package_id, package_id),
            )
            rows = cur.fetchall()

    return [
        {
            "sha256": sha256,
            "filename": filename,
            "byteSize": byte_size,
            "ingestedAt": ingested_at.isoformat(),
            "pages": pages,
            "letters": letters,
            "status": status or "unknown",
            "error": error,
        }
        for sha256, filename, byte_size, ingested_at, pages, letters, status, error in rows
    ]


@app.get("/api/documents/{sha256}/original")
def download_original(sha256: str, request: Request):
    """The original PDF back out of the register, byte-for-byte.

    Serving the stored bytes rather than anything re-derived matters here: this
    is the artefact an annexure bundle would contain, and its sha256 is its
    identity, so what comes out must be exactly what went in.
    """
    settings = get_settings()
    with psycopg.connect(settings.database_url) as conn:
        user_id, _ = require_user(request, conn)
        assert_owns_document(conn, user_id, sha256)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT storage_uri, original_filename FROM documents WHERE sha256 = %s", (sha256,)
            )
            row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="No such document.")
    path = Path(row[0].removeprefix("file://"))
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Original file missing from storage.")
    # HTTP headers are latin-1; real filenames here are not. One of these
    # documents is "... GFC Drawing \u2013 Superstructure ...", whose en dash
    # raised UnicodeEncodeError and turned the download into a 500. RFC 6266:
    # an ASCII-safe `filename` for old clients plus `filename*` carrying the
    # real UTF-8 name.
    filename = row[1]
    ascii_name = filename.encode("ascii", "replace").decode("ascii").replace('"', "")
    quoted = urllib.parse.quote(filename, safe="")
    return Response(
        content=path.read_bytes(),
        media_type="application/pdf",
        headers={
            "Content-Disposition":
                f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quoted}'
        },
    )


@app.get("/api/letters/{letter_id}/fields")
def get_letter_fields(letter_id: str, request: Request) -> list[dict]:
    """Per-field provenance for one letter: the exact page, bounding box, and
    validation outcome behind every extracted value -- the citation data
    PIPELINE.md's click-to-locate feature is built on. `bbox` is null when
    validation is 'unresolved' (nothing to point at) and always normalized 0..1
    against the page image, not pixels, so it works at any raster resolution."""
    settings = get_settings()
    with psycopg.connect(settings.database_url) as conn:
        user_id, _ = require_user(request, conn)
        assert_owns_letter(conn, user_id, letter_id)
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
def get_page_raster(sha256: str, page_no: int, request: Request):
    """Serves the actual rasterized scan for one page -- the real source image
    the register's extracted values were read from, not a placeholder."""
    settings = get_settings()
    with psycopg.connect(settings.database_url) as conn:
        user_id, _ = require_user(request, conn)
        assert_owns_document(conn, user_id, sha256)
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
def list_ambiguous_citations(package_id: str, request: Request) -> list[dict]:
    """Citations that fuzzy-matched a candidate but were never auto-resolved --
    see link.py's reasoning: the exact digits that would tell two real letters
    apart are the part most vulnerable to OCR noise, so a plausible-looking
    match is not the same thing as a confirmed one. This is the review queue a
    human works through to actually confirm (or leave alone) each one."""
    settings = get_settings()
    with psycopg.connect(settings.database_url) as conn:
        user_id, _ = require_user(request, conn)
        assert_owns_package(conn, user_id, package_id)
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
def confirm_citation(citation_id: str, body: ConfirmCitationBody, request: Request) -> dict:
    """Links a citation to the human-confirmed candidate and re-threads the
    package. This is the ONLY path that turns a fuzzy match into a resolved
    one -- the pipeline itself never does this automatically."""
    settings = get_settings()
    with psycopg.connect(settings.database_url) as conn:
        user_id, _ = require_user(request, conn)
        assert_owns_citation(conn, user_id, citation_id)
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
                """
                UPDATE citations
                SET resolution = 'resolved', cited_letter_id = %s,
                    resolution_source = 'human'
                WHERE id = %s
                RETURNING cited_ref_normalized
                """,
                (body.candidate_letter_id, citation_id),
            )
            (cited_ref_normalized,) = cur.fetchone()

            # Remember the decision, so the same OCR corruption does not have to
            # be re-confirmed on every future document that repeats it. Learned
            # ONLY from this explicit confirmation -- never from a score -- so
            # every alias is a human judgement that can be inspected or removed.
            # A later confirmation of the same string supersedes an earlier one.
            cur.execute(
                """
                INSERT INTO citation_aliases (package_id, cited_ref_normalized, letter_id)
                VALUES (%s, %s, %s)
                ON CONFLICT (package_id, cited_ref_normalized)
                DO UPDATE SET letter_id = EXCLUDED.letter_id, created_at = now()
                """,
                (package_id, cited_ref_normalized, body.candidate_letter_id),
            )

        # Apply the new alias across the package immediately, so a confirmation
        # resolves every other citation of the same reference at once instead of
        # presenting them one at a time.
        reresolve_package(conn, str(package_id))
        recompute_threads(conn, str(package_id))
        conn.commit()

    return {"status": "confirmed"}


class _CacheControlledStaticFiles(StaticFiles):
    """StaticFiles with cache headers that actually match what changes.

    Plain StaticFiles sends no Cache-Control at all -- only ETag/Last-Modified.
    With nothing explicit, browsers apply their OWN heuristic freshness (a
    fraction of the file's age), and can serve a cached `index.html` WITHOUT
    even asking the server. That is actively dangerous here: every deploy
    replaces the container filesystem outright, so a hashed asset from two
    deploys ago (e.g. `index-BE9fNK-7.js`) no longer exists on the new one.
    A browser holding a stale `index.html` that references it hits a 404 for
    the app's own entry script -- on every refresh, because the cached HTML
    that's causing it is exactly what a plain refresh does NOT re-fetch.
    Reproduced directly: an old bundle hash from a stale page load 404'd
    against the current deploy.

    The fix is the standard split for content-hashed builds:
      - `index.html` (and anything else NOT under /assets/, e.g. favicon.svg):
        no-cache -- browsers may keep a copy but MUST revalidate with the
        server on every load, so a new deploy is picked up on the very next
        request rather than whenever the heuristic cache happens to expire.
      - `/assets/*` (Vite's content-hashed filenames): immutable, cached for a
        year. Safe specifically BECAUSE any content change produces a new
        filename -- the old name never changes meaning underneath it.
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        path = str(args[0]) if args else ""
        if "/assets/" in path:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache"
        return response


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
    app.mount("/", _CacheControlledStaticFiles(directory=_frontend_dist, html=True), name="frontend")
