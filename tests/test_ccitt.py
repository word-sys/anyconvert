"""Tests for CCITT Group 3 and Group 4 Fax decompression filter."""

from __future__ import annotations

import io
import unittest

from anyconvert.pdf.filters import ccitt_decode, decode_stream
from anyconvert.pdf.filters.ccitt import (
    _build_tree,
    _decode_1d_row,
    _decode_2d_row,
    _pack_bits_to_row,
    _CCITTBitReader,
)
from anyconvert.pdf.graphics.image import PDFImage
from anyconvert.pdf.parser import PDFArray, PDFDict, PDFName, PDFStream


class TestCCITTFaxFilter(unittest.TestCase):
    """Unit tests for pure-Python CCITT Group 3 and Group 4 facsimile decoder."""

    def test_bit_reader_basic(self) -> None:
        """Verify MSB-first bit reading and byte alignment."""
        # 0xA5 = 10100101, 0x3C = 00111100
        reader = _CCITTBitReader(b"\xA5\x3C")
        bits = [reader.read_bit() for _ in range(8)]
        self.assertEqual(bits, [1, 0, 1, 0, 0, 1, 0, 1])

        # Read 3 bits of second byte (001)
        self.assertEqual([reader.read_bit() for _ in range(3)], [0, 0, 1])
        # Align to byte boundary
        reader.align_to_byte()
        self.assertTrue(reader.is_eof)
        # Reading past EOF returns 0 without raising
        self.assertEqual(reader.read_bit(), 0)

    def test_pack_bits_to_row(self) -> None:
        """Verify bit packing into byte rows with BlackIs1 inversion."""
        bits = [1, 1, 1, 1, 0, 0, 0, 0]  # White(1), Black(0)
        # Default BlackIs1=False -> White=1, Black=0 -> 11110000 = 0xF0
        row_normal = _pack_bits_to_row(bits, 8, black_is_1=False)
        self.assertEqual(row_normal, b"\xF0")

        # BlackIs1=True -> White=0, Black=1 -> 00001111 = 0x0F
        row_inverted = _pack_bits_to_row(bits, 8, black_is_1=True)
        self.assertEqual(row_inverted, b"\x0F")

    def test_g3_1d_all_white_row(self) -> None:
        """Verify 1D MH decoding of a solid white scanline."""
        # 16 white pixels: White terminating code for 16 is '101010'
        # Bitstream: 10101000 = 0xA8
        data = bytes([0xA8])
        decoded = ccitt_decode(data, params={"K": 0, "Columns": 16, "Rows": 1})
        # 16 white pixels in PDF (BlackIs1=False) is 0xFF, 0xFF
        self.assertEqual(decoded, b"\xFF\xFF")

    def test_g3_1d_all_black_row(self) -> None:
        """Verify 1D MH decoding of a solid black scanline."""
        # Scanlines must start with a White run.
        # Run 0 White: '00110101'
        # Run 8 Black: '000101'
        # Total bits: 00110101 00010100 (14 bits padded to 16) -> 0x35, 0x14
        data = bytes([0x35, 0x14])
        decoded = ccitt_decode(data, params={"K": 0, "Columns": 8, "Rows": 1})
        # 8 black pixels in PDF (BlackIs1=False) is 0x00
        self.assertEqual(decoded, b"\x00")

    def test_g3_1d_mixed_runs(self) -> None:
        """Verify 1D MH decoding with alternating White and Black runs."""
        # Width: 10 pixels. White 4, Black 3, White 3.
        # White 4: '1011'
        # Black 3: '10'
        # White 3: '1000'
        # Combined: 10111010 00000000 -> 0xBA, 0x00
        data = bytes([0xBA, 0x00])
        decoded = ccitt_decode(data, params={"K": 0, "Columns": 10, "Rows": 1})
        # 10 pixels: 1 1 1 1 0 0 0 1 1 1 -> 11110001 11000000 -> 0xF1, 0xC0
        self.assertEqual(decoded, b"\xF1\xC0")

    def test_g3_1d_makeup_codes(self) -> None:
        """Verify 1D MH decoding of runs requiring make-up codes (>= 64 pixels)."""
        # Run 68 White: Make-up 64 ('11011') + Terminating 4 ('1011') -> '110111011' (9 bits)
        # Padded to 16 bits: 11011101 10000000 -> 0xDD, 0x80
        data = bytes([0xDD, 0x80])
        decoded = ccitt_decode(data, params={"K": 0, "Columns": 68, "Rows": 1})
        self.assertEqual(len(decoded), 9)  # (68 + 7) // 8 = 9 bytes
        # 68 bits of 1s: 8 full bytes of 0xFF, and 9th byte 11110000 (0xF0)
        expected = b"\xFF" * 8 + b"\xF0"
        self.assertEqual(decoded, expected)

    def test_g4_vertical_v0_repetition(self) -> None:
        """Verify Group 4 V(0) relative vertical mode decoding."""
        # Width: 8.
        # First row reference is all-white.
        # Coding line: V(0) ('1') matches the first transition on refline (at index 8 / width).
        # So row 1 is all-white.
        # Row 2: V(0) ('1') matches refline row 1 (all white).
        # Row 3: V(0) ('1').
        # Bitstream: '111' padded to 1 byte: 11100000 = 0xE0
        data = bytes([0xE0])
        decoded = ccitt_decode(data, params={"K": -1, "Columns": 8, "Rows": 3})
        self.assertEqual(decoded, b"\xFF\xFF\xFF")

    def test_g4_horizontal_mode(self) -> None:
        """Verify Group 4 Horizontal mode decoding."""
        # Row 1: Horizontal Mode '001', followed by White 4 ('1011') and Black 4 ('011').
        # Bits: 001 1011 011 = 00110110 11000000 -> 0x36, 0xC0
        data = bytes([0x36, 0xC0])
        decoded = ccitt_decode(data, params={"K": -1, "Columns": 8, "Rows": 1})
        # 4 white (1111), 4 black (0000) -> 0xF0
        self.assertEqual(decoded, b"\xF0")

    def test_g4_pass_mode_and_vertical(self) -> None:
        """Verify Group 4 Pass Mode and Vertical offset transitions."""
        # Row 1: Horizontal (White 4, Black 4) -> 001 1011 011 (10 bits)
        # Row 2: Two V(0) codes ('11') copy the two transitions from Row 1
        # Combined bits: '0011011011' + '11' = 00110110 11110000 -> 0x36, 0xF0
        data = bytes([0x36, 0xF0])
        decoded = ccitt_decode(data, params={"K": -1, "Columns": 8, "Rows": 2})
        self.assertEqual(decoded, b"\xF0\xF0")

    def test_g4_encoded_byte_align(self) -> None:
        """Verify Group 4 with EncodedByteAlign=True."""
        # Each row bitstream starts on a byte boundary.
        # Row 1: V(0) ('1') -> Byte 0: 0x80 (10000000)
        # Row 2: V(0) ('1') -> Byte 1: 0x80 (10000000)
        data = bytes([0x80, 0x80])
        decoded = ccitt_decode(
            data,
            params={"K": -1, "Columns": 8, "Rows": 2, "EncodedByteAlign": True},
        )
        self.assertEqual(decoded, b"\xFF\xFF")

    def test_decode_stream_dispatcher_ccitt(self) -> None:
        """Verify decode_stream dispatcher recognizes CCITTFaxDecode filter names."""
        data = bytes([0xA8])  # 16 white pixels
        params = PDFDict({"K": 0, "Columns": 16, "Rows": 1})

        # Test full filter name
        res1 = decode_stream(data, filter_spec=PDFName("CCITTFaxDecode"), params_spec=params)
        self.assertEqual(res1, b"\xFF\xFF")

        # Test abbreviation /CCF
        res2 = decode_stream(data, filter_spec="/CCF", params_spec=params)
        self.assertEqual(res2, b"\xFF\xFF")

    def test_pdf_image_xobject_integration(self) -> None:
        """Verify end-to-end PDFImage extraction from a CCITTFaxDecode stream."""
        # 8x2 bilevel image:
        # Row 1: All White (V0 '1')
        # Row 2: All White (V0 '1')
        # CCITT bitstream: 0xC0
        ccitt_data = bytes([0xC0])
        img_dict = PDFDict({
            "Type": PDFName("XObject"),
            "Subtype": PDFName("Image"),
            "Width": 8,
            "Height": 2,
            "BitsPerComponent": 1,
            "ColorSpace": PDFName("DeviceGray"),
            "Filter": PDFName("CCITTFaxDecode"),
            "DecodeParms": PDFDict({"K": -1, "Columns": 8, "Rows": 2}),
        })
        stream = PDFStream(img_dict, memoryview(ccitt_data))
        pdf_image = PDFImage.from_stream(stream)

        self.assertEqual(pdf_image.width, 8)
        self.assertEqual(pdf_image.height, 2)
        self.assertEqual(pdf_image.format, "png")
        self.assertEqual(len(pdf_image.rgba_pixels), 8 * 2 * 4)  # 16 pixels * 4 bytes RGBA

        # Output PNG serialization
        png_bytes = pdf_image.to_png()
        self.assertTrue(png_bytes.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_corrupt_stream_resilience(self) -> None:
        """Verify decoder gracefully handles empty or truncated streams without crashing."""
        self.assertEqual(ccitt_decode(b""), b"")

        # Truncated data with Rows=4: should pad with blank rows
        data = bytes([0x80])
        decoded = ccitt_decode(data, params={"K": -1, "Columns": 8, "Rows": 4})
        self.assertEqual(len(decoded), 4)  # 4 rows * 1 byte per row


if __name__ == "__main__":
    unittest.main()
