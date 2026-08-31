"""S1 — Rasterize. PDF bytes -> page images at 300 DPI. No preprocessing beyond DPI
(no deskew/despeckle/threshold) — PIPELINE.md is explicit that preprocessing is a
policy to benchmark, not apply blindly, and this build has no benchmark yet.

Rasterizes ONE PAGE AT A TIME rather than the whole document up front. A real
multi-page scan at 300 DPI is tens of MB per page as a decoded PIL Image;
loading every page simultaneously (the previous approach, `convert_from_bytes`
with no page range) was fine on a local machine but genuinely OOM-killed the
process on a memory-constrained deployment (512MB free-tier container) --
found by seeing a real request hang for ~50s then the whole server restart
with no traceback, which matches a hard kill rather than a raised exception.
Peak memory now holds at most one rasterized page plus one OCR pass over it,
regardless of document length.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from io import BytesIO

import pytesseract
from pdf2image import convert_from_bytes, pdfinfo_from_bytes
from PIL import Image

# 300 DPI is the standard recommendation for document OCR and stays the default
# (local runs, and any host with real CPU/RAM, should use it). It is overridable
# because rendering cost scales with the square of DPI: on a 0.1-CPU / 512MB
# free-tier container, 300 DPI OCR of a full page is slow enough to be
# impractical, and 200 DPI cuts pixel count -- so both memory and tesseract CPU
# time -- by ~56%. That IS an accuracy tradeoff on small or poor-quality print,
# so it is opt-in per deployment rather than lowered for everyone.
DPI = int(os.environ.get("RASTER_DPI", "300"))

# Grayscale rather than RGB: a third of the decoded image memory for scans of
# black-and-white correspondence, and no OCR accuracy cost -- tesseract
# binarizes internally regardless of how many channels it is handed.
GRAYSCALE = os.environ.get("RASTER_GRAYSCALE", "1") == "1"


@dataclass(frozen=True)
class Page:
    page_no: int  # 1-indexed
    image: Image.Image
    width_px: int
    height_px: int

    def png_bytes(self) -> bytes:
        buf = BytesIO()
        self.image.save(buf, format="PNG")
        return buf.getvalue()


# Pages in real scanned correspondence are routinely fed through the scanner
# sideways or upside down. Tesseract does not correct for this on its own: it
# reads the rotated glyphs literally and emits confident-looking garbage --
# observed on real documents, where an upside-down page produced the reference
# "€91/AI-Dd/S707/SS@d-AG/0b-HN/A TA/GSd 'ON" (the true reference, reversed).
# That garbage then propagates: the letter's own reference is wrong, so its
# citations never match anything and the letter never joins a thread.
#
# Correcting orientation BEFORE OCR fixed the same page to
# "GOVERNMENT OF MEGHALAYA / OFFICE OF THE DEPUTY COMMISSIONER...".
# The rotated image is what gets stored and OCR'd, so bounding boxes, the
# stored raster and the click-to-locate viewer all stay in agreement -- and the
# viewer shows the page the right way up as a side effect.
AUTO_ORIENT = os.environ.get("RASTER_AUTO_ORIENT", "1") == "1"

# OSD reports a confidence alongside the angle. Real correctly-detected
# rotations in this corpus scored 23-30, so the floor only exists to ignore
# readings from pages with too little text to judge; it is not a quality bar.
MIN_ORIENT_CONFIDENCE = float(os.environ.get("RASTER_ORIENT_MIN_CONF", "5"))


def get_page_count(pdf_bytes: bytes) -> int:
    return pdfinfo_from_bytes(pdf_bytes)["Pages"]


def _auto_orient(image: Image.Image) -> Image.Image:
    """Rotate a page upright if Tesseract's orientation detection is confident.
    Never raises: OSD legitimately fails on sparse or image-only pages, and a
    page that cannot be assessed is simply left as scanned."""
    if not AUTO_ORIENT:
        return image
    try:
        osd = pytesseract.image_to_osd(image, output_type=pytesseract.Output.DICT)
    except Exception:
        return image
    rotate = osd.get("rotate", 0) or 0
    if rotate % 360 == 0 or osd.get("orientation_conf", 0) < MIN_ORIENT_CONFIDENCE:
        return image
    # OSD reports how far the page is rotated clockwise from upright, so undo it
    # by rotating the same amount counter-clockwise. expand=True keeps the whole
    # page when width and height swap on a 90/270 turn.
    return image.rotate(-rotate, expand=True)


def rasterize_page(pdf_bytes: bytes, page_no: int) -> Page:
    """Renders exactly one page (1-indexed). Re-parses the PDF from bytes each
    call -- pdf2image/poppler don't expose a way to keep a decoded document
    open across calls, so this trades a small amount of repeated parsing
    overhead for the memory bound described above."""
    images = convert_from_bytes(
        pdf_bytes, dpi=DPI, first_page=page_no, last_page=page_no, grayscale=GRAYSCALE
    )
    img = _auto_orient(images[0])
    return Page(page_no=page_no, image=img, width_px=img.width, height_px=img.height)
