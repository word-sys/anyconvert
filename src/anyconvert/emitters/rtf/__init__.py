"""RTF 1.9.1 (Rich Text Format) document emitter package."""

from __future__ import annotations

from anyconvert.emitters.rtf.emitter import (
    RtfColorTable,
    RtfEmitter,
    RtfFontTable,
    RtfStyleSheet,
)
from anyconvert.emitters.rtf.unicode import (
    CP_ARABIC,
    CP_CENTRAL_EUR,
    CP_CYRILLIC,
    CP_GREEK,
    CP_HEBREW,
    CP_JAPANESE,
    CP_KOREAN,
    CP_SIMPLIFIED_CHINESE,
    CP_TURKISH,
    CP_WESTERN,
    RtfCodePageProfile,
    classify_rtf_font_family,
    clean_rtf_font_name,
    detect_rtf_codepage,
    encode_rtf_unicode,
    escape_rtf_text,
    get_codepage_profile,
    resolve_rtf_font,
)

__all__ = [
    "RtfEmitter",
    "RtfFontTable",
    "RtfColorTable",
    "RtfStyleSheet",
    "RtfCodePageProfile",
    "CP_WESTERN",
    "CP_CENTRAL_EUR",
    "CP_CYRILLIC",
    "CP_GREEK",
    "CP_TURKISH",
    "CP_HEBREW",
    "CP_ARABIC",
    "CP_JAPANESE",
    "CP_SIMPLIFIED_CHINESE",
    "CP_KOREAN",
    "get_codepage_profile",
    "detect_rtf_codepage",
    "clean_rtf_font_name",
    "resolve_rtf_font",
    "classify_rtf_font_family",
    "encode_rtf_unicode",
    "escape_rtf_text",
]
