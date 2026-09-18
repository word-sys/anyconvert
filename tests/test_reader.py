"""Test suite for Phase 3: Zero-Copy Binary Memory Reader & Bit Stream Tools."""

from __future__ import annotations

import io
import struct
import unittest

from anyconvert.common.reader import (
    BitReader,
    ByteReader,
    PDF_DELIMITERS,
    PDF_WHITESPACE,
)


class TestByteReader(unittest.TestCase):
    """Test memoryview-backed zero-copy ByteReader operations."""

    def test_initialization_types(self) -> None:
        raw = b"Hello, AnyConvert!"
        r_bytes = ByteReader(raw)
        r_bytearray = ByteReader(bytearray(raw))
        r_mv = ByteReader(memoryview(raw))
        r_sub = ByteReader(r_bytes)

        self.assertEqual(len(r_bytes), len(raw))
        self.assertEqual(len(r_bytearray), len(raw))
        self.assertEqual(len(r_mv), len(raw))
        self.assertEqual(len(r_sub), len(raw))

    def test_seeking_and_cursor(self) -> None:
        reader = ByteReader(b"0123456789ABCDEF")
        self.assertEqual(reader.tell(), 0)
        self.assertEqual(reader.remaining, 16)
        self.assertFalse(reader.is_eof)

        # Seek forward
        reader.seek(5, io.SEEK_SET)
        self.assertEqual(reader.tell(), 5)
        self.assertEqual(reader.read_byte(), ord("5"))

        # Seek relative
        reader.seek(2, io.SEEK_CUR)
        self.assertEqual(reader.tell(), 8)
        self.assertEqual(reader.read_byte(), ord("8"))

        # Seek from end
        reader.seek(-2, io.SEEK_END)
        self.assertEqual(reader.tell(), 14)
        self.assertEqual(bytes(reader.read_bytes(2)), b"EF")
        self.assertTrue(reader.is_eof)

        # Negative position error
        with self.assertRaises(ValueError):
            reader.seek(-1, io.SEEK_SET)

    def test_slice_and_sub_reader(self) -> None:
        raw = b"ABCDEFGHIJ"
        reader = ByteReader(raw)
        sl = reader.slice(2, 6)
        self.assertEqual(bytes(sl), b"CDEF")
        self.assertEqual(reader.tell(), 0)  # cursor unaltered

        sub = reader.sub_reader(4, 9)
        self.assertEqual(len(sub), 5)
        self.assertEqual(bytes(sub.read_bytes(5)), b"EFGHI")

    def test_read_and_peek(self) -> None:
        reader = ByteReader(b"XYZ123")
        self.assertEqual(reader.peek_byte(), ord("X"))
        self.assertEqual(reader.peek_byte(1), ord("Y"))
        self.assertEqual(reader.read_byte(), ord("X"))
        self.assertEqual(bytes(reader.peek_bytes(2)), b"YZ")
        self.assertEqual(bytes(reader.read_bytes(2)), b"YZ")

        # Bounds checks
        self.assertIsNone(reader.peek_byte(100))
        with self.assertRaises(EOFError):
            reader.read_bytes(10, require_exact=True)

    def test_pattern_matching_and_finding(self) -> None:
        reader = ByteReader(b"trailer\n<< /Size 10 >>\nstartxref\n500")
        self.assertTrue(reader.match(b"trailer"))
        self.assertEqual(reader.tell(), 7)

        # Non-matching does not advance
        self.assertFalse(reader.match(b"MISSING"))
        self.assertEqual(reader.tell(), 7)

        # Find forward and backward
        idx = reader.find(b"startxref")
        self.assertEqual(idx, 23)

        ridx = reader.rfind(b"Size")
        self.assertEqual(ridx, 12)

    def test_pdf_whitespace_and_comments(self) -> None:
        data = b"   \t\r\n% This is a comment\r\n  % Another comment\n123"
        reader = ByteReader(data)
        skipped = reader.skip_whitespace_and_comments()
        self.assertGreater(skipped, 0)
        self.assertEqual(bytes(reader.read_bytes(3)), b"123")

    def test_read_line(self) -> None:
        data = b"Line 1\nLine 2\r\nLine 3\rLine 4"
        reader = ByteReader(data)
        self.assertEqual(bytes(reader.read_line()), b"Line 1")
        self.assertEqual(bytes(reader.read_line()), b"Line 2")
        self.assertEqual(bytes(reader.read_line()), b"Line 3")
        self.assertEqual(bytes(reader.read_line()), b"Line 4")
        self.assertTrue(reader.is_eof)

    def test_endian_unpacking(self) -> None:
        # Construct binary payload
        u16_be_bytes = struct.pack(">H", 0x1234)
        u16_le_bytes = struct.pack("<H", 0x1234)
        u32_be_bytes = struct.pack(">I", 0xDEADBEEF)
        u32_le_bytes = struct.pack("<I", 0xDEADBEEF)
        u64_be_bytes = struct.pack(">Q", 0x0123456789ABCDEF)
        f32_be_bytes = struct.pack(">f", 3.1415927)
        f64_be_bytes = struct.pack(">d", 2.718281828459045)
        fixed_bytes = struct.pack(">i", int(1.5 * 65536))

        # 24-bit test: 0x123456
        u24_be_bytes = bytes([0x12, 0x34, 0x56])
        u24_le_bytes = bytes([0x56, 0x34, 0x12])

        payload = (
            b"\x80\x7F"
            + u16_be_bytes
            + u16_le_bytes
            + u24_be_bytes
            + u24_le_bytes
            + u32_be_bytes
            + u32_le_bytes
            + u64_be_bytes
            + f32_be_bytes
            + f64_be_bytes
            + fixed_bytes
        )

        r = ByteReader(payload)
        self.assertEqual(r.read_u8(), 0x80)
        self.assertEqual(r.read_i8(), 127)
        self.assertEqual(r.read_u16_be(), 0x1234)
        self.assertEqual(r.read_u16_le(), 0x1234)
        self.assertEqual(r.read_u24_be(), 0x123456)
        self.assertEqual(r.read_u24_le(), 0x123456)
        self.assertEqual(r.read_u32_be(), 0xDEADBEEF)
        self.assertEqual(r.read_u32_le(), 0xDEADBEEF)
        self.assertEqual(r.read_u64_be(), 0x0123456789ABCDEF)
        self.assertAlmostEqual(r.read_f32_be(), 3.1415927, places=5)
        self.assertAlmostEqual(r.read_f64_be(), 2.718281828459045, places=10)
        self.assertAlmostEqual(r.read_fixed_16_16(), 1.5)


