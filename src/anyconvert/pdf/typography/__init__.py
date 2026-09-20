"""PDF typography, font engines, metric extractors, and CMap decoders."""

from __future__ import annotations

from anyconvert.pdf.typography.cff import CFFFont, CFFIndex
from anyconvert.pdf.typography.cmap import CMap, CodeSpaceRange, decode_cmap_hex
from anyconvert.pdf.typography.composite import CompositeFont
from anyconvert.pdf.typography.encodings import (
    ADOBE_GLYPH_LIST,
    MAC_ROMAN_ENCODING,
    PDF_DOC_ENCODING,
    STANDARD_ENCODING,
    SYMBOL_ENCODING,
    WIN_ANSI_ENCODING,
    ZAPF_DINGBATS_ENCODING,
    EncodingResolver,
    get_base_encoding,
    glyph_name_to_unicode,
    resolve_differences,
)
from anyconvert.pdf.typography.font import BaseFont, FontMetrics
from anyconvert.pdf.typography.sfnt import SFNTFont, SFNTTableRecord
from anyconvert.pdf.typography.type1 import (
    Type1Font,
    eexec_decrypt,
    eexec_encrypt,
    unpack_pfb,
)

__all__ = [
    "FontMetrics",
    "BaseFont",
    "SFNTTableRecord",
    "SFNTFont",
    "Type1Font",
    "eexec_decrypt",
    "eexec_encrypt",
    "unpack_pfb",
    "CFFIndex",
    "CFFFont",
    "CompositeFont",
    "CodeSpaceRange",
    "CMap",
    "decode_cmap_hex",
    "WIN_ANSI_ENCODING",
    "MAC_ROMAN_ENCODING",
    "STANDARD_ENCODING",
    "PDF_DOC_ENCODING",
    "SYMBOL_ENCODING",
    "ZAPF_DINGBATS_ENCODING",
    "ADOBE_GLYPH_LIST",
    "glyph_name_to_unicode",
    "get_base_encoding",
    "resolve_differences",
    "EncodingResolver",
]
