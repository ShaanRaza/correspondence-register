"""Orchestrates S0-S8 for one uploaded PDF against one package. See PIPELINE.md.

One simplification from PIPELINE.md's original description, stated honestly rather
than silently: letter-boundary detection (splitting one PDF into several physical
letters) is delegated to the S3 extraction call itself (the model returns page_from/
page_to per letter) rather than a separate deterministic heuristic — a real boundary
detector for "a fresh reference-header block" is a genuine sub-project on its own,
and delegating the structural judgment to the model, while still requiring every
FIELD VALUE to be independently verbatim-verified in S4, keeps the evidentiary
guarantee (nothing is asserted without provenance) while accepting that document
splitting itself is not (yet) independently verified against the source.

This is a synchronous, per-request pipeline (no job queue) for the demo: 10
documents, uploaded one at a time, is not a scale that needs async workers. The
Postgres jobs table + reprocessing-match code from earlier in this project remain
the design for when that changes.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

import psycopg
from openai import OpenAI

from .extract import MODEL as EXTRACTION_MODEL, extract_document
from .link import choose_ref, recompute_threads, resolve_citations
from .ocr import OcrPage, recognize_page
from .provenance import map_span_to_bbox
from .rasterize import get_page_count, rasterize_page
from .storage import LocalBlobStore, original_key, raster_key, sha256_hex
from .validate import validate_verbatim

# Bumped whenever anything that can change the register changes -- here the
# extraction model. v1 Claude Opus 5, v2 Gemini, v3 OpenAI. The schema treats
# pipeline_versions as the provenance record for exactly this, so a new LLM
# gets a new version rather than silently reusing the old one's identity.
PIPELINE_VERSION_ID = "v3"


def normalize_ref(ref: str) -> str:
    ref = unicodedata.normalize("NFC", ref)
    return " ".join(ref.split()).upper()


def _fetch_parties(conn: psycopg.Connection, package_id: str) -> dict[str, str]:
    """{short_code: party_id} for this package, e.g. {'CTR': ..., 'AE': ...}."""
    with conn.cursor() as cur:
        cur.execute("SELECT short_code, id FROM parties WHERE package_id = %s", (package_id,))
        return {row[0]: str(row[1]) for row in cur.fetchall()}


def _resolve_party(text: str | None, parties: dict[str, str]) -> str | None:
    """Best-effort substring match against this package's seeded CTR/AE parties.
    Real correspondence phrases parties in many ways ("M/s ABC Construction Ltd",
    "The Authority Engineer, NH-44") -- this is a first pass, not a directory
    lookup, and is expected to leave many letters unresolved rather than guess."""
    if not text:
        return None
    lowered = text.lower()
    if "contractor" in lowered and "CTR" in parties:
        return parties["CTR"]
    if ("authority engineer" in lowered or "engineer" in lowered) and "AE" in parties:
        return parties["AE"]
    return None


@dataclass
class IngestResult:
    document_sha256: str
    is_duplicate: bool
    extraction_run_id: str | None
    letter_ids: list[str]
    error: str | None = None
    # Candidate letters this run found that matched an ALREADY-REGISTERED letter_ref
    # in the package (a re-scan or duplicate submission of the same correspondence,
    # not a new item) -- {"letter_ref": ..., "existing_letter_id": ...} per match.
    matched_existing: list[dict] | None = None


def _ensure_pipeline_version(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO pipeline_versions (id, ocr_provider, ocr_provider_version, llm_model,
                                            prompt_sha256, schema_sha256, config)
            VALUES (%s, 'tesseract', '5.5.3', %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (PIPELINE_VERSION_ID, EXTRACTION_MODEL, "0" * 64, "0" * 64,
             psycopg.types.json.Json({"lang": "eng+hin"})),
        )


def ingest_pdf(
    conn: psycopg.Connection,
    store: LocalBlobStore,
    openai_client: OpenAI,
    *,
    package_id: str,
    pdf_bytes: bytes,
    original_filename: str,
    contract_conditions: str,
    package_context: str,
) -> IngestResult:
    _ensure_pipeline_version(conn)

    # --- S0: intake ---
    sha256 = sha256_hex(pdf_bytes)
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM documents WHERE sha256 = %s", (sha256,))
        already_exists = cur.fetchone() is not None

    if not already_exists:
        # Write the blob only if it isn't already there. The database row and the
        # blob can legitimately disagree: the store is keyed by content hash and
        # outlives any single database, so pointing a fresh/reset database at an
        # existing storage root leaves blobs present with no matching row. Calling
        # put() unconditionally then raised FileExistsError from the immutability
        # guard and failed the whole upload -- every re-upload after a database
        # reset died this way. Skipping is safe precisely BECAUSE the key is the
        # sha256: an existing object at this key is byte-identical by construction,
        # so there is nothing to overwrite and immutability is still honoured.
        blob_key = original_key(sha256)
        if not store.exists(blob_key):
            store.put(blob_key, pdf_bytes, immutable=True)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO documents (sha256, byte_size, mime_type, original_filename, storage_uri)
                VALUES (%s, %s, 'application/pdf', %s, %s)
                """,
                (sha256, len(pdf_bytes), original_filename, store.uri(original_key(sha256))),
            )

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO package_documents (package_id, document_sha256) VALUES (%s, %s) "
            "ON CONFLICT DO NOTHING",
            (package_id, sha256),
        )
        cur.execute(
            "SELECT 1 FROM extraction_runs WHERE document_sha256 = %s AND package_id = %s AND is_current",
            (sha256, package_id),
        )
        if cur.fetchone() is not None:
            return IngestResult(sha256, True, None, [], error=None)

    # --- S1 + S2: rasterize and OCR one page at a time -- keeping every page's
    # decoded image in memory at once (the previous approach) is what OOM-killed
    # a real request on a memory-constrained deployment. See rasterize.py.
    page_count = get_page_count(pdf_bytes)
    ocr_pages: dict[int, OcrPage] = {}
    for page_no in range(1, page_count + 1):
        page = rasterize_page(pdf_bytes, page_no)
        raster_bytes = page.png_bytes()
        key = raster_key(PIPELINE_VERSION_ID, sha256, page.page_no)
        if not store.exists(key):
            store.put(key, raster_bytes, immutable=True)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO document_pages (document_sha256, pipeline_version_id, page_no,
                                             width_px, height_px, dpi, raster_uri)
                VALUES (%s, %s, %s, %s, %s, 300, %s)
                ON CONFLICT (document_sha256, pipeline_version_id, page_no) DO NOTHING
                """,
                (sha256, PIPELINE_VERSION_ID, page.page_no, page.width_px, page.height_px, store.uri(key)),
            )
        ocr_pages[page.page_no] = recognize_page(page)  # raises if the invariant fails

    # --- S3: extraction (one LLM call for the whole document) ---
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO extraction_runs (document_sha256, package_id, pipeline_version_id, status)
            VALUES (%s, %s, %s, 'running') RETURNING id
            """,
            (sha256, package_id, PIPELINE_VERSION_ID),
        )
        (extraction_run_id,) = cur.fetchone()

    # page_ocr is scoped to (extraction_run_id, page_no) -- not document_pages -- because
    # OCR text/tokens can legitimately differ between runs (a re-extraction under a new
    # pipeline_version). extracted_fields' composite FK requires this row to exist before
    # any field can cite a page, so it must be written before S6 inserts any field.
    with conn.cursor() as cur:
        for page_no, ocr_page in ocr_pages.items():
            tokens_json = [
                {
                    "text": t.text,
                    "char_start": t.char_start,
                    "char_end": t.char_end,
                    "bbox": {"x": t.bbox.x, "y": t.bbox.y, "width": t.bbox.width, "height": t.bbox.height},
                    "confidence": t.confidence,
                }
                for t in ocr_page.tokens
            ]
            cur.execute(
                """
                INSERT INTO page_ocr (extraction_run_id, document_sha256, page_no, text, tokens,
                                       provider, provider_version)
                VALUES (%s, %s, %s, %s, %s, 'tesseract', '5.5.3')
                """,
                (extraction_run_id, sha256, page_no, ocr_page.text, psycopg.types.json.Json(tokens_json)),
            )

    try:
        result = extract_document(
            openai_client,
            contract_conditions=contract_conditions,
            package_context=package_context,
            page_texts={pno: p.text for pno, p in ocr_pages.items()},
        )
    except Exception as e:  # noqa: BLE001 - genuinely need to record any failure
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE extraction_runs SET status = 'failed', error = %s, finished_at = now() WHERE id = %s",
                (str(e), extraction_run_id),
            )
        conn.commit()
        return IngestResult(sha256, False, str(extraction_run_id), [], error=str(e))

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE extraction_runs
            SET status = 'succeeded', is_current = true, finished_at = now(),
                llm_request_id = %s, input_tokens = %s, output_tokens = %s, cache_read_tokens = %s
            WHERE id = %s
            """,
            (
                result.request_id,
                result.usage.input_tokens,
                result.usage.output_tokens,
                result.usage.cache_read_tokens,
                extraction_run_id,
            ),
        )
        cur.execute(
            """
            INSERT INTO llm_requests (extraction_run_id, model, llm_request_id, input_tokens,
                                       output_tokens, cache_read_tokens, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'succeeded')
            """,
            (extraction_run_id, EXTRACTION_MODEL, result.request_id, result.usage.input_tokens,
             result.usage.output_tokens, result.usage.cache_read_tokens),
        )

    # --- S6: assembly + deterministic serial assignment (this document's letters only) ---
    raw_letters = result.raw.get("letters", [])
    candidates = []
    for raw in raw_letters:
        ref_field = raw.get("letter_ref") or {}
        # See choose_ref(): the tight `value` when it is contained in the
        # validated `verbatim` span, otherwise the verbatim itself.
        ref_verbatim = choose_ref(ref_field)
        candidates.append(
            {
                "raw": raw,
                "letter_ref": ref_verbatim,
                "letter_ref_normalized": normalize_ref(ref_verbatim or "") or None,
                "dated": (raw.get("dated") or {}).get("value"),
                "page_from": raw.get("page_from", 1),
                "page_to": raw.get("page_to", 1),
            }
        )
    # Deterministic order: (dated, letter_ref_normalized, page_from) -- reproducible
    # regardless of the order Claude happened to list letters in.
    candidates.sort(key=lambda c: (c["dated"] or "", c["letter_ref_normalized"] or "", c["page_from"]))

    parties = _fetch_parties(conn, package_id)
    letter_ids: list[str] = []
    matched_existing: list[dict] = []
    for cand in candidates:
        raw = cand["raw"]

        # Near-duplicate check: a letter_ref already registered in this package --
        # from ANY source document, not just a re-extraction of this same one --
        # means this is a re-scan or duplicate submission of the same physical
        # correspondence, not a new register entry. The register is one row per
        # distinct letter, never one per scanned copy (see PIPELINE.md's "one row
        # per logical letter" invariant). Matched on letter_ref_normalized alone --
        # real EPC reference numbers are assigned once per letter and are the
        # authoritative identifier a register runs on; requiring the date to also
        # match would let an OCR misread of the date defeat the very check meant
        # to catch a re-scan. Fields are still extracted and stored (with no
        # letter_id) so the document's own audit trail is never lost, even though
        # it doesn't mint a second row.
        if cand["letter_ref_normalized"]:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM letters WHERE package_id = %s AND is_current AND letter_ref_normalized = %s",
                    (package_id, cand["letter_ref_normalized"]),
                )
                existing = cur.fetchone()
            if existing is not None:
                matched_existing.append(
                    {"letter_ref": cand["letter_ref"], "existing_letter_id": str(existing[0])}
                )
                _insert_validated_fields(conn, extraction_run_id, None, raw, ocr_pages)
                continue

        from_text = (raw.get("from_party") or {}).get("value")
        to_text = (raw.get("to_party") or {}).get("value")
        from_party_id = _resolve_party(from_text, parties)
        to_party_id = _resolve_party(to_text, parties)
        if from_party_id == parties.get("CTR"):
            direction = "outward"
        elif to_party_id == parties.get("CTR"):
            direction = "inward"
        else:
            direction = None  # neither side resolved to the contractor -- flagged, not guessed

        with conn.cursor() as cur:
            cur.execute("SELECT next_serial FROM packages WHERE id = %s FOR UPDATE", (package_id,))
            (serial,) = cur.fetchone()
            cur.execute("UPDATE packages SET next_serial = next_serial + 1 WHERE id = %s", (package_id,))

            cur.execute(
                """
                INSERT INTO letters (package_id, document_sha256, extraction_run_id, serial,
                                      letter_ref, letter_ref_normalized, dated, subject,
                                      page_from, page_to, direction, from_party_id, to_party_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    package_id, sha256, extraction_run_id, serial,
                    cand["letter_ref"], cand["letter_ref_normalized"], cand["dated"],
                    (raw.get("subject") or {}).get("value"),
                    cand["page_from"], cand["page_to"], direction, from_party_id, to_party_id,
                ),
            )
            (letter_id,) = cur.fetchone()
            letter_ids.append(str(letter_id))

        _insert_validated_fields(conn, extraction_run_id, letter_id, raw, ocr_pages)

    # --- S7: citation resolution + threading (package-wide recompute) ---
    resolve_citations(conn, package_id, str(extraction_run_id))
    recompute_threads(conn, package_id)

    # --- S8: publish. Everything above this point in the function is fast,
    # deterministic DB writes (no OCR/LLM calls) except the S3 call itself, which
    # already committed its own status row separately -- committing here makes the
    # letters/citations/threads for this document visible atomically. ---
    conn.commit()
    return IngestResult(sha256, False, str(extraction_run_id), letter_ids, matched_existing=matched_existing or None)


