"""Unit tests for Phase 8: SFNT, OpenType, and TrueType font parsing."""

from __future__ import annotations

import struct
import unittest

from anyconvert.exceptions import PDFFontError
from anyconvert.pdf.typography.font import BaseFont, FontMetrics
from anyconvert.pdf.typography.sfnt import SFNTFont


def build_synthetic_sfnt(
    units_per_em: int = 2048,
    ascender: int = 1600,
    descender: int = -400,
    glyph_widths: list[int] | None = None,
) -> bytes:
    """Construct a minimal valid binary TrueType SFNT container for testing."""
    if glyph_widths is None:
        glyph_widths = [1024, 1200, 800]  # Glyph 0 (missing), Glyph 1 ('A'), Glyph 2 ('B')

    num_glyphs = len(glyph_widths)

    # 1. 'head' table (54 bytes)
    head_table = bytearray(54)
    struct.pack_into(">H", head_table, 18, units_per_em)
    struct.pack_into(">hhhh", head_table, 36, -100, -200, 1500, 1800)  # xMin, yMin, xMax, yMax

    # 2. 'maxp' table (32 bytes)
    maxp_table = bytearray(32)
    struct.pack_into(">H", maxp_table, 4, num_glyphs)

    # 3. 'hhea' table (36 bytes)
    hhea_table = bytearray(36)
    struct.pack_into(">hh", hhea_table, 4, ascender, descender)
    struct.pack_into(">H", hhea_table, 34, num_glyphs)  # numberOfHMetrics

    # 4. 'hmtx' table (4 bytes per metric: advanceWidth, lsb)
    hmtx_table = bytearray()
    for w in glyph_widths:
        hmtx_table.extend(struct.pack(">Hh", w, 0))

    # 5. 'cmap' table with Format 4 subtable
    # Map 'A' (65) -> Glyph 1, 'B' (66) -> Glyph 2
    # segCount = 2 (Segment 1: [65, 66], Segment 2: [0xFFFF, 0xFFFF])
    # Format 4 header: format=4, length=32, language=0, segCountX2=4, searchRange=4, entrySelector=1, rangeShift=0
    seg_count = 2
    fmt4_data = bytearray()
    fmt4_data.extend(struct.pack(">HHHHHH", 4, 32, 0, 4, 4, 1))
    fmt4_data.extend(struct.pack(">H", 0))  # rangeShift
    fmt4_data.extend(struct.pack(">2H", 66, 0xFFFF))  # endCodes
    fmt4_data.extend(struct.pack(">H", 0))  # reservedPad
    fmt4_data.extend(struct.pack(">2H", 65, 0xFFFF))  # startCodes
    fmt4_data.extend(struct.pack(">2h", -64, 1))  # idDeltas (65 + (-64) = 1, 66 + (-64) = 2)
    fmt4_data.extend(struct.pack(">2H", 0, 0))  # idRangeOffsets

    # CMAP parent table: version=0, numSubtables=1, (platform 3, encoding 1, offset 12)
    cmap_table = bytearray()
    cmap_table.extend(struct.pack(">HH", 0, 1))
    cmap_table.extend(struct.pack(">HHI", 3, 1, 12))  # Subtable record
    cmap_table.extend(fmt4_data)

    # 6. 'OS/2' table (optional, 96 bytes)
    os2_table = bytearray(96)
    struct.pack_into(">H", os2_table, 4, 700)  # usWeightClass = 700 (Bold)
    struct.pack_into(">H", os2_table, 62, 0x21)  # fsSelection = Bold (0x20) + Italic (0x01)
    struct.pack_into(">hh", os2_table, 86, 500, 700)  # sxHeight, sCapHeight

    tables = [
        (b"OS/2", bytes(os2_table)),
        (b"cmap", bytes(cmap_table)),
        (b"head", bytes(head_table)),
        (b"hhea", bytes(hhea_table)),
        (b"hmtx", bytes(hmtx_table)),
        (b"maxp", bytes(maxp_table)),
    ]

    # SFNT header: sfnt_version (0x00010000), num_tables (6), searchRange, entrySelector, rangeShift
    num_tables = len(tables)
    header = struct.pack(">I4H", 0x00010000, num_tables, 64, 2, 32)

    # Calculate offsets
    dir_size = 12 + num_tables * 16
    curr_offset = dir_size
    records = bytearray()
    payload = bytearray()

    for tag, tbl_bytes in tables:
        records.extend(struct.pack(">4sIII", tag, 0, curr_offset, len(tbl_bytes)))
        payload.extend(tbl_bytes)
        curr_offset += len(tbl_bytes)

    return header + records + payload


class TestSFNTFont(unittest.TestCase):
    """Tests for TrueType / OpenType SFNT font parser."""

    def test_base_font_and_metrics(self) -> None:
        metrics = FontMetrics(ascender=750.0, descender=-250.0)
        base = BaseFont(name="TestFont", metrics=metrics, widths={65: 600.0})
        self.assertEqual(base.get_width(65), 600.0)
        self.assertEqual(base.get_width(66), 500.0)  # Default width
        self.assertEqual(base.to_unicode(65), "A")
        self.assertEqual(base.to_unicode(1000), "\ufffd")

    def test_synthetic_sfnt_parsing(self) -> None:
        sfnt_bytes = build_synthetic_sfnt(
            units_per_em=2048,
            ascender=1600,
            descender=-400,
            glyph_widths=[1024, 1200, 800],
        )
        font = SFNTFont(sfnt_bytes, name="SyntheticTrueType")

        # Units per em
        self.assertEqual(font.metrics.units_per_em, 2048)

        # Scale factor = 1000 / 2048 = 0.48828125
        # Normalized ascender: 1600 * 0.48828125 = 781.25
        self.assertAlmostEqual(font.metrics.ascender, 781.25)
        # Normalized descender: -400 * 0.48828125 = -195.3125
        self.assertAlmostEqual(font.metrics.descender, -195.3125)

        # Bounding box
        self.assertIsNotNone(font.metrics.bbox)
        assert font.metrics.bbox is not None
        self.assertAlmostEqual(font.metrics.bbox.x0, -100 * (1000.0 / 2048.0))

        # Check cmap resolution: 'A' (65) -> Glyph 1, 'B' (66) -> Glyph 2
        self.assertEqual(font.get_glyph_id(65), 1)
        self.assertEqual(font.get_glyph_id(66), 2)
        self.assertIsNone(font.get_glyph_id(67))

        # Check advance width resolution:
        # Glyph 1 width: 1200 * (1000 / 2048) = 585.9375
        # Glyph 2 width: 800 * (1000 / 2048) = 390.625
        self.assertAlmostEqual(font.get_width(65), 585.9375)
        self.assertAlmostEqual(font.get_width(66), 390.625)

        # OS/2 flags
        self.assertTrue(font.metrics.is_bold)
        self.assertTrue(font.metrics.is_italic)

    def test_truncated_sfnt_raises(self) -> None:
        with self.assertRaises(PDFFontError):
            SFNTFont(b"\x00\x01\x00\x00")


if __name__ == "__main__":
    unittest.main()
