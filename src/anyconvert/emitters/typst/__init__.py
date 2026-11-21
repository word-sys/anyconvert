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

__all__ = [
    "TypstEmitter",
    "clean_typst_font_name",
    "escape_typst_string",
    "escape_typst_markup",
    "is_monospace_font",
    "is_code_paragraph",
    "is_list_paragraph",
    "render_typst_code_block",
    "render_typst_run",
    "render_typst_paragraph",
    "render_typst_page_blocks",
    "render_typst_table",
]
