"""Zero-copy binary memory reader and bit stream tools.

This module provides high-performance binary parsing tools backed by Python memoryviews:
- ByteReader: Zero-copy slicing, seeking, and endian-aware unpacking over raw byte buffers.
- BitReader: Dynamic MSB/LSB bit-level stream reader for compressed image, font, and filter data.
"""

from __future__ import annotations

import io
import os
import struct
from typing import Optional, Sequence, Set, Tuple, Union

# Standard PDF whitespace byte values per PDF 32000-1 §7.2.2:
# 0x00 (NUL), 0x09 (HT), 0x0A (LF), 0x0C (FF), 0x0D (CR), 0x20 (SP)
PDF_WHITESPACE: Set[int] = {0x00, 0x09, 0x0A, 0x0C, 0x0D, 0x20}

# Standard PDF delimiter characters per PDF 32000-1 §7.2.2:
# '(', ')', '<', '>', '[', ']', '{', '}', '/', '%'
PDF_DELIMITERS: Set[int] = {
    0x28,  # (
    0x29,  # )
    0x3C,  # <
    0x3E,  # >
    0x5B,  # [
    0x5D,  # ]
    0x7B,  # {
    0x7D,  # }
    0x2F,  # /
    0x25,  # %
}


class ByteReader:
    """Zero-copy memoryview-backed binary byte reader.

    Supports non-allocating slicing, navigation, pattern matching, backwards searching,
    and endian-aware numeric unpacking over arbitrary byte sequences.
    """

    __slots__ = ("_view", "_pos", "_length")

    def __init__(self, data: Union[bytes, bytearray, memoryview, ByteReader]) -> None:
        """Initialize ByteReader with byte data or another ByteReader.

        Args:
            data: Raw bytes, bytearray, memoryview, or existing ByteReader.
        """
        if isinstance(data, ByteReader):
            self._view: memoryview = data._view
            self._pos: int = data._pos
        elif isinstance(data, memoryview):
            self._view = data
            self._pos = 0
        elif isinstance(data, (bytes, bytearray)):
            self._view = memoryview(data)
            self._pos = 0
        else:
            raise TypeError(f"Expected bytes, bytearray, or memoryview, got {type(data).__name__}")

        self._length: int = len(self._view)

    @property
    def pos(self) -> int:
        """Current cursor byte offset."""
        return self._pos

    @property
    def length(self) -> int:
        """Total buffer length in bytes."""
        return self._length

    @property
    def remaining(self) -> int:
        """Number of unread bytes remaining."""
        return max(0, self._length - self._pos)

    @property
    def is_eof(self) -> bool:
        """Return True if cursor has reached or passed the end of the buffer."""
        return self._pos >= self._length

    def tell(self) -> int:
        """Return current byte position."""
        return self._pos

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        """Move cursor to a specified byte offset.

        Args:
            offset: Target byte offset.
            whence: Reference point (os.SEEK_SET=0, os.SEEK_CUR=1, os.SEEK_END=2).

        Returns:
            int: New byte offset.

        Raises:
            ValueError: If seek target is negative or whence is invalid.
        """
        if whence == os.SEEK_SET:
            target = offset
        elif whence == os.SEEK_CUR:
            target = self._pos + offset
        elif whence == os.SEEK_END:
            target = self._length + offset
        else:
            raise ValueError(f"Invalid whence argument: {whence}")

        if target < 0:
            raise ValueError(f"Negative seek position: {target}")

        self._pos = min(target, self._length)
        return self._pos

    def peek_byte(self) -> Optional[int]:
        """Return the next byte without advancing cursor, or None if EOF."""
        if self._pos >= self._length:
            return None
        return int(self._view[self._pos])

    def peek_bytes(self, n: int) -> memoryview:
        """Return a zero-copy memoryview of the next n bytes without advancing cursor.

        Args:
            n: Number of bytes to peek.

        Returns:
            memoryview: Zero-copy slice of available bytes up to n.
        """
        end = min(self._pos + max(0, n), self._length)
        return self._view[self._pos:end]

    def read_byte(self) -> int:
        """Read and return the next single byte, advancing cursor by 1.

        Returns:
            int: Byte value (0-255).

        Raises:
            EOFError: If at end of buffer.
        """
        if self._pos >= self._length:
            raise EOFError("Unexpected end of buffer in read_byte()")
        val = int(self._view[self._pos])
        self._pos += 1
        return val

    def read_bytes(self, n: int) -> memoryview:
        """Read and return a zero-copy slice of up to n bytes, advancing cursor.

        Args:
            n: Number of bytes to read.

        Returns:
            memoryview: Sliced view of up to n bytes.
        """
        read_len = min(max(0, n), self.remaining)
        start = self._pos
        self._pos += read_len
        return self._view[start : self._pos]

    def read_exact(self, n: int) -> memoryview:
        """Read exactly n bytes or raise EOFError.

        Args:
            n: Number of bytes required.

        Returns:
            memoryview: Exactly n bytes.

        Raises:
            EOFError: If fewer than n bytes are remaining.
        """
        if self.remaining < n:
            raise EOFError(
                f"Requested {n} bytes, but only {self.remaining} bytes remain at offset {self._pos}"
            )
        start = self._pos
        self._pos += n
        return self._view[start : self._pos]

    def slice(self, start: int, end: int) -> memoryview:
        """Return a zero-copy memoryview slice between absolute offsets [start, end].

        Args:
            start: Absolute starting byte offset.
            end: Absolute ending byte offset.

        Returns:
            memoryview: Sliced view.
        """
        clamped_start = max(0, min(start, self._length))
        clamped_end = max(clamped_start, min(end, self._length))
        return self._view[clamped_start:clamped_end]

    def sub_reader(self, start: int, end: int) -> ByteReader:
        """Create a new ByteReader operating over the slice [start, end].

        Args:
            start: Starting byte offset.
            end: Ending byte offset.

        Returns:
            ByteReader: Child reader over sliced view.
        """
        return ByteReader(self.slice(start, end))

    def match(self, pattern: bytes, consume: bool = False) -> bool:
        """Check if bytes at current position match pattern.

        Args:
            pattern: Byte sequence to match.
            consume: If True and match succeeds, advances cursor past pattern.

        Returns:
            bool: True if matched.
        """
        pat_len = len(pattern)
        if self.remaining < pat_len:
            return False

        if bytes(self._view[self._pos : self._pos + pat_len]) == pattern:
            if consume:
                self._pos += pat_len
            return True
        return False

    def skip_whitespace(self) -> int:
        """Skip contiguous PDF whitespace bytes (0x00, 0x09, 0x0A, 0x0C, 0x0D, 0x20).

        Returns:
            int: Number of whitespace bytes skipped.
        """
        start = self._pos
        view = self._view
        length = self._length
        pos = self._pos

        while pos < length and view[pos] in PDF_WHITESPACE:
            pos += 1

        self._pos = pos
        return pos - start

    def skip_comment(self) -> bool:
        """Skip a PDF comment line starting with '%' (0x25) until EOL.

        Returns:
            bool: True if a comment was encountered and skipped.
        """
        if self._pos >= self._length or self._view[self._pos] != 0x25:  # '%'
            return False

        view = self._view
        length = self._length
        pos = self._pos + 1

        # Scan until CR (0x0D) or LF (0x0A) or EOF
        while pos < length and view[pos] not in (0x0A, 0x0D):
            pos += 1

        self._pos = pos
        return True

    def skip_whitespace_and_comments(self) -> int:
        """Repeatedly skip all whitespace and '%' comments until reaching a token or EOF.

        Returns:
            int: Total count of bytes skipped.
        """
        start = self._pos
        while self._pos < self._length:
            skipped_ws = self.skip_whitespace()
            skipped_comment = self.skip_comment()
            if skipped_ws == 0 and not skipped_comment:
                break
        return self._pos - start

    def read_line(self) -> bytes:
        """Read bytes until next newline (CR, LF, or CRLF), returning line bytes without newline.

        Returns:
            bytes: Line content.
        """
        if self.is_eof:
            return b""

        start = self._pos
        view = self._view
        length = self._length
        pos = self._pos

        while pos < length and view[pos] not in (0x0A, 0x0D):
            pos += 1

        line = bytes(view[start:pos])

        # Consume newline characters
        if pos < length and view[pos] == 0x0D:  # CR
            pos += 1
            if pos < length and view[pos] == 0x0A:  # CRLF
                pos += 1
        elif pos < length and view[pos] == 0x0A:  # LF
            pos += 1

        self._pos = pos
        return line

    def read_until(self, delimiter: bytes, include_delimiter: bool = False) -> memoryview:
        """Read bytes until delimiter sequence is encountered.

        Args:
            delimiter: Byte sequence marking the stopping boundary.
            include_delimiter: If True, delimiter is included in the returned slice.

        Returns:
            memoryview: Sliced view of data up to delimiter.
        """
        idx = self.find(delimiter, start=self._pos)
        start = self._pos
        if idx == -1:
            # Read until EOF
            self._pos = self._length
            return self._view[start : self._length]

        if include_delimiter:
            end = idx + len(delimiter)
            self._pos = end
            return self._view[start:end]
        else:
            self._pos = idx + len(delimiter)
            return self._view[start:idx]

    def find(self, pattern: bytes, start: Optional[int] = None, end: Optional[int] = None) -> int:
        """Search forward for pattern within byte buffer.

        Args:
            pattern: Byte sequence to find.
            start: Optional start offset (defaults to current position).
            end: Optional end offset (defaults to buffer length).

        Returns:
            int: Absolute byte offset of first match, or -1 if not found.
        """
        s = self._pos if start is None else max(0, start)
        e = self._length if end is None else min(self._length, end)

        if s >= e or len(pattern) > (e - s):
            return -1

        # Use bytes.find via memoryview cast/slicing
        raw_slice = self._view[s:e]
        rel_idx = bytes(raw_slice).find(pattern)
        if rel_idx == -1:
            return -1
        return s + rel_idx

    def rfind(self, pattern: bytes, start: Optional[int] = None, end: Optional[int] = None) -> int:
        """Search backward for pattern within byte buffer.

        Crucial for scanning backwards from EOF to locate `startxref`.

        Args:
            pattern: Byte sequence to find.
            start: Optional start offset (defaults to 0).
            end: Optional end offset (defaults to buffer length).

        Returns:
            int: Absolute byte offset of match, or -1 if not found.
        """
        s = 0 if start is None else max(0, start)
        e = self._length if end is None else min(self._length, end)

        if s >= e or len(pattern) > (e - s):
            return -1

        raw_slice = self._view[s:e]
        rel_idx = bytes(raw_slice).rfind(pattern)
        if rel_idx == -1:
            return -1
        return s + rel_idx

    # =========================================================================
    # Numeric Unpacking (Endian-Aware via struct.unpack_from)
    # =========================================================================

    def read_uint8(self) -> int:
        """Read unsigned 8-bit integer."""
        return self.read_byte()

    def read_int8(self) -> int:
        """Read signed 8-bit integer."""
        val = self.read_byte()
        return val if val < 128 else val - 256

    def read_uint16_be(self) -> int:
        """Read unsigned 16-bit big-endian integer."""
        if self.remaining < 2:
            raise EOFError("Insufficient bytes for uint16_be")
        val: int = struct.unpack_from(">H", self._view, self._pos)[0]
        self._pos += 2
        return val

    def read_uint16_le(self) -> int:
        """Read unsigned 16-bit little-endian integer."""
        if self.remaining < 2:
            raise EOFError("Insufficient bytes for uint16_le")
        val: int = struct.unpack_from("<H", self._view, self._pos)[0]
        self._pos += 2
        return val

    def read_int16_be(self) -> int:
        """Read signed 16-bit big-endian integer."""
        if self.remaining < 2:
            raise EOFError("Insufficient bytes for int16_be")
        val: int = struct.unpack_from(">h", self._view, self._pos)[0]
        self._pos += 2
        return val

    def read_int16_le(self) -> int:
        """Read signed 16-bit little-endian integer."""
        if self.remaining < 2:
            raise EOFError("Insufficient bytes for int16_le")
        val: int = struct.unpack_from("<h", self._view, self._pos)[0]
        self._pos += 2
        return val

    def read_uint24_be(self) -> int:
        """Read unsigned 24-bit big-endian integer (common in font tables)."""
        if self.remaining < 3:
            raise EOFError("Insufficient bytes for uint24_be")
        b0 = self._view[self._pos]
        b1 = self._view[self._pos + 1]
        b2 = self._view[self._pos + 2]
        self._pos += 3
        return (b0 << 16) | (b1 << 8) | b2

    def read_uint32_be(self) -> int:
        """Read unsigned 32-bit big-endian integer."""
        if self.remaining < 4:
            raise EOFError("Insufficient bytes for uint32_be")
        val: int = struct.unpack_from(">I", self._view, self._pos)[0]
        self._pos += 4
        return val

    def read_uint32_le(self) -> int:
        """Read unsigned 32-bit little-endian integer."""
        if self.remaining < 4:
            raise EOFError("Insufficient bytes for uint32_le")
        val: int = struct.unpack_from("<I", self._view, self._pos)[0]
        self._pos += 4
        return val

    def read_int32_be(self) -> int:
        """Read signed 32-bit big-endian integer."""
        if self.remaining < 4:
            raise EOFError("Insufficient bytes for int32_be")
        val: int = struct.unpack_from(">i", self._view, self._pos)[0]
        self._pos += 4
        return val

    def read_int32_le(self) -> int:
        """Read signed 32-bit little-endian integer."""
        if self.remaining < 4:
            raise EOFError("Insufficient bytes for int32_le")
        val: int = struct.unpack_from("<i", self._view, self._pos)[0]
        self._pos += 4
        return val

    def read_uint64_be(self) -> int:
        """Read unsigned 64-bit big-endian integer."""
        if self.remaining < 8:
            raise EOFError("Insufficient bytes for uint64_be")
        val: int = struct.unpack_from(">Q", self._view, self._pos)[0]
        self._pos += 8
        return val

    def read_uint64_le(self) -> int:
        """Read unsigned 64-bit little-endian integer."""
        if self.remaining < 8:
            raise EOFError("Insufficient bytes for uint64_le")
        val: int = struct.unpack_from("<Q", self._view, self._pos)[0]
        self._pos += 8
        return val

    def read_float32_be(self) -> float:
        """Read 32-bit IEEE 754 single-precision float (big-endian)."""
        if self.remaining < 4:
            raise EOFError("Insufficient bytes for float32_be")
        val: float = struct.unpack_from(">f", self._view, self._pos)[0]
        self._pos += 4
        return val

    def read_float32_le(self) -> float:
        """Read 32-bit IEEE 754 single-precision float (little-endian)."""
        if self.remaining < 4:
            raise EOFError("Insufficient bytes for float32_le")
        val: float = struct.unpack_from("<f", self._view, self._pos)[0]
        self._pos += 4
        return val

    def read_float64_be(self) -> float:
        """Read 64-bit IEEE 754 double-precision float (big-endian)."""
        if self.remaining < 8:
            raise EOFError("Insufficient bytes for float64_be")
        val: float = struct.unpack_from(">d", self._view, self._pos)[0]
        self._pos += 8
        return val

    def read_float64_le(self) -> float:
        """Read 64-bit IEEE 754 double-precision float (little-endian)."""
        if self.remaining < 8:
            raise EOFError("Insufficient bytes for float64_le")
        val: float = struct.unpack_from("<d", self._view, self._pos)[0]
        self._pos += 8
        return val

    def to_bytes(self) -> bytes:
        """Return full buffer as bytes."""
        return bytes(self._view)