class TestBitReader(unittest.TestCase):
    """Test BitReader bit-level stream parsing."""

    def test_msb_first_reading(self) -> None:
        # Byte: 0b10110001 (0xB1), 0b11001010 (0xCA)
        data = bytes([0b10110001, 0b11001010])
        reader = BitReader(data, msb_first=True)

        self.assertEqual(reader.remaining_bits, 16)
        # Read 1 bit: 1
        self.assertEqual(reader.read_bit(), 1)
        # Read 3 bits: 0b011 = 3
        self.assertEqual(reader.read_bits(3), 3)
        # Read 4 bits: 0b0001 = 1
        self.assertEqual(reader.read_bits(4), 1)

        # Now at second byte
        self.assertEqual(reader.bit_tell(), 8)
        # Read 4 bits: 0b1100 = 12
        self.assertEqual(reader.read_bits(4), 12)
        # Peek remaining 4 bits: 0b1010 = 10
        self.assertEqual(reader.peek_bits(4), 10)
        self.assertEqual(reader.read_bits(4), 10)
        self.assertTrue(reader.is_eof)

    def test_lsb_first_reading(self) -> None:
        # Byte: 0b00001101 (0x0D) -> LSB bits: 1, 0, 1, 1, 0, 0, 0, 0
        data = bytes([0b00001101])
        reader = BitReader(data, msb_first=False)

        # Read 4 bits: 0b1101 = 13
        self.assertEqual(reader.read_bits(4), 13)
        # Read 4 bits: 0b0000 = 0
        self.assertEqual(reader.read_bits(4), 0)
        self.assertTrue(reader.is_eof)

    def test_byte_alignment_and_seek(self) -> None:
        data = bytes([0xFF, 0x00, 0xAA])
        reader = BitReader(data)
        reader.read_bits(3)
        self.assertEqual(reader.bit_tell(), 3)
        reader.align_to_byte()
        self.assertEqual(reader.bit_tell(), 8)
        self.assertEqual(reader.read_bits(8), 0x00)

        # Bit seek
        reader.bit_seek(0)
        self.assertEqual(reader.read_bits(8), 0xFF)

    def test_bit_reader_eof_error(self) -> None:
        reader = BitReader(bytes([0xFF]))
        reader.read_bits(8)
        with self.assertRaises(EOFError):
            reader.read_bit()


if __name__ == "__main__":
    unittest.main()
