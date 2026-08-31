"""Loads configuration from environment variables / backend/.env. Never hard-codes
a credential and never writes one — OPENAI_API_KEY is read from whatever the user
set themselves (shell env or their own .env file), consistent with the rule that
Claude never sees or enters API keys anywhere."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_BACKEND_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    openai_api_key: str | None
    database_url: str
    storage_root: Path
    # Shared-password gate, not real per-user auth: this app has no user model.
    # None means the gate is off (the local-dev default) -- set only when
    # actually deploying somewhere reachable by more than just you.
    app_password: str | None
    allowed_origin: str


def get_settings() -> Settings:
    return Settings(
        openai_api_key=os.environ.get("OPENAI_API_KEY") or None,
        database_url=os.environ.get(
            "DATABASE_URL", f"postgresql://{os.environ.get('USER', 'postgres')}@localhost:5432/correspondence_register"
        ),
        storage_root=Path(os.environ.get("STORAGE_ROOT", str(_BACKEND_ROOT / "storage"))).resolve(),
        app_password=os.environ.get("APP_PASSWORD") or None,
        allowed_origin=os.environ.get("ALLOWED_ORIGIN", "http://localhost:5173"),
    )
