"""Tests for JBIG2 segment header parser and decompression filter."""

from __future__ import annotations

import struct
import unittest

from anyconvert.pdf.filters import decode_stream, jbig2_decode
from anyconvert.pdf.filters.jbig2 import (
    JBIG2_FILE_HEADER_MAGIC,
    JBIG2Segment,
    JBIG2StreamParser,
    SEG_TYPE_END_OF_FILE,
    SEG_TYPE_END_OF_PAGE,
    SEG_TYPE_IMMEDIATE_GENERIC_REGION,
    SEG_TYPE_PAGE_INFO,
    SEG_TYPE_SYMBOL_DICT,
)
from anyconvert.pdf.graphics.image import PDFImage
from anyconvert.pdf.parser import PDFDict, PDFName, PDFStream


def _build_test_jbig2_stream(
    width: int = 8,
    height: int = 2,
    use_mmr: bool = True,
    include_file_header: bool = False,
) -> bytes:
    """Helper to build a synthetic JBIG2 bitstream for unit testing."""
    parts: list[bytes] = []

    if include_file_header:
        # 8 bytes magic + 1 byte flags (0 = page count known) + 4 bytes page count (1)
        parts.append(JBIG2_FILE_HEADER_MAGIC + b"\x00\x00\x00\x00\x01")

    # Segment 0: Page Information (Type 48)
    # seg_num=0, flags=48, ref_byte=0, page=1, len=19
    seg0_header = struct.pack(">IBBBI", 0, SEG_TYPE_PAGE_INFO, 0, 1, 19)
    seg0_data = struct.pack(">IIIIBH", width, height, 0, 0, 0, 0)
    parts.append(seg0_header + seg0_data)

    if use_mmr:
        # Segment 1: Immediate Generic Region (Type 38) with MMR=1
        # G4 data for width=8, height=2 (all-white): 0xC0
        g4_payload = b"\xC0"
        reg_header = struct.pack(">IIiiBB", width, height, 0, 0, 0, 1)
        seg1_payload = reg_header + g4_payload
        seg1_header = struct.pack(
            ">IBBBI", 1, SEG_TYPE_IMMEDIATE_GENERIC_REGION, 0, 1, len(seg1_payload)
        )
        parts.append(seg1_header + seg1_payload)
    else:
        # Segment 1: Symbol dictionary or arithmetic coded region (placeholder)
        seg1_payload = b"\x00" * 16
        seg1_header = struct.pack(
            ">IBBBI", 1, SEG_TYPE_SYMBOL_DICT, 0, 1, len(seg1_payload)
        )
        parts.append(seg1_header + seg1_payload)

    # Segment 2: End of Page (Type 49)
    parts.append(struct.pack(">IBBBI", 2, SEG_TYPE_END_OF_PAGE, 0, 1, 0))

    # Segment 3: End of File (Type 62)
    parts.append(struct.pack(">IBBBI", 3, SEG_TYPE_END_OF_FILE, 0, 1, 0))

    return b"".join(parts)


