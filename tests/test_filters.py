"""Unit tests for Phase 7: Stream Decompression Filter Pipeline."""

from __future__ import annotations

import struct
import unittest
import zlib

from anyconvert.exceptions import PDFSyntaxError, PDFUnsupportedFilterError
from anyconvert.pdf.filters.ascii import ascii_85_decode, ascii_hex_decode
from anyconvert.pdf.filters.flate import flate_decode
from anyconvert.pdf.filters.lzw import lzw_decode
from anyconvert.pdf.filters.runlength import run_length_decode
from anyconvert.pdf.filters import decode_stream
from anyconvert.pdf.parser import PDFArray, PDFDict, PDFName


class TestASCIIFilters(unittest.TestCase):
    """Tests for ASCIIHexDecode and ASCII85Decode."""

    def test_ascii_hex_decode(self) -> None:
        # Standard
        self.assertEqual(ascii_hex_decode(b"48656C6C6F>"), b"Hello")
        # With whitespace and lowercase
        self.assertEqual(ascii_hex_decode(b" 48 65 6c 6c 6f >"), b"Hello")
        # Odd-nibble auto-padding with 0
        self.assertEqual(ascii_hex_decode(b"48656c6c6>"), b"Hell\x60")
        # Invalid character
        with self.assertRaises(PDFSyntaxError):
            ascii_hex_decode(b"48656Z>")

    def test_ascii_85_decode(self) -> None:
        # Standard string: "Hello world!" -> "87cURD]j7BEbo80"
        encoded = b"<~87cURD]j7BEbo80~>"
        self.assertEqual(ascii_85_decode(encoded), b"Hello world!")

        # Zero group 'z'
        self.assertEqual(ascii_85_decode(b"<~z~>"), b"\x00\x00\x00\x00")
        self.assertEqual(ascii_85_decode(b"<~87cURz~>"), b"Hell\x00\x00\x00\x00")

        # Whitespace inside ASCII85
        self.assertEqual(ascii_85_decode(b"<~ 87 cU RD ]j 7B Eb o8 0 ~>"), b"Hello world!")

        # Invalid characters (characters above 'u' like 'v', 'w', 'x', 'y')
        with self.assertRaises(PDFSyntaxError):
            ascii_85_decode(b"<~vwxyz~>")


class TestRunLengthDecode(unittest.TestCase):
    """Tests for PackBits (RunLengthDecode)."""

    def test_run_length_decode(self) -> None:
        # Literal run of 5 bytes (length_byte = 4): "Hello"
        # Repeated run of 4 spaces (length_byte = 257 - 4 = 253 = 0xFD): "    "
        # Literal run of 5 bytes: "World"
        # EOD: 128 (0x80)
        data = bytes([4]) + b"Hello" + bytes([0xFD, ord(" "), 4]) + b"World" + bytes([128])
        decoded = run_length_decode(data)
        self.assertEqual(decoded, b"Hello    World")

        # Truncated or empty
        self.assertEqual(run_length_decode(b""), b"")
        self.assertEqual(run_length_decode(bytes([128])), b"")


class TestLZWDecode(unittest.TestCase):
    """Tests for LZWDecode state machine."""

    def test_lzw_decode_basic(self) -> None:
        # Construct synthetic LZW stream with ClearTable (256) and EOD (257)
        # Sequence of characters: 'A', 'B', 'A', 'B', 'A'
        # 9-bit codes:
        # 256 (Clear)
        # 65 ('A')
        # 66 ('B')
        # 258 ('AB')
        # 65 ('A')
        # 257 (EOD)
        codes = [256, 65, 66, 258, 65, 257]
        # Pack 9-bit codes into bytes (MSB first)
        packed = bytearray()
        acc = 0
        bits = 0
        for code in codes:
            acc = (acc << 9) | code
            bits += 9
            while bits >= 8:
                bits -= 8
                packed.append((acc >> bits) & 0xFF)
        if bits > 0:
            packed.append((acc << (8 - bits)) & 0xFF)

        decoded = lzw_decode(bytes(packed), early_change=1)
        self.assertEqual(decoded, b"ABABA")


