"""Unit tests for Phase 3: ByteReader, BitReader, and binary stream tools."""

from __future__ import annotations

import io
import os
import struct
import unittest

from anyconvert.common.reader import (
    PDF_DELIMITERS,
    PDF_WHITESPACE,
    BitReader,
    ByteReader,
)


class TestByteReader(unittest.TestCase):
    """Tests for ByteReader zero-copy memory reader."""

    def test_init_and_properties(self) -> None:
        data = b"Hello, World!"
        reader = ByteReader(data)
        self.assertEqual(reader.length, 13)
        self.assertEqual(reader.pos, 0)
        self.assertEqual(reader.remaining, 13)
        self.assertFalse(reader.is_eof)

        # From bytearray
        ba_reader = ByteReader(bytearray(b"abc"))
        self.assertEqual(ba_reader.length, 3)

        # From memoryview
        mv_reader = ByteReader(memoryview(b"xyz"))
        self.assertEqual(mv_reader.length, 3)

        # From another ByteReader
        clone = ByteReader(reader)
        self.assertEqual(clone.length, 13)

        # Invalid type raises TypeError
        with self.assertRaises(TypeError):
            ByteReader(12345)  # type: ignore[arg-type]

    def test_seeking_and_navigation(self) -> None:
        data = b"0123456789"
        reader = ByteReader(data)

        # SEEK_SET
        reader.seek(5)
        self.assertEqual(reader.tell(), 5)
        self.assertEqual(reader.read_byte(), ord("5"))

        # SEEK_CUR
        reader.seek(2, whence=os.SEEK_CUR)
        self.assertEqual(reader.tell(), 8)
        self.assertEqual(reader.read_byte(), ord("8"))

        # SEEK_END
        reader.seek(-2, whence=os.SEEK_END)
        self.assertEqual(reader.tell(), 8)

        # Negative seek error
        with self.assertRaises(ValueError):
            reader.seek(-1, whence=os.SEEK_SET)

        # Invalid whence
        with self.assertRaises(ValueError):
            reader.seek(0, whence=99)

        # Seeking beyond length clamps to length
        reader.seek(100)
        self.assertEqual(reader.tell(), 10)
        self.assertTrue(reader.is_eof)

    def test_reading_and_slicing(self) -> None:
        data = b"ABCDEFGHIJ"
        reader = ByteReader(data)

        # Peek
        self.assertEqual(reader.peek_byte(), ord("A"))
        self.assertEqual(bytes(reader.peek_bytes(4)), b"ABCD")
        self.assertEqual(reader.pos, 0)  # Peek does not advance

        # Read byte
        b = reader.read_byte()
        self.assertEqual(b, ord("A"))
        self.assertEqual(reader.pos, 1)

        # Read bytes
        s = reader.read_bytes(3)
        self.assertEqual(bytes(s), b"BCD")
        self.assertEqual(reader.pos, 4)

        # Read exact
        exact = reader.read_exact(2)
        self.assertEqual(bytes(exact), b"EF")

        # Slice
        sl = reader.slice(2, 6)
        self.assertEqual(bytes(sl), b"CDEF")

        # Sub reader
        sub = reader.sub_reader(0, 3)
        self.assertEqual(sub.length, 3)
        self.assertEqual(bytes(sub.read_bytes(3)), b"ABC")

        # Read exact beyond EOF
        with self.assertRaises(EOFError):
            reader.read_exact(100)

    def test_match_and_find(self) -> None:
        data = b"xref\n0 10\ntrailer\n<< /Size 10 >>\nstartxref\n1234\n%%EOF"
        reader = ByteReader(data)

        # Match without consume
        self.assertTrue(reader.match(b"xref"))
        self.assertEqual(reader.pos, 0)

        # Match with consume
        self.assertTrue(reader.match(b"xref\n", consume=True))
        self.assertEqual(reader.pos, 5)

        # Forward search
        startxref_pos = reader.find(b"startxref")
        self.assertGreater(startxref_pos, 0)

        # Reverse search (crucial for PDF startxref locating)
        eof_pos = reader.rfind(b"%%EOF")
        self.assertGreater(eof_pos, startxref_pos)
        self.assertEqual(reader.rfind(b"nonexistent"), -1)

    def test_whitespace_and_comments(self) -> None:
        raw = b" \t\r\n% This is a comment\r\n   % Second comment\n123 456"
        reader = ByteReader(raw)

        # Skip all whitespace and comments
        skipped = reader.skip_whitespace_and_comments()
        self.assertGreater(skipped, 0)
        self.assertEqual(bytes(reader.read_bytes(3)), b"123")

    def test_read_line_and_read_until(self) -> None:
        text = b"First line\r\nSecond line\nThird line\rFourth line"
        reader = ByteReader(text)

        self.assertEqual(reader.read_line(), b"First line")
        self.assertEqual(reader.read_line(), b"Second line")
        self.assertEqual(reader.read_line(), b"Third line")
        self.assertEqual(reader.read_line(), b"Fourth line")
        self.assertEqual(reader.read_line(), b"")

        # read_until
        stream_data = b"stream\r\nHello PDF Content\r\nendstream"
        sr = ByteReader(stream_data)
        self.assertEqual(bytes(sr.read_until(b"\r\n")), b"stream")
        self.assertEqual(bytes(sr.read_until(b"\r\nendstream")), b"Hello PDF Content")

    def test_numeric_unpacking(self) -> None:
        # Build binary payload
        payload = bytearray()
        payload.extend(struct.pack(">B", 250))  # uint8
        payload.extend(struct.pack(">b", -50))  # int8
        payload.extend(struct.pack(">H", 0xABCD))  # uint16_be
        payload.extend(struct.pack("<H", 0xABCD))  # uint16_le
        payload.extend(struct.pack(">h", -1234))  # int16_be
        payload.extend(struct.pack("<h", -1234))  # int16_le
        payload.extend(b"\x12\x34\x56")  # uint24_be (0x123456)
        payload.extend(struct.pack(">I", 0x12345678))  # uint32_be
        payload.extend(struct.pack("<I", 0x12345678))  # uint32_le
        payload.extend(struct.pack(">i", -987654))  # int32_be
        payload.extend(struct.pack("<i", -987654))  # int32_le
        payload.extend(struct.pack(">Q", 0x1122334455667788))  # uint64_be
        payload.extend(struct.pack("<Q", 0x1122334455667788))  # uint64_le
        payload.extend(struct.pack(">f", 3.14159))  # float32_be
        payload.extend(struct.pack("<f", 3.14159))  # float32_le
        payload.extend(struct.pack(">d", 2.718281828459))  # float64_be
        payload.extend(struct.pack("<d", 2.718281828459))  # float64_le

        r = ByteReader(payload)
        self.assertEqual(r.read_uint8(), 250)
        self.assertEqual(r.read_int8(), -50)
        self.assertEqual(r.read_uint16_be(), 0xABCD)
        self.assertEqual(r.read_uint16_le(), 0xABCD)
        self.assertEqual(r.read_int16_be(), -1234)
        self.assertEqual(r.read_int16_le(), -1234)
        self.assertEqual(r.read_uint24_be(), 0x123456)
        self.assertEqual(r.read_uint32_be(), 0x12345678)
        self.assertEqual(r.read_uint32_le(), 0x12345678)
        self.assertEqual(r.read_int32_be(), -987654)
        self.assertEqual(r.read_int32_le(), -987654)
        self.assertEqual(r.read_uint64_be(), 0x1122334455667788)
        self.assertEqual(r.read_uint64_le(), 0x1122334455667788)
        self.assertAlmostEqual(r.read_float32_be(), 3.14159, places=5)
        self.assertAlmostEqual(r.read_float32_le(), 3.14159, places=5)
        self.assertAlmostEqual(r.read_float64_be(), 2.718281828459, places=10)
        self.assertAlmostEqual(r.read_float64_le(), 2.718281828459, places=10)
        self.assertTrue(r.is_eof)

        # EOFError on short reads
        short = ByteReader(b"\x01")
        with self.assertRaises(EOFError):
            short.read_uint16_be()


