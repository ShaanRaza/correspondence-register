"""S2 — OCR. Tesseract implementation of the OcrProvider protocol from PIPELINE.md.

The invariant every adapter must satisfy, asserted here on every page before it is
ever returned to the caller:

    for every token:  page.text[token.char_start:token.char_end] == token.text

as exact code-point equality (not "byte-identical" — see PIPELINE.md § S2 on why
that distinction is real for Devanagari). If this assertion fails, the adapter is
wrong and the page is never persisted — this is the single equality the entire
provenance chain (validation, highlighting, job 5's click-through) rests on.

lang='eng+hin': Hindi's script is Devanagari, and this product's correspondence
mixes English and Devanagari on the same line (see PRODUCT.md's bilingual
constraint) — a single OCR pass needs both scripts loaded.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

import pytesseract
from pytesseract import Output

from .rasterize import Page

TESSERACT_LANG = "eng+hin"


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class OcrToken:
    text: str
    char_start: int
    char_end: int
    bbox: Rect
    confidence: float


@dataclass(frozen=True)
class OcrPage:
    text: str
    tokens: list[OcrToken]


def _normalize_for_join(word: str) -> str:
    # NFC only — never strip/alter characters here. Devanagari conjuncts and matras
    # must survive untouched; this is normalization of composed-form representation,
    # not text cleanup. See PIPELINE.md's bilingual normalization warning.
    return unicodedata.normalize("NFC", word)


def recognize_page(page: Page) -> OcrPage:
    data = pytesseract.image_to_data(
        page.image, lang=TESSERACT_LANG, output_type=Output.DICT
    )

    n = len(data["text"])
    text_parts: list[str] = []
    tokens: list[OcrToken] = []
    cursor = 0
    prev_line_key: tuple[int, int, int] | None = None

    for i in range(n):
        raw_word = data["text"][i]
        word = _normalize_for_join(raw_word.strip())
        if not word:
            continue  # Tesseract emits non-word rows (block/par/line level) too

        line_key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        if prev_line_key is None:
            sep = ""
        elif line_key != prev_line_key:
            sep = "\n"
        else:
            sep = " "

        if sep:
            text_parts.append(sep)
            cursor += len(sep)

        char_start = cursor
        text_parts.append(word)
        cursor += len(word)
        char_end = cursor
        prev_line_key = line_key

        conf_raw = data["conf"][i]
        confidence = float(conf_raw) / 100.0 if float(conf_raw) >= 0 else 0.0

        bbox = Rect(
            x=data["left"][i] / page.width_px,
            y=data["top"][i] / page.height_px,
            width=data["width"][i] / page.width_px,
            height=data["height"][i] / page.height_px,
        )

        tokens.append(
            OcrToken(
                text=word,
                char_start=char_start,
                char_end=char_end,
                bbox=bbox,
                confidence=confidence,
            )
        )

    full_text = "".join(text_parts)

    # The invariant. Not a sanity check to log and continue past — a page that fails
    # this is never returned, because everything downstream trusts it unconditionally.
    for t in tokens:
        actual = full_text[t.char_start : t.char_end]
        if actual != t.text:
            raise AssertionError(
                f"OCR token invariant violated on page {page.page_no}: "
                f"text[{t.char_start}:{t.char_end}] = {actual!r}, expected {t.text!r}"
            )

    return OcrPage(text=full_text, tokens=tokens)
