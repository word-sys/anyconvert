"""Unit test suite for Phase 9: Type 1, CFF, and Composite fonts."""

from __future__ import annotations

import struct
from typing import List

import pytest

from anyconvert.common.geometry import BoundingBox
from anyconvert.pdf.parser import PDFArray, PDFDict, PDFIndirectRef, PDFName, PDFStream
from anyconvert.pdf.typography.cff import CFFFont, CFFIndex
from anyconvert.pdf.typography.composite import CompositeFont
from anyconvert.pdf.typography.sfnt import SFNTFont
from anyconvert.pdf.typography.type1 import (
    Type1Font,
    _parse_type1_charstring_width,
    eexec_decrypt,
    eexec_encrypt,
    unpack_pfb,
)


# ==============================================================================
# 1. eexec and Type 1 Tests
# ==============================================================================


def test_eexec_roundtrip_binary() -> None:
    plaintext = b"/FontName /TestFont def\n/Encoding StandardEncoding def\n"
    encrypted = eexec_encrypt(plaintext, key=55665, add_random=4)
    decrypted = eexec_decrypt(encrypted, key=55665, discard=4)
    assert decrypted == plaintext


def test_eexec_roundtrip_charstring_key() -> None:
    # CharStrings use key 4330
    cs_plain = b"\x8b\x8c\x0d"  # e.g., 0 1 hsbw
    encrypted = eexec_encrypt(cs_plain, key=4330, add_random=4)
    decrypted = eexec_decrypt(encrypted, key=4330, discard=4)
    assert decrypted == cs_plain


def test_eexec_hex_decoding() -> None:
    plaintext = b"Test eexec plain text message"
    binary_cipher = eexec_encrypt(plaintext, key=55665, add_random=4)
    # Convert cipher to ASCII hex with newlines
    hex_ascii = binary_cipher.hex().upper().encode("ascii")
    # Add newlines and spaces
    hex_formatted = b"\n".join([hex_ascii[i : i + 32] for i in range(0, len(hex_ascii), 32)]) + b"\n"

    decrypted = eexec_decrypt(hex_formatted, key=55665, discard=4)
    assert decrypted == plaintext


def test_type1_charstring_width_parser() -> None:
    # CharString: sbx=50 (189), wx=600, hsbw=13
    # 50 in Type 1: 50 + 139 = 189 (\xbd)
    # 600 in Type 1: (247-250) -> 600 - 108 = 492 = 1*256 + 236 -> b0 = 247 + 1 = 248 (\xf8), b1 = 236 (\xec)
    # 13: hsbw (\r)
    cs = bytes([189, 248, 236, 13])
    width = _parse_type1_charstring_width(cs)
    assert width == 600.0

    # 32-bit integer operand (255): 255 followed by 4-byte big-endian
    # sbx=0 (139), wx=750, hsbw=13
    cs_32 = b"\x8b\xff" + struct.pack(">i", 750) + b"\x0d"
    width_32 = _parse_type1_charstring_width(cs_32)
    assert width_32 == 750.0

    # sbw operator (12 7): sbx sby wx wy 12 7
    # sbx=0 (139), sby=0 (139), wx=500 (248 136), wy=0 (139), 12, 7
    # 500 - 108 = 392 = 1*256 + 136 -> b0 = 248, b1 = 136
    cs_sbw = bytes([139, 139, 248, 136, 139, 12, 7])
    width_sbw = _parse_type1_charstring_width(cs_sbw)
    assert width_sbw == 500.0


def test_unpack_pfb() -> None:
    # Record 1: ASCII (length 10)
    # Record 2: Binary (length 8)
    # Record 3: EOF
    r1_data = b"/FontName "
    r2_data = b"\x01\x02\x03\x04\x05\x06\x07\x08"

    pfb = (
        b"\x80\x01" + struct.pack("<I", len(r1_data)) + r1_data
        + b"\x80\x02" + struct.pack("<I", len(r2_data)) + r2_data
        + b"\x80\x03"
    )

    clean, l1, l2, l3 = unpack_pfb(pfb)
    assert clean == r1_data + r2_data
    assert l1 == len(r1_data)
    assert l2 == len(r2_data)

    # Non-PFB pass-through
    raw = b"Regular stream"
    clean_raw, rl1, rl2, rl3 = unpack_pfb(raw)
    assert clean_raw == raw
    assert rl1 == len(raw)


