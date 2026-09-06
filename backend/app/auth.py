"""Accounts and sessions.

Each person gets a PRIVATE register, so the app has to know who is asking. That
is the whole reason identity exists here -- not user management for its own
sake. It also lets an evidentiary decision name an account rather than an
anonymous "human".

Deliberately self-contained: no external identity provider and no email
delivery, so the deployment has no third-party dependency and nothing extra to
pay for or configure.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import psycopg
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import HTTPException, Request

# argon2id at the library's defaults -- memory-hard, and the current best
# practice for password storage.
_hasher = PasswordHasher()

SESSION_COOKIE = "cr_session"
SESSION_DAYS = 30


def hash_password(plaintext: str) -> str:
    return _hasher.hash(plaintext)


def verify_password(password_hash: str, plaintext: str) -> bool:
    try:
        _hasher.verify(password_hash, plaintext)
        return True
    except (VerifyMismatchError, InvalidHashError):
        return False


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _token_hash(raw_token: str) -> str:
    """Only the hash is stored. A database dump therefore contains nothing that
    can be replayed as a login."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


def create_session(conn: psycopg.Connection, user_id: str) -> tuple[str, datetime]:
    """Returns (raw token for the cookie, expiry). The raw token is never persisted."""
    raw = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (%s, %s, %s)",
            (_token_hash(raw), user_id, expires),
        )
    return raw, expires


def delete_session(conn: psycopg.Connection, raw_token: str) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM sessions WHERE token_hash = %s", (_token_hash(raw_token),))


def user_for_token(conn: psycopg.Connection, raw_token: str | None) -> tuple[str, str] | None:
    """(user_id, email) for a live session, or None. Expired rows are deleted on
    sight so the table does not accumulate them."""
    if not raw_token:
        return None
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.user_id, u.email, s.expires_at
            FROM sessions s JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = %s
            """,
            (_token_hash(raw_token),),
        )
        row = cur.fetchone()
        if row is None:
            return None
        user_id, email, expires_at = row
        if expires_at <= datetime.now(timezone.utc):
            cur.execute("DELETE FROM sessions WHERE token_hash = %s", (_token_hash(raw_token),))
            return None
    return str(user_id), email


def require_user(request: Request, conn: psycopg.Connection) -> tuple[str, str]:
    user = user_for_token(conn, request.cookies.get(SESSION_COOKIE))
    if user is None:
        raise HTTPException(status_code=401, detail="Not signed in.")
    return user


def package_for_user(conn: psycopg.Connection, user_id: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM packages WHERE owner_user_id = %s ORDER BY created_at LIMIT 1",
            (user_id,),
        )
        row = cur.fetchone()
    return str(row[0]) if row else None


def assert_owns_package(conn: psycopg.Connection, user_id: str, package_id: str) -> None:
    """Every route returning register content passes through here. Without it a
    signed-in user could read another account's register just by knowing its id."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM packages WHERE id = %s AND owner_user_id = %s", (package_id, user_id)
        )
        if cur.fetchone() is None:
            # 404 rather than 403: a wrong owner should not be able to learn
            # that a package id exists at all.
            raise HTTPException(status_code=404, detail="No such package.")


def assert_owns_letter(conn: psycopg.Connection, user_id: str, letter_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM letters l JOIN packages p ON p.id = l.package_id
            WHERE l.id = %s AND p.owner_user_id = %s
            """,
            (letter_id, user_id),
        )
        if cur.fetchone() is None:
            raise HTTPException(status_code=404, detail="No such letter.")


def assert_owns_document(conn: psycopg.Connection, user_id: str, sha256: str) -> None:
    """A document is reachable only through a package the caller owns. Page
    rasters are the scanned correspondence itself, so this is the check that
    stops one account reading another's source images by content hash."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM package_documents pd JOIN packages p ON p.id = pd.package_id
            WHERE pd.document_sha256 = %s AND p.owner_user_id = %s
            """,
            (sha256, user_id),
        )
        if cur.fetchone() is None:
            raise HTTPException(status_code=404, detail="No such document.")


def assert_owns_citation(conn: psycopg.Connection, user_id: str, citation_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM citations c JOIN packages p ON p.id = c.package_id
            WHERE c.id = %s AND p.owner_user_id = %s
            """,
            (citation_id, user_id),
        )
        if cur.fetchone() is None:
            raise HTTPException(status_code=404, detail="No such citation.")
