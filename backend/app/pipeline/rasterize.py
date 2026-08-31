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

from dataclasses import dataclass
from io import BytesIO

from pdf2image import convert_from_bytes, pdfinfo_from_bytes
from PIL import Image

DPI = 300


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


def get_page_count(pdf_bytes: bytes) -> int:
    return pdfinfo_from_bytes(pdf_bytes)["Pages"]


def rasterize_page(pdf_bytes: bytes, page_no: int) -> Page:
    """Renders exactly one page (1-indexed). Re-parses the PDF from bytes each
    call -- pdf2image/poppler don't expose a way to keep a decoded document
    open across calls, so this trades a small amount of repeated parsing
    overhead for the memory bound described above."""
    images = convert_from_bytes(pdf_bytes, dpi=DPI, first_page=page_no, last_page=page_no)
    img = images[0]
    return Page(page_no=page_no, image=img, width_px=img.width, height_px=img.height)