def test_type1_font_header_and_charstrings() -> None:
    # Construct a synthetic Type 1 font with ASCII header and encrypted eexec
    header = (
        b"%!FontType1-1.0: MyCustomType1 1.0\n"
        b"/FontName /CustomType1-Bold def\n"
        b"/FontBBox [-100 -200 1000 800] def\n"
        b"/FontMatrix [0.001 0 0 0.001 0 0] def\n"
        b"/ItalicAngle -14.5 def\n"
        b"/isFixedPitch false def\n"
        b"currentfile eexec\n"
    )

    # CharString for /A: sbx=0 (139), wx=650, hsbw=13
    # 650 - 108 = 542 = 2 * 256 + 30 -> 247 + 2 = 249, 30
    cs_a_plain = bytes([139, 249, 30, 13])
    cs_a_enc = eexec_encrypt(cs_a_plain, key=4330, add_random=4)

    # CharString for /.notdef: sbx=0, wx=250, hsbw=13
    # 250 in Type 1: 247 + 0 = 247, 250 - 108 = 142 -> 247, 142
    cs_notdef_plain = bytes([139, 247, 142, 13])
    cs_notdef_enc = eexec_encrypt(cs_notdef_plain, key=4330, add_random=4)

    eexec_body = (
        b"/CharStrings 2 dict dup begin\n"
        + b"/A " + str(len(cs_a_enc)).encode("ascii") + b" RD " + cs_a_enc + b" ND def\n"
        + b"/.notdef " + str(len(cs_notdef_enc)).encode("ascii") + b" RD " + cs_notdef_enc + b" ND def\n"
        + b"end\n"
    )

    encrypted_eexec = eexec_encrypt(eexec_body, key=55665, add_random=4)

    font_data = header + encrypted_eexec
    font = Type1Font(font_data, length1=len(header), length2=len(encrypted_eexec))

    assert font.name == "CustomType1-Bold"
    assert font.metrics.bbox == BoundingBox(x0=-100.0, y0=-200.0, x1=1000.0, y1=800.0)
    assert font.metrics.ascender == 800.0
    assert font.metrics.descender == -200.0
    assert font.metrics.italic_angle == -14.5
    assert font.metrics.is_italic is True
    assert font.metrics.is_monospace is False
    assert font.font_matrix == [0.001, 0.0, 0.0, 0.001, 0.0, 0.0]

    # Verify extracted glyph widths from CharStrings
    assert font.get_glyph_width("A") == 650.0
    assert font.get_glyph_width(".notdef") == 250.0
    assert font.metrics.default_width == 250.0
    assert font.get_glyph_width("NonExistent") == 250.0


# ==============================================================================
# 2. CFF Index and CFFFont Tests
# ==============================================================================


def test_cff_index_empty_and_build() -> None:
    # Empty index
    empty_bytes = struct.pack(">H", 0)
    empty_index, next_pos = CFFIndex.parse(empty_bytes, 0)
    assert len(empty_index) == 0
    assert next_pos == 2

    # Build and parse roundtrip
    items = [b"Apple", b"Banana", b"CherryPie", b"Date"]
    serialized = CFFIndex.build(items)
    index, end_pos = CFFIndex.parse(serialized, 0)
    assert len(index) == 4
    assert end_pos == len(serialized)
    assert index[0] == b"Apple"
    assert index[1] == b"Banana"
    assert index[2] == b"CherryPie"
    assert index[3] == b"Date"
    assert list(index) == items


