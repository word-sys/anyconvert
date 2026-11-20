"""RTF 1.9.1 (Rich Text Format) document emitter package."""

from __future__ import annotations

from anyconvert.emitters.rtf.emitter import (
    RtfColorTable,
    RtfEmitter,
    RtfFontTable,
    RtfStyleSheet,
    classify_rtf_font_family,
    clean_rtf_font_name,
    escape_rtf_text,
)

__all__ = [
    "RtfEmitter",
    "RtfFontTable",
    "RtfColorTable",
    "RtfStyleSheet",
    "clean_rtf_font_name",
    "classify_rtf_font_family",
    "escape_rtf_text",
]
