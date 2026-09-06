# One image serving BOTH the API and the built UI, on one origin.
#
# Single-origin is deliberate: it removes CORS from the deployment entirely and
# means the frontend never has to know its own public hostname. Two earlier
# attempts at a split frontend/backend deployment broke precisely there -- a
# frontend bundle pinned to a backend URL that later changed, and a password
# gate that swallowed CORS preflight.

# ---- Stage 1: build the frontend ----
FROM node:22-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# Empty (not unset) so api.ts's `??` resolves to same-origin relative URLs.
ENV VITE_API_BASE=""
RUN npm run build

# ---- Stage 2: runtime ----
FROM python:3.11-slim

# Without this, Python block-buffers stdout/stderr when it isn't a TTY (true of
# any container), so tracebacks can be delayed or lost -- leaving only a bare
# 500 in the platform log with no way to see the cause.
ENV PYTHONUNBUFFERED=1

# Tesseract (+ the Hindi/Devanagari pack, since this correspondence mixes
# English and Hindi on one line) and poppler-utils (pdftoppm, for rasterizing
# PDF pages). Neither ships with the base image; the pipeline needs both.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-hin \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/pyproject.toml ./
COPY backend/app ./app
COPY backend/scripts ./scripts
# The schema, so a blank hosted database can provision itself on first boot
# (app/bootstrap.py). There is no shell on this container to run psql from.
COPY db ./db
RUN pip install --no-cache-dir -e .

COPY --from=frontend /build/dist ./frontend_dist
ENV FRONTEND_DIST=/app/frontend_dist

# Container-local disk. NOT persistent across redeploys unless a volume is
# mounted here: database rows survive (Postgres is a separate service) but
# stored page rasters do not, so click-to-locate would 404 for documents
# ingested before a redeploy.
ENV STORAGE_ROOT=/app/storage
RUN mkdir -p /app/storage

# Railway injects $PORT; the default keeps this image runnable anywhere.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