def test_cff_font_parsing() -> None:
    # Construct synthetic CFF binary
    # Header: major=1, minor=0, hdr_size=4, off_size=1
    hdr = bytes([1, 0, 4, 1])

    # 1. Name INDEX: ["TestCFF"]
    name_idx = CFFIndex.build([b"TestCFF"])

    # 2. Top DICT operands:
    # FontBBox (5): -50 -150 1050 850
    # isFixedPitch (12, 1): 1
    # ItalicAngle (12, 2): -12.5 (BCD encoded real)
    # CharStrings (17): offset (computed)
    # Private (18): size, offset (computed)

    bbox_bytes = bytes([
        89,        # -50: 89 - 139 = -50
        251, 42,   # -150: -(251-251)*256 - 42 - 108 = -150
        250, 174,  # 1050: (250-247)*256 + 174 + 108 = 768 + 174 + 108 = 1050
        249, 230,  # 850: (249-247)*256 + 230 + 108 = 512 + 230 + 108 = 850
        5,         # operator 5: FontBBox
    ])

    fixed_pitch_bytes = bytes([
        140,       # 1 (140 - 139 = 1)
        12, 1,     # operator (12, 1): isFixedPitch
    ])

    # Italic angle: -12.5 encoded via BCD (30 ... FF)
    bcd_italic = bytes([30, 0xE1, 0x2A, 0x5F, 12, 2])

    # 3. String INDEX: empty
    string_idx = CFFIndex.build([])

    # 4. Global Subr INDEX: empty
    gsubr_idx = CFFIndex.build([])

    # Prepare CharStrings:
    # GID 0: nominalWidthX + 50 (width=550 if nominal=500), then endchar (14)
    # 50 in Type 2: 50 + 139 = 189
    cs0 = bytes([189, 14])
    # GID 1: default width (no width arg), endchar (14)
    cs1 = bytes([14])

    charstrings_idx = CFFIndex.build([cs0, cs1])

    # Private DICT:
    # defaultWidthX (20): 600 => (248-247)*256 + 236 + 108 = 600 => 248, 236, 20
    # nominalWidthX (21): 500 => (248-247)*256 + 136 + 108 = 500 => 248, 136, 21
    private_dict_bytes = bytes([248, 236, 20, 248, 136, 21])

    priv_size = len(private_dict_bytes)
    top_core = bbox_bytes + fixed_pitch_bytes + bcd_italic

    prefix = hdr + name_idx
    priv_dummy = bytes([29, 0, 0, 0, priv_size, 29, 0, 0, 0, 0, 18])
    cs_dummy = bytes([29, 0, 0, 0, 0, 17])
    top_dict_bytes = top_core + priv_dummy + cs_dummy
    top_idx = CFFIndex.build([top_dict_bytes])

    pos_after_gsubr = len(prefix) + len(top_idx) + len(string_idx) + len(gsubr_idx)
    priv_offset = pos_after_gsubr
    cs_offset = priv_offset + priv_size

    # Now write the real Top DICT
    priv_real = bytes([29]) + struct.pack(">i", priv_size) + bytes([29]) + struct.pack(">i", priv_offset) + bytes([18])
    cs_real = bytes([29]) + struct.pack(">i", cs_offset) + bytes([17])
    top_dict_real = top_core + priv_real + cs_real
    top_idx_real = CFFIndex.build([top_dict_real])

    full_cff = hdr + name_idx + top_idx_real + string_idx + gsubr_idx + private_dict_bytes + charstrings_idx

    cff_font = CFFFont(full_cff)

    assert cff_font.name == "TestCFF"
    assert cff_font.metrics.bbox == BoundingBox(x0=-50.0, y0=-150.0, x1=1050.0, y1=850.0)
    assert cff_font.metrics.is_monospace is True
    assert cff_font.metrics.is_italic is True
    assert cff_font.metrics.italic_angle == -12.5
    assert cff_font.default_width_x == 600.0
    assert cff_font.nominal_width_x == 500.0

    # CharStrings width verification:
    # GID 0: nominal 500 + 50 = 550
    assert cff_font.get_width(0) == 550.0
    # GID 1: default width = 600
    assert cff_font.get_width(1) == 600.0


# ==============================================================================
# 3. CompositeFont Tests
# ==============================================================================


def test_composite_font_width_arrays() -> None:
    # Test Format 1 and Format 2 mixed in /W array
    # Format 1: 10 [ 500 550 600 ] -> 10: 500, 11: 550, 12: 600
    # Format 2: 20 25 700          -> 20..25: 700
    w_array = PDFArray([
        10, PDFArray([500, 550, 600]),
        20, 25, 700,
    ])

    cid_dict = PDFDict({
        "Type": PDFName("Font"),
        "Subtype": PDFName("CIDFontType2"),
        "BaseFont": PDFName("TestCIDFont"),
        "DW": 1000,
        "W": w_array,
    })

    top_dict = PDFDict({
        "Type": PDFName("Font"),
        "Subtype": PDFName("Type0"),
        "BaseFont": PDFName("TestCIDFont-Identity"),
        "Encoding": PDFName("Identity-H"),
        "DescendantFonts": PDFArray([cid_dict]),
    })

    font = CompositeFont(top_dict)
    assert font.name == "TestCIDFont-Identity"
    assert font.is_vertical is False

    # Format 1 entries
    assert font.get_width(10) == 500.0
    assert font.get_width(11) == 550.0
    assert font.get_width(12) == 600.0

    # Format 2 entries
    for cid in range(20, 26):
        assert font.get_width(cid) == 700.0

    # Fallback to /DW
    assert font.get_width(99) == 1000.0