class TestJBIG2Filter(unittest.TestCase):
    """Unit tests for pure-Python JBIG2 stream parser and decompression filter."""

    def test_parser_standalone_file_header(self) -> None:
        """Verify parser correctly detects and skips standalone .jb2 file headers."""
        data = _build_test_jbig2_stream(width=16, height=4, include_file_header=True)
        parser = JBIG2StreamParser(data)
        segments = parser.parse_all()

        self.assertGreaterEqual(len(segments), 3)
        self.assertEqual(parser.page_width, 16)
        self.assertEqual(parser.page_height, 4)
        self.assertEqual(segments[0].seg_type, SEG_TYPE_PAGE_INFO)

    def test_parser_embedded_stream_segments(self) -> None:
        """Verify segment metadata extraction from an embedded PDF JBIG2 stream."""
        data = _build_test_jbig2_stream(width=8, height=2, include_file_header=False)
        parser = JBIG2StreamParser(data)
        segments = parser.parse_all()

        self.assertEqual(len(segments), 4)
        self.assertEqual(segments[0].seg_num, 0)
        self.assertEqual(segments[0].seg_type, SEG_TYPE_PAGE_INFO)
        self.assertEqual(segments[0].page, 1)

        self.assertEqual(segments[1].seg_num, 1)
        self.assertEqual(segments[1].seg_type, SEG_TYPE_IMMEDIATE_GENERIC_REGION)

        self.assertEqual(segments[2].seg_type, SEG_TYPE_END_OF_PAGE)
        self.assertEqual(segments[3].seg_type, SEG_TYPE_END_OF_FILE)

    def test_mmr_generic_region_decoding(self) -> None:
        """Verify MMR-encoded generic regions decode cleanly via CCITT Group 4."""
        data = _build_test_jbig2_stream(width=8, height=2, use_mmr=True)
        decoded = jbig2_decode(data)

        # 8 pixels wide, 2 rows of white -> 2 bytes of 0xFF
        self.assertEqual(decoded, b"\xFF\xFF")

    def test_arithmetic_coding_dimensional_fallback(self) -> None:
        """Verify graceful dimensional fallback for arithmetic coding segments."""
        data = _build_test_jbig2_stream(width=16, height=2, use_mmr=False)
        decoded = jbig2_decode(data)

        # 16 pixels wide = 2 bytes per row * 2 rows = 4 bytes of white scanline (0xFF)
        self.assertEqual(len(decoded), 4)
        self.assertEqual(decoded, b"\xFF\xFF\xFF\xFF")

    def test_fallback_dimensions_from_decode_parms(self) -> None:
        """Verify fallback dimensions can be supplied via DecodeParms."""
        # Minimal empty stream with no page info
        data = b"\x00\x00\x00\x01\x00\x00\x01\x00\x00\x00\x00"
        params = {"Width": 24, "Height": 3}
        decoded = jbig2_decode(data, params=params)

        # 24 pixels wide = 3 bytes per row * 3 rows = 9 bytes
        self.assertEqual(len(decoded), 9)

    def test_jbig2_globals_handling(self) -> None:
        """Verify /JBIG2Globals parameter stream is parsed before main stream."""
        # Create global symbol dictionary segment
        global_seg = struct.pack(">IBBBI", 0, SEG_TYPE_SYMBOL_DICT, 0, 0, 8) + b"\x00" * 8
        global_stream = PDFStream(PDFDict({}), memoryview(global_seg))

        main_data = _build_test_jbig2_stream(width=8, height=2, use_mmr=True)
        params = PDFDict({"JBIG2Globals": global_stream})

        decoded = jbig2_decode(main_data, params=params)
        self.assertEqual(decoded, b"\xFF\xFF")

    def test_decode_stream_dispatcher_jbig2(self) -> None:
        """Verify decode_stream routes /JBIG2Decode and /JBIG2 to jbig2_decode."""
        data = _build_test_jbig2_stream(width=8, height=2, use_mmr=True)

        res1 = decode_stream(data, filter_spec=PDFName("JBIG2Decode"))
        self.assertEqual(res1, b"\xFF\xFF")

        res2 = decode_stream(data, filter_spec="/JBIG2")
        self.assertEqual(res2, b"\xFF\xFF")

    def test_pdf_image_xobject_integration(self) -> None:
        """Verify end-to-end PDFImage extraction from a JBIG2Decode stream."""
        jbig2_data = _build_test_jbig2_stream(width=8, height=2, use_mmr=True)
        img_dict = PDFDict({
            "Type": PDFName("XObject"),
            "Subtype": PDFName("Image"),
            "Width": 8,
            "Height": 2,
            "BitsPerComponent": 1,
            "ColorSpace": PDFName("DeviceGray"),
            "Filter": PDFName("JBIG2Decode"),
        })
        stream = PDFStream(img_dict, memoryview(jbig2_data))
        pdf_image = PDFImage.from_stream(stream)

        self.assertEqual(pdf_image.width, 8)
        self.assertEqual(pdf_image.height, 2)
        self.assertEqual(pdf_image.format, "png")
        self.assertEqual(len(pdf_image.rgba_pixels), 8 * 2 * 4)

        png_data = pdf_image.to_png()
        self.assertTrue(png_data.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_empty_and_corrupt_stream_resilience(self) -> None:
        """Verify empty or corrupt JBIG2 streams return gracefully without crashing."""
        self.assertEqual(jbig2_decode(b""), b"")

        # Corrupted stream with dimensions provided
        corrupt = b"\xFF\xFF\x00\x12\x34"
        decoded = jbig2_decode(corrupt, params={"Width": 8, "Height": 2})
        self.assertEqual(len(decoded), 2)  # 2 rows * 1 byte


if __name__ == "__main__":
    unittest.main()
