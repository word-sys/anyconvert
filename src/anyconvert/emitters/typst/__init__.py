"""Typst (.typ) academic and scientific document emitter package."""

from __future__ import annotations

from anyconvert.emitters.typst.content import (
    is_code_paragraph,
    is_list_paragraph,
    is_monospace_font,
    render_typst_code_block,
    render_typst_page_blocks,
    render_typst_paragraph,
    render_typst_run,
    render_typst_table,
)
from anyconvert.emitters.typst.emitter import (
    TypstEmitter,
    clean_typst_font_name,
    escape_typst_markup,
    escape_typst_string,
)
from anyconvert.emitters.typst.math import (
    UNICODE_TO_TYPST_MATH,
    classify_math_font,
    contains_math_symbol,
    decode_math_font_text,
    detect_script_kind,
    is_math_font,
    render_typst_math_runs,
    translate_math_text_to_typst,
)

__all__ = [
    "TypstEmitter",
    "UNICODE_TO_TYPST_MATH",
    "classify_math_font",
    "clean_typst_font_name",
    "contains_math_symbol",
    "decode_math_font_text",
    "detect_script_kind",
    "escape_typst_string",
    "escape_typst_markup",
    "is_code_paragraph",
    "is_list_paragraph",
    "is_math_font",
    "is_monospace_font",
    "render_typst_code_block",
    "render_typst_math_runs",
    "render_typst_run",
    "render_typst_paragraph",
    "render_typst_page_blocks",
    "render_typst_table",
    "translate_math_text_to_typst",
]