class TestFlateDecodeAndPredictors(unittest.TestCase):
    """Tests for FlateDecode and TIFF/PNG row predictor reversals."""

    def test_flate_plain(self) -> None:
        raw = b"Uncompressed plain text stream payload."
        compressed = zlib.compress(raw)
        self.assertEqual(flate_decode(compressed), raw)

    def test_tiff_predictor_8bit(self) -> None:
        # 2 rows of RGB (colors=3, bpc=8, columns=2)
        # Row 1 original: [10, 20, 30,  15, 25, 35]
        # Row 1 diffed:   [10, 20, 30,   5,  5,  5]
        # Row 2 original: [100, 110, 120,  120, 115, 125]
        # Row 2 diffed:   [100, 110, 120,   20,   5,   5]
        diffed = bytes([
            10, 20, 30, 5, 5, 5,
            100, 110, 120, 20, 5, 5,
        ])
        expected = bytes([
            10, 20, 30, 15, 25, 35,
            100, 110, 120, 120, 115, 125,
        ])
        compressed = zlib.compress(diffed)
        params = PDFDict({
            "Predictor": 2,
            "Columns": 2,
            "Colors": 3,
            "BitsPerComponent": 8,
        })
        decompressed = flate_decode(compressed, params=params)
        self.assertEqual(decompressed, expected)

    def test_tiff_predictor_16bit(self) -> None:
        # 1 row of 2 16-bit samples (colors=1, bpc=16, columns=2)
        # Sample 1: 1000 (0x03E8)
        # Sample 2: 1500 (0x05DC) -> diff = 500 (0x01F4)
        diffed = struct.pack(">HH", 1000, 500)
        expected = struct.pack(">HH", 1000, 1500)
        compressed = zlib.compress(diffed)
        params = PDFDict({
            "Predictor": 2,
            "Columns": 2,
            "Colors": 1,
            "BitsPerComponent": 16,
        })
        self.assertEqual(flate_decode(compressed, params=params), expected)

    def test_png_predictors(self) -> None:
        # Row 1: filter 1 (Sub), deltas [10, 20,  5, 5] -> [10, 20, 15, 25] (bpp=2)
        # Row 2: filter 2 (Up), deltas  [1,  2,   3, 4] -> [11, 22, 18, 29]
        # Row 3: filter 3 (Avg), deltas [0,  0,   0, 0]
        # Row 4: filter 4 (Paeth)
        row1_diff = bytes([1, 10, 20, 5, 5])
        row2_diff = bytes([2, 1, 2, 3, 4])
        data = row1_diff + row2_diff
        compressed = zlib.compress(data)

        params = PDFDict({
            "Predictor": 15,
            "Columns": 2,
            "Colors": 2,
            "BitsPerComponent": 8,
        })
        res = flate_decode(compressed, params=params)
        expected_row1 = bytes([10, 20, 15, 25])
        expected_row2 = bytes([11, 22, 18, 29])
        self.assertEqual(res, expected_row1 + expected_row2)


class TestFilterPipeline(unittest.TestCase):
    """Tests for multi-stage filter pipeline dispatcher."""

    def test_pipeline_dispatch(self) -> None:
        raw_text = b"Confidential document stream pipeline content."

        # Stage 1: Compress with Flate
        step1 = zlib.compress(raw_text)

        # Stage 2: Encode with ASCII85
        # We can test decode_stream on both stages in sequence
        # Using PDFArray of filters: [/ASCIIHexDecode, /FlateDecode]
        step2_hex = step1.hex().encode("ascii") + b">"

        decoded = decode_stream(
            step2_hex,
            filter_spec=PDFArray([PDFName("ASCIIHexDecode"), PDFName("FlateDecode")]),
        )
        self.assertEqual(decoded, raw_text)

    def test_filter_abbreviations(self) -> None:
        raw = b"Sample vector"
        comp = zlib.compress(raw)
        self.assertEqual(decode_stream(comp, "/Fl"), raw)
        self.assertEqual(decode_stream(comp, "FlateDecode"), raw)

    def test_unsupported_filter(self) -> None:
        with self.assertRaises(PDFUnsupportedFilterError):
            decode_stream(b"data", "/UnknownFilter123")


if __name__ == "__main__":
    unittest.main()