def _insert_field(
    conn: psycopg.Connection, extraction_run_id, letter_id, field_key: str, field_index: int,
    field_obj: dict | None, ocr_pages: dict[int, OcrPage],
) -> None:
    if not field_obj:
        return
    verbatim = field_obj.get("verbatim", "")
    value = field_obj.get("value", "")
    page_no = field_obj.get("page")
    page = ocr_pages.get(page_no)

    if page is None:
        validation, char_start, char_end, bbox = "unresolved", None, None, None
    else:
        v = validate_verbatim(page.text, verbatim)
        validation, char_start, char_end = v.validation, v.char_start, v.char_end
        bbox = (
            map_span_to_bbox(page, char_start, char_end)
            if validation != "unresolved"
            else None
        )
        if bbox is None and validation != "unresolved":
            validation, char_start, char_end = "unresolved", None, None

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO extracted_fields (extraction_run_id, letter_id, field_key, field_index,
                                           value_text, value_verbatim, page_no, char_start, char_end,
                                           bbox, validation)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                extraction_run_id, letter_id, field_key, field_index, value, verbatim,
                page_no if validation != "unresolved" else None,
                char_start, char_end,
                psycopg.types.json.Json(bbox) if bbox else None,
                validation,
            ),
        )


def _insert_validated_fields(conn, extraction_run_id, letter_id, raw: dict, ocr_pages) -> None:
    _insert_field(conn, extraction_run_id, letter_id, "letter_ref", 0, raw.get("letter_ref"), ocr_pages)
    _insert_field(conn, extraction_run_id, letter_id, "dated", 0, raw.get("dated"), ocr_pages)
    _insert_field(conn, extraction_run_id, letter_id, "received", 0, raw.get("received"), ocr_pages)
    _insert_field(conn, extraction_run_id, letter_id, "from_party", 0, raw.get("from_party"), ocr_pages)
    _insert_field(conn, extraction_run_id, letter_id, "to_party", 0, raw.get("to_party"), ocr_pages)
    _insert_field(conn, extraction_run_id, letter_id, "subject", 0, raw.get("subject"), ocr_pages)
    for i, ch in enumerate(raw.get("chainage") or []):
        _insert_field(conn, extraction_run_id, letter_id, "chainage", i, ch, ocr_pages)
    for i, cl in enumerate(raw.get("clause") or []):
        _insert_field(conn, extraction_run_id, letter_id, "clause", i, cl, ocr_pages)
    for i, cr in enumerate(raw.get("cited_refs") or []):
        _insert_field(conn, extraction_run_id, letter_id, "cited_ref", i, cr, ocr_pages)
