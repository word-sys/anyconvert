"""Unit test suite for Phase 10: CMap and Character Encodings."""

from __future__ import annotations

import pytest

from anyconvert.pdf.parser import PDFArray, PDFDict, PDFName
from anyconvert.pdf.typography.cmap import CMap, CodeSpaceRange, decode_cmap_hex
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


# ==============================================================================
# 1. Base Encoding Tests
# ==============================================================================


def test_base_encodings_standard_characters() -> None:
    # ASCII range in WinAnsi
    assert WIN_ANSI_ENCODING[65] == "A"
    assert WIN_ANSI_ENCODING[97] == "a"
    assert WIN_ANSI_ENCODING[32] == " "

    # WinAnsi extensions
    assert WIN_ANSI_ENCODING[128] == "\u20ac"  # Euro
    assert WIN_ANSI_ENCODING[149] == "\u2022"  # Bullet
    assert WIN_ANSI_ENCODING[150] == "\u2013"  # En-dash
    assert WIN_ANSI_ENCODING[151] == "\u2014"  # Em-dash
    assert WIN_ANSI_ENCODING[153] == "\u2122"  # Trademark
    assert WIN_ANSI_ENCODING[169] == "\u00a9"  # Copyright

    # MacRoman extensions
    assert MAC_ROMAN_ENCODING[128] == "\u00c4"  # A-dieresis
    assert MAC_ROMAN_ENCODING[165] == "\u2022"  # Bullet
    assert MAC_ROMAN_ENCODING[219] == "\u20ac"  # Euro

    # StandardEncoding
    assert STANDARD_ENCODING[39] == "\u2019"  # Quoteright
    assert STANDARD_ENCODING[96] == "\u2018"  # Quoteleft
    assert STANDARD_ENCODING[174] == "\ufb01"  # fi ligature
    assert STANDARD_ENCODING[175] == "\ufb02"  # fl ligature

    # PDFDocEncoding
    assert PDF_DOC_ENCODING[160] == "\u20ac"  # Euro

    # Symbol & ZapfDingbats
    assert SYMBOL_ENCODING[97] == "\u03b1"  # alpha
    assert SYMBOL_ENCODING[98] == "\u03b2"  # beta
    assert ZAPF_DINGBATS_ENCODING[33] == "\u2701"


def test_get_base_encoding_lookup() -> None:
    assert get_base_encoding("WinAnsiEncoding")[128] == "\u20ac"
    assert get_base_encoding(PDFName("WinAnsiEncoding"))[128] == "\u20ac"
    assert get_base_encoding("/MacRomanEncoding")[128] == "\u00c4"
    assert get_base_encoding("StandardEncoding")[174] == "\ufb01"
    assert get_base_encoding("PDFDocEncoding")[160] == "\u20ac"
    assert get_base_encoding("Symbol")[97] == "\u03b1"
    assert get_base_encoding("ZapfDingbats")[33] == "\u2701"


# ==============================================================================
# 2. Adobe Glyph List & Differences Tests
# ==============================================================================


def test_glyph_name_to_unicode() -> None:
    # Direct AGL
    assert glyph_name_to_unicode("bullet") == "\u2022"
    assert glyph_name_to_unicode("emdash") == "\u2014"
    assert glyph_name_to_unicode("fi") == "\ufb01"
    assert glyph_name_to_unicode("Euro") == "\u20ac"
    assert glyph_name_to_unicode("copyright") == "\u00a9"

    # Variant suffixes
    assert glyph_name_to_unicode("A.swash") == "A"
    assert glyph_name_to_unicode("e.alt") == "e"
    assert glyph_name_to_unicode("bullet.alt") == "\u2022"

    # uniXXXX algorithmic
    assert glyph_name_to_unicode("uni0041") == "A"
    assert glyph_name_to_unicode("uni0152") == "\u0152"  # OE
    assert glyph_name_to_unicode("uni00460046") == "FF"  # Multiple code units
    assert glyph_name_to_unicode("uni00460049") == "FI"

    # uXXXX algorithmic
    assert glyph_name_to_unicode("u0041") == "A"
    assert glyph_name_to_unicode("u0152") == "\u0152"
    assert glyph_name_to_unicode("u1F600") == "\U0001F600"  # 😀

    # Edge cases
    assert glyph_name_to_unicode(".notdef") is None
    assert glyph_name_to_unicode("") is None
    assert glyph_name_to_unicode("UnknownGlyphNameX99") is None


def test_resolve_differences() -> None:
    base = dict(WIN_ANSI_ENCODING)

    # Apply differences: starting at 24: breve, caron; starting at 30: dotaccent
    diffs = [
        24, PDFName("breve"), PDFName("caron"),
        30, "dotaccent",
        65, PDFName("bullet"),  # Override 'A' (65) with bullet
    ]

    mutated = resolve_differences(base, diffs)

    assert mutated[24] == "\u02d8"  # breve
    assert mutated[25] == "\u02c7"  # caron
    assert mutated[30] == "\u02d9"  # dotaccent
    assert mutated[65] == "\u2022"  # bullet overriding 'A'
    assert mutated[66] == "B"       # 'B' unchanged


