# Running this yourself

This is a per-package correspondence register for EPC contractor correspondence —
real OCR, real Gemini extraction, real provenance. These steps get it running on
your own machine with your own data and your own API key; nothing from the
person who sent you this is included (no documents, no credentials).

Written for macOS with Homebrew. If you're on Linux, swap `brew install` for
your distro's package manager; package names are usually the same or close.

## 1. Prerequisites

```bash
brew install postgresql@18 tesseract tesseract-lang poppler python@3.11 node
brew services start postgresql@18
```

`tesseract-lang` adds the Hindi/Devanagari OCR pack this pipeline uses alongside
English. `poppler` provides `pdftoppm`, used to rasterize PDF pages.

## 2. Database

```bash
createdb correspondence_register
psql -d correspondence_register -f db/schema.sql
psql -d correspondence_register -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
```

## 3. Backend

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

Open `backend/.env` and fill in `DATABASE_URL` with your own Postgres username
(run `whoami` if unsure — the default `postgresql://postgres@localhost/...`
often isn't right on macOS, where your own username is usually the role).
Leave `GEMINI_API_KEY` blank here — you'll enter it in the browser instead (see
step 6), which is the easier path if you're just trying this out. Only set it
here if you want every upload from this machine to use the same key by default.

Seed the one package this build ingests documents into:

```bash
python -m scripts.seed_upload_package
```

This prints a `package_id`. Open `frontend/src/lib/api.ts` and replace the
`UPLOAD_PACKAGE_ID` constant with the one it printed.

Start the backend:

```bash
uvicorn app.main:app --port 8000 --reload
```

## 4. Frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open the URL it prints (typically `http://localhost:5173`).

## 5. Get a free Gemini API key

Free tier, no credit card: https://aistudio.google.com/apikey — capped at
20 requests/day, and each document you upload is one request.

## 6. Use it

Click **Upload** in the title bar. Paste your Gemini key into the "Gemini API
key" field there (it's saved only in your browser, sent only with your own
uploads — nothing about it touches this codebase). Drop in a real PDF letter
and watch it actually get OCR'd, extracted, and validated — this isn't a demo
with fixture data, it's the real pipeline running against whatever you give it.

## What you get vs. what you don't

Real: OCR (Tesseract, English + Hindi), LLM extraction (Gemini) with
verbatim-verified fields, click-to-locate source highlighting on the actual
scanned page, deterministic duplicate/near-duplicate detection, citation
threading with a human-review step for ambiguous matches.

Not included: any authentication (this is a single-user local tool, don't
expose it to the internet as-is), the original sender's uploaded documents or
database contents (you're starting from an empty package), production
deployment config of any kind.