def test_composite_font_vertical_metrics() -> None:
    # Vertical font with /Identity-V, /DW2, and /W2
    # /DW2 [ vy w1y ] = [880 -1000]
    # /W2 format 1: 30 [ -900 250 850 ]
    # /W2 format 2: 40 42 -800 300 800
    w2_array = PDFArray([
        30, PDFArray([-900, 250, 850]),
        40, 42, -800, 300, 800,
    ])

    cid_dict = PDFDict({
        "Type": PDFName("Font"),
        "Subtype": PDFName("CIDFontType0"),
        "BaseFont": PDFName("KozMin-V"),
        "DW": 1000,
        "DW2": PDFArray([880, -1000]),
        "W2": w2_array,
    })

    top_dict = PDFDict({
        "Type": PDFName("Font"),
        "Subtype": PDFName("Type0"),
        "BaseFont": PDFName("KozMin-V"),
        "Encoding": PDFName("Identity-V"),
        "DescendantFonts": PDFArray([cid_dict]),
    })

    font = CompositeFont(top_dict)
    assert font.is_vertical is True

    # Format 1 vertical metrics: CID 30 -> (-900, 250, 850)
    assert font.get_vertical_metrics(30) == (-900.0, 250.0, 850.0)

    # Format 2 vertical metrics: CID 40..42 -> (-800, 300, 800)
    for cid in range(40, 43):
        assert font.get_vertical_metrics(cid) == (-800.0, 300.0, 800.0)

    # Fallback default vertical metrics:
    # default w0 = 1000, vx = 500, vy = 880, w1y = -1000
    assert font.get_vertical_metrics(999) == (-1000.0, 500.0, 880.0)


def test_composite_font_cid_to_gid_map() -> None:
    # Stream containing 2-byte GIDs
    # CID 0 -> GID 10, CID 1 -> GID 20, CID 2 -> GID 30
    gids = struct.pack(">HHH", 10, 20, 30)
    stream = PDFStream(dict=PDFDict({"Length": len(gids)}), data=memoryview(gids))

    cid_dict = PDFDict({
        "Type": PDFName("Font"),
        "Subtype": PDFName("CIDFontType2"),
        "BaseFont": PDFName("TTFont"),
        "CIDToGIDMap": stream,
    })

    top_dict = PDFDict({
        "Type": PDFName("Font"),
        "Subtype": PDFName("Type0"),
        "BaseFont": PDFName("TTFont"),
        "DescendantFonts": PDFArray([cid_dict]),
    })

    font = CompositeFont(top_dict)
    assert font.cid_to_gid(0) == 10
    assert font.cid_to_gid(1) == 20
    assert font.cid_to_gid(2) == 30
    assert font.cid_to_gid(3) == 0  # Out of range fallback


def test_composite_font_descriptor_metrics() -> None:
    fd_dict = PDFDict({
        "Type": PDFName("FontDescriptor"),
        "FontName": PDFName("DescribedFont"),
        "Ascent": 750,
        "Descent": -220,
        "CapHeight": 680,
        "ItalicAngle": -11.0,
        "Flags": 65,  # Bit 1 (FixedPitch=1) + Bit 7 (Italic=64) = 65
        "FontBBox": PDFArray([-120, -250, 1020, 890]),
    })

    cid_dict = PDFDict({
        "Type": PDFName("Font"),
        "Subtype": PDFName("CIDFontType0"),
        "BaseFont": PDFName("DescribedFont"),
        "FontDescriptor": fd_dict,
    })

    top_dict = PDFDict({
        "Type": PDFName("Font"),
        "Subtype": PDFName("Type0"),
        "BaseFont": PDFName("DescribedFont"),
        "DescendantFonts": PDFArray([cid_dict]),
    })

    font = CompositeFont(top_dict)
    assert font.metrics.ascender == 750.0
    assert font.metrics.descender == -220.0
    assert font.metrics.cap_height == 680.0
    assert font.metrics.italic_angle == -11.0
    assert font.metrics.is_italic is True
    assert font.metrics.is_monospace is True
    assert font.metrics.bbox == BoundingBox(x0=-120.0, y0=-250.0, x1=1020.0, y1=890.0)