def test_encoding_resolver() -> None:
    # Test resolving from PDF dictionary
    enc_dict = PDFDict({
        "Type": PDFName("Encoding"),
        "BaseEncoding": PDFName("WinAnsiEncoding"),
        "Differences": PDFArray([
            128, PDFName("fi"), PDFName("fl"),
        ]),
    })

    resolver = EncodingResolver(enc_dict)
    mapping = resolver.mapping

    assert mapping[128] == "\ufb01"  # fi
    assert mapping[129] == "\ufb02"  # fl
    assert mapping[65] == "A"
    assert resolver.decode_char(128) == "\ufb01"
    assert resolver.decode_char(65) == "A"


# ==============================================================================
# 3. CMap & /ToUnicode Tests
# ==============================================================================


def test_decode_cmap_hex() -> None:
    # 2-byte UTF-16
    assert decode_cmap_hex("<0041>") == "A"
    assert decode_cmap_hex("<0020>") == " "
    assert decode_cmap_hex("<20AC>") == "\u20ac"

    # Multi-character ligature
    assert decode_cmap_hex("<00460046>") == "FF"
    assert decode_cmap_hex("<00460049>") == "FI"

    # 4-byte surrogate pair (U+1F600 😀: D83D DE00)
    assert decode_cmap_hex("<D83DDE00>") == "\U0001F600"

    # 1-byte fallback
    assert decode_cmap_hex("<41>") == "A"


def test_cmap_parsing_and_string_decoding() -> None:
    cmap_text = """
    /CIDInit /ProcSet findresource begin
    12 dict begin
    begincmap
    /CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def
    /CMapName /Custom-ToUnicode def
    /CMapType 2 def
    1 begincodespacerange
      <0000> <FFFF>
    endcodespacerange
    2 beginbfchar
      <0001> <0041>
      <0002> <00460049>
    endbfchar
    1 beginbfrange
      <0010> <0012> <0061>
    endbfrange
    1 beginbfrange
      <0020> <0022> [ <0031> <0032> <0033> ]
    endbfrange
    endcmap
    CMapName currentdict /CMap defineresource pop
    end
    end
    """

    cmap = CMap.parse(cmap_text)

    assert cmap.name == "Custom-ToUnicode"
    assert cmap.cmap_type == 2
    assert len(cmap.codespaces) == 1
    assert cmap.codespaces[0].byte_len == 2

    # bfchar verification
    assert cmap.to_unicode(1) == "A"
    assert cmap.to_unicode(2) == "FI"

    # Linear bfrange verification (<0010>..<0012> -> 'a'..'c')
    assert cmap.to_unicode(0x0010) == "a"
    assert cmap.to_unicode(0x0011) == "b"
    assert cmap.to_unicode(0x0012) == "c"

    # Array bfrange verification (<0020>..<0022> -> '1'..'3')
    assert cmap.to_unicode(0x0020) == "1"
    assert cmap.to_unicode(0x0021) == "2"
    assert cmap.to_unicode(0x0022) == "3"

    # Content string decoding (2-byte codes)
    # Stream bytes: 0x0001 ('A') 0x0002 ('FI') 0x0010 ('a') 0x0020 ('1')
    raw_content = b"\x00\x01\x00\x02\x00\x10\x00\x20"
    decoded = cmap.decode_string(raw_content)
    assert decoded == "AFIa1"


def test_cmap_surrogate_pair_bfrange() -> None:
    # Test linear bfrange carrying over surrogate pairs (U+1F600 = D83D DE00)
    cmap_text = """
    begincmap
    1 begincodespacerange
      <0001> <0002>
    endcodespacerange
    1 beginbfrange
      <0001> <0002> <D83DDE00>
    endbfrange
    endcmap
    """

    cmap = CMap.parse(cmap_text)
    assert cmap.to_unicode(1) == "\U0001F600"  # 😀 (U+1F600)
    assert cmap.to_unicode(2) == "\U0001F601"  # 😁 (U+1F601)


def test_cmap_single_byte_codespace() -> None:
    cmap_text = """
    begincmap
    1 begincodespacerange
      <00> <FF>
    endcodespacerange
    1 beginbfrange
      <41> <43> <0041>
    endbfrange
    endcmap
    """

    cmap = CMap.parse(cmap_text)
    assert cmap.to_unicode(0x41) == "A"
    assert cmap.to_unicode(0x42) == "B"
    assert cmap.to_unicode(0x43) == "C"

    # 1-byte stream decoding
    raw_content = b"\x41\x42\x43"
    decoded = cmap.decode_string(raw_content)
    assert decoded == "ABC"
