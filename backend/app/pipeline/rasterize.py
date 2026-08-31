"""S1 — Rasterize. PDF bytes -> page images at 300 DPI. No preprocessing beyond DPI
(no deskew/despeckle/threshold) — PIPELINE.md is explicit that preprocessing is a
policy to benchmark, not apply blindly, and this build has no benchmark yet."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from pdf2image import convert_from_bytes
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


def rasterize_pdf(pdf_bytes: bytes) -> list[Page]:
    images = convert_from_bytes(pdf_bytes, dpi=DPI)
    return [
        Page(page_no=i + 1, image=img, width_px=img.width, height_px=img.height)
        for i, img in enumerate(images)
    ]