class BitReader:
    """Bit-level stream reader supporting variable bit-widths and MSB/LSB bit orders.

    Designed for decoding bit-packed data streams such as LZW codes, JBIG2, CCITT Fax,
    and indexed image color components.
    """

    __slots__ = ("_reader", "_msb_first", "_buffer", "_bits_left")

    def __init__(
        self,
        source: Union[bytes, bytearray, memoryview, ByteReader],
        msb_first: bool = True,
    ) -> None:
        """Initialize BitReader.

        Args:
            source: Raw byte data or existing ByteReader.
            msb_first: True for MSB-first bit order (default, standard in PDF),
                       False for LSB-first bit order.
        """
        self._reader = source if isinstance(source, ByteReader) else ByteReader(source)
        self._msb_first: bool = msb_first
        self._buffer: int = 0
        self._bits_left: int = 0

    @property
    def is_msb_first(self) -> bool:
        """Return True if reading Most Significant Bit first."""
        return self._msb_first

    @property
    def bits_available_in_buffer(self) -> int:
        """Number of unconsumed bits currently buffered in accumulator."""
        return self._bits_left

    @property
    def is_eof(self) -> bool:
        """Return True if both buffer and underlying byte stream are exhausted."""
        return self._bits_left == 0 and self._reader.is_eof

    def read_bit(self) -> int:
        """Read a single bit (0 or 1).

        Returns:
            int: 0 or 1.

        Raises:
            EOFError: If stream is exhausted.
        """
        return self.read_bits(1)

    def read_bits(self, count: int) -> int:
        """Read specified number of bits (1 to 32).

        Args:
            count: Number of bits to read (1 <= count <= 32).

        Returns:
            int: Unpacked integer value.

        Raises:
            ValueError: If count is out of range [1, 32].
            EOFError: If stream does not contain enough bits.
        """
        if count < 1 or count > 32:
            raise ValueError(f"Bit count must be between 1 and 32, got {count}")

        # Fill buffer until we have at least count bits or stream runs dry
        while self._bits_left < count:
            if self._reader.is_eof:
                raise EOFError(
                    f"Requested {count} bits, but only {self._bits_left} bits remaining"
                )
            byte_val = self._reader.read_byte()
            if self._msb_first:
                self._buffer = (self._buffer << 8) | byte_val
            else:
                self._buffer |= byte_val << self._bits_left
            self._bits_left += 8

        if self._msb_first:
            shift = self._bits_left - count
            result = (self._buffer >> shift) & ((1 << count) - 1)
            self._bits_left -= count
            # Mask buffer to prevent overflow
            self._buffer &= (1 << self._bits_left) - 1
        else:
            result = self._buffer & ((1 << count) - 1)
            self._buffer >>= count
            self._bits_left -= count

        return result

    def peek_bits(self, count: int) -> int:
        """Peek at specified number of bits without consuming them.

        Args:
            count: Number of bits to peek (1 <= count <= 32).

        Returns:
            int: Unpacked integer value.

        Raises:
            ValueError: If count is out of range.
            EOFError: If stream does not contain enough bits.
        """
        if count < 1 or count > 32:
            raise ValueError(f"Bit count must be between 1 and 32, got {count}")

        # Save state
        saved_pos = self._reader.pos
        saved_buffer = self._buffer
        saved_bits_left = self._bits_left

        try:
            return self.read_bits(count)
        finally:
            # Restore state
            self._reader.seek(saved_pos)
            self._buffer = saved_buffer
            self._bits_left = saved_bits_left

    def skip_bits(self, count: int) -> None:
        """Skip specified number of bits.

        Args:
            count: Number of bits to discard.
        """
        remaining = count
        while remaining > 0:
            to_read = min(remaining, 32)
            self.read_bits(to_read)
            remaining -= to_read

    def align_to_byte(self) -> None:
        """Discard unconsumed bits in accumulator to align to the next byte boundary."""
        if self._msb_first:
            discard = self._bits_left % 8
            if discard > 0:
                self._bits_left -= discard
                self._buffer &= (1 << self._bits_left) - 1
        else:
            discard = self._bits_left % 8
            if discard > 0:
                self._buffer >>= discard
                self._bits_left -= discard
        # Also clear full bytes left in buffer if align means flush
        self._buffer = 0
        self._bits_left = 0
