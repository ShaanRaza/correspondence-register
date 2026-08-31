FROM python:3.11-slim

# Without this, Python block-buffers stdout/stderr when it isn't a TTY (true of
# any container) -- exception tracebacks from a failed request can be delayed
# or never flushed, showing only a bare "500" in the platform's logs with no
# way to see why. Confirmed the hard way: every upload 500'd with zero
# traceback in Render's logs until this was set.
ENV PYTHONUNBUFFERED=1

# Tesseract (+ Hindi/Devanagari pack, since correspondence mixes English and
# Hindi on the same line) and poppler-utils (pdftoppm, used to rasterize PDF
# pages) -- a plain Python buildpack has neither, and this pipeline needs both.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-hin \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
COPY scripts ./scripts

RUN pip install --no-cache-dir -e .

# Railway injects $PORT at runtime; STORAGE_ROOT here is container-local disk,
# which does NOT persist across deploys/restarts unless a volume is mounted at
# the same path -- fine for a throwaway/demo deployment, not for real evidence.
ENV STORAGE_ROOT=/app/storage
RUN mkdir -p /app/storage

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