class TestBitReader(unittest.TestCase):
    """Tests for BitReader bit-level stream reading."""

    def test_msb_first_reading(self) -> None:
        # Binary: 10101100 00111101 (0xAC, 0x3D)
        data = bytes([0xAC, 0x3D])
        br = BitReader(data, msb_first=True)

        self.assertTrue(br.is_msb_first)
        # Read 4 bits: 1010 (10)
        self.assertEqual(br.read_bits(4), 10)
        # Peek 4 bits: 1100 (12)
        self.assertEqual(br.peek_bits(4), 12)
        # Read 4 bits: 1100 (12)
        self.assertEqual(br.read_bits(4), 12)
        # Read 1 bit: 0
        self.assertEqual(br.read_bit(), 0)
        # Read 7 bits: 0111101 (61)
        self.assertEqual(br.read_bits(7), 61)
        self.assertTrue(br.is_eof)

    def test_lsb_first_reading(self) -> None:
        # Binary: 10101100 (0xAC) -> LSB first: bits 00110101
        data = bytes([0xAC])
        br = BitReader(data, msb_first=False)

        self.assertFalse(br.is_msb_first)
        # Lower 4 bits of 0xAC are 1100 (12)
        self.assertEqual(br.read_bits(4), 12)
        # Upper 4 bits of 0xAC are 1010 (10)
        self.assertEqual(br.read_bits(4), 10)
        self.assertTrue(br.is_eof)

    def test_bit_reader_exceptions_and_skip(self) -> None:
        br = BitReader(b"\xFF\x00")
        with self.assertRaises(ValueError):
            br.read_bits(0)
        with self.assertRaises(ValueError):
            br.read_bits(33)

        br.skip_bits(4)
        self.assertEqual(br.read_bits(4), 0x0F)
        br.align_to_byte()
        self.assertEqual(br.read_bits(8), 0x00)

        # Exhaustion error
        with self.assertRaises(EOFError):
            br.read_bits(1)


if __name__ == "__main__":
    unittest.main()
