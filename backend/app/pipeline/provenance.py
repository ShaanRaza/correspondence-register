"""S5 — Provenance mapping. (page_no, char_start, char_end) -> the union rect and
per-token rects of every OCR token whose span overlaps [char_start, char_end).
Both are stored (not just the union) — a value wrapping two lines needs two
rectangles, or a union box would highlight text between them that isn't the value.
"""

from __future__ import annotations

from .ocr import OcrPage, Rect


def map_span_to_bbox(page: OcrPage, char_start: int, char_end: int) -> dict | None:
    overlapping = [
        t for t in page.tokens if t.char_start < char_end and t.char_end > char_start
    ]
    if not overlapping:
        return None

    min_x = min(t.bbox.x for t in overlapping)
    min_y = min(t.bbox.y for t in overlapping)
    max_x = max(t.bbox.x + t.bbox.width for t in overlapping)
    max_y = max(t.bbox.y + t.bbox.height for t in overlapping)

    return {
        "union": {"x": min_x, "y": min_y, "w": max_x - min_x, "h": max_y - min_y},
        "rects": [
            {"x": t.bbox.x, "y": t.bbox.y, "w": t.bbox.width, "h": t.bbox.height}
            for t in overlapping
        ],
    }
