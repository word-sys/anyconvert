"""Zero-copy binary memory readers and bit stream utilities.

Provides:
- ByteReader: High-performance, zero-allocation memoryview-backed binary reader
  with endian-aware integer/float decoding and PDF token navigation.
- BitReader: Bit-level stream reader supporting variable-length bit decoding
  (1-32 bits) in both MSB-first and LSB-first modes.
"""

from __future__ import annotations

import io
import struct
from typing import Optional, Sequence, Tuple, Union

# Standard PDF whitespace characters: NUL (0x00), TAB (0x09), LF (0x0A), FF (0x0C), CR (0x0D), SPACE (0x20)
PDF_WHITESPACE = frozenset(b"\x00\t\n\x0c\r ")

# Standard PDF delimiters
PDF_DELIMITERS = frozenset(b"()<>[]{}/%")


class ByteReader:
    """Zero-copy memoryview reader for high-throughput binary stream navigation.

    Wraps a contiguous byte sequence in a read-only memoryview, providing
    cursor management, slicing without memory duplication, struct unpacking,
    and scanning primitives.
    """

    __slots__ = ("_view", "_pos", "_len")

    def __init__(self, data: Union[bytes, bytearray, memoryview, ByteReader]) -> None:
        if isinstance(data, ByteReader):
            self._view: memoryview = data._view
        elif isinstance(data, memoryview):
            self._view = data.cast("B") if data.format != "B" else data
        elif isinstance(data, (bytes, bytearray)):
            self._view = memoryview(data)
        else:
            raise TypeError(f"Unsupported data type for ByteReader: {type(data).__name__}")

        self._pos: int = 0
        self._len: int = len(self._view)

    # --------------------------------------------------------------------------
    # Cursor & Stream Properties
    # --------------------------------------------------------------------------

    def __len__(self) -> int:
        return self._len

    @property
    def position(self) -> int:
        """Current byte cursor position."""
        return self._pos

    @property
    def remaining(self) -> int:
        """Number of remaining unread bytes."""
        return max(0, self._len - self._pos)

    @property
    def is_eof(self) -> bool:
        """Check whether cursor has reached or passed the end of the buffer."""
        return self._pos >= self._len

    @property
    def buffer(self) -> memoryview:
        """Access the underlying memoryview."""
        return self._view

    def tell(self) -> int:
        """Return current byte position."""
        return self._pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        """Move cursor position according to whence.

        Args:
            offset: Byte offset to move.
            whence: io.SEEK_SET (0), io.SEEK_CUR (1), or io.SEEK_END (2).

        Returns:
            New absolute cursor position.
        """
        if whence == io.SEEK_SET:
            new_pos = offset
        elif whence == io.SEEK_CUR:
            new_pos = self._pos + offset
        elif whence == io.SEEK_END:
            new_pos = self._len + offset
        else:
            raise ValueError(f"Invalid whence value: {whence}")

        if new_pos < 0:
            raise ValueError(f"Seek position cannot be negative ({new_pos})")
        self._pos = min(new_pos, self._len)
        return self._pos

    def skip(self, n: int) -> None:
        """Advance the cursor by n bytes."""
        self.seek(n, io.SEEK_CUR)

    # --------------------------------------------------------------------------
    # Slicing and Sub-readers
    # --------------------------------------------------------------------------

    def slice(self, start: int, end: int) -> memoryview:
        """Extract a zero-copy memoryview slice between [start, end]."""
        start = max(0, min(start, self._len))
        end = max(start, min(end, self._len))
        return self._view[start:end]

    def sub_reader(self, start: int, end: int) -> ByteReader:
        """Create a child ByteReader referencing a slice of this reader."""
        return ByteReader(self.slice(start, end))

    # --------------------------------------------------------------------------
    # Low-Level Reading & Peeking
    # --------------------------------------------------------------------------

    def read_byte(self) -> int:
        """Read and return next unsigned 8-bit integer, advancing cursor by 1.

        Raises:
            EOFError: If at EOF.
        """
        if self._pos >= self._len:
            raise EOFError("Unexpected end of stream while reading byte")
        b = self._view[self._pos]
        self._pos += 1
        return b

    def peek_byte(self, offset: int = 0) -> Optional[int]:
        """Look at byte at (current_pos + offset) without advancing cursor.

        Returns:
            Integer byte in [0, 255] or None if target position is out of bounds.
        """
        target = self._pos + offset
        if 0 <= target < self._len:
            return self._view[target]
        return None

    def read_bytes(self, n: int, require_exact: bool = True) -> memoryview:
        """Read n bytes advancing cursor.

        Args:
            n: Number of bytes to read.
            require_exact: If True, raises EOFError if fewer than n bytes remain.

        Returns:
            Zero-copy memoryview slice of length n (or available bytes).
        """
        if n < 0:
            raise ValueError(f"Cannot read negative number of bytes: {n}")
        if self._pos + n > self._len:
            if require_exact:
                raise EOFError(
                    f"Requested {n} bytes but only {self.remaining} bytes available"
                )
            n = self.remaining

        start = self._pos
        self._pos += n
        return self._view[start:self._pos]

    def peek_bytes(self, n: int) -> memoryview:
        """Look ahead up to n bytes without advancing cursor."""
        if n < 0:
            raise ValueError(f"Cannot peek negative number of bytes: {n}")
        end = min(self._pos + n, self._len)
        return self._view[self._pos:end]

    def match(self, pattern: bytes) -> bool:
        """Check if remaining stream starts with pattern.

        If matched, advances cursor past pattern and returns True.
        Otherwise leaves cursor unchanged and returns False.
        """
        pat_len = len(pattern)
        if self._pos + pat_len <= self._len:
            if bytes(self._view[self._pos:self._pos + pat_len]) == pattern:
                self._pos += pat_len
                return True
        return False

    def starts_with(self, pattern: bytes) -> bool:
        """Check if stream starts with pattern at current position without advancing."""
        pat_len = len(pattern)
        if self._pos + pat_len <= self._len:
            return bytes(self._view[self._pos:self._pos + pat_len]) == pattern
        return False

    def find(self, sub: bytes, start: Optional[int] = None, end: Optional[int] = None) -> int:
        """Find index of sub within specified bounds (default from current pos to EOF).

        Returns:
            Absolute index of first match, or -1 if not found.
        """
        st = self._pos if start is None else max(0, start)
        en = self._len if end is None else min(self._len, end)
        if st >= en:
            return -1
        # Convert search window to bytes for efficient pattern matching
        window = bytes(self._view[st:en])
        idx = window.find(sub)
        return -1 if idx == -1 else st + idx

    def rfind(self, sub: bytes, start: Optional[int] = None, end: Optional[int] = None) -> int:
        """Search backward for index of sub within specified bounds.

        Args:
            sub: Substring bytes to search for.
            start: Starting index (default: 0).
            end: Ending index (default: end of buffer).

        Returns:
            Absolute index of last match, or -1 if not found.
        """
        st = 0 if start is None else max(0, start)
        en = self._len if end is None else min(self._len, end)
        if st >= en:
            return -1
        window = bytes(self._view[st:en])
        idx = window.rfind(sub)
        return -1 if idx == -1 else st + idx


    # --------------------------------------------------------------------------
    # PDF Whitespace and Comment Scanners
    # --------------------------------------------------------------------------

    def skip_whitespace(self) -> int:
        """Skip any consecutive PDF whitespace characters.

        Returns:
            Count of whitespace bytes skipped.
        """
        start = self._pos
        while self._pos < self._len and self._view[self._pos] in PDF_WHITESPACE:
            self._pos += 1
        return self._pos - start

    def skip_comment(self) -> bool:
        """If positioned on a PDF comment indicator (%), consume to line ending.

        Returns:
            True if a comment was skipped, False otherwise.
        """
        if self._pos < self._len and self._view[self._pos] == 0x25:  # b'%'
            self._pos += 1
            while self._pos < self._len:
                b = self._view[self._pos]
                self._pos += 1
                if b == 0x0A:  # LF
                    break
                if b == 0x0D:  # CR
                    if self._pos < self._len and self._view[self._pos] == 0x0A:
                        self._pos += 1  # consume CRLF
                    break
            return True
        return False

    def skip_whitespace_and_comments(self) -> int:
        """Repeatedly skip whitespace and PDF comments until token start or EOF.

        Returns:
            Total count of bytes skipped.
        """
        start = self._pos
        while self._pos < self._len:
            ws = self.skip_whitespace()
            cm = self.skip_comment()
            if ws == 0 and not cm:
                break
        return self._pos - start

    def read_line(self, keep_newline: bool = False) -> memoryview:
        """Read bytes until next CRLF, LF, or CR.

        Returns:
            Zero-copy memoryview slice of the line.
        """
        start = self._pos
        while self._pos < self._len:
            b = self._view[self._pos]
            if b == 0x0A:  # LF
                line_end = self._pos
                self._pos += 1
                return self.slice(start, self._pos if keep_newline else line_end)
            if b == 0x0D:  # CR
                line_end = self._pos
                self._pos += 1
                if self._pos < self._len and self._view[self._pos] == 0x0A:
                    self._pos += 1  # CRLF
                return self.slice(start, self._pos if keep_newline else line_end)
            self._pos += 1

        return self.slice(start, self._pos)

    # --------------------------------------------------------------------------
    # Endian-Aware Numeric Unpacking
    # --------------------------------------------------------------------------

    def read_u8(self) -> int:
        """Read unsigned 8-bit integer."""
        return self.read_byte()

    def read_i8(self) -> int:
        """Read signed 8-bit integer."""
        b = self.read_byte()
        return b - 256 if b >= 128 else b

    def read_u16_be(self) -> int:
        """Read unsigned 16-bit big-endian integer."""
        res: Tuple[int] = struct.unpack_from(">H", self._view, self._pos)
        self._pos += 2
        return res[0]

    def read_u16_le(self) -> int:
        """Read unsigned 16-bit little-endian integer."""
        res: Tuple[int] = struct.unpack_from("<H", self._view, self._pos)
        self._pos += 2
        return res[0]

    def read_i16_be(self) -> int:
        """Read signed 16-bit big-endian integer."""
        res: Tuple[int] = struct.unpack_from(">h", self._view, self._pos)
        self._pos += 2
        return res[0]

    def read_i16_le(self) -> int:
        """Read signed 16-bit little-endian integer."""
        res: Tuple[int] = struct.unpack_from("<h", self._view, self._pos)
        self._pos += 2
        return res[0]

    def read_u24_be(self) -> int:
        """Read unsigned 24-bit big-endian integer."""
        if self._pos + 3 > self._len:
            raise EOFError("Insufficient bytes for u24_be")
        b0 = self._view[self._pos]
        b1 = self._view[self._pos + 1]
        b2 = self._view[self._pos + 2]
        self._pos += 3
        return (b0 << 16) | (b1 << 8) | b2

    def read_u24_le(self) -> int:
        """Read unsigned 24-bit little-endian integer."""
        if self._pos + 3 > self._len:
            raise EOFError("Insufficient bytes for u24_le")
        b0 = self._view[self._pos]
        b1 = self._view[self._pos + 1]
        b2 = self._view[self._pos + 2]
        self._pos += 3
        return (b2 << 16) | (b1 << 8) | b0

    def read_u32_be(self) -> int:
        """Read unsigned 32-bit big-endian integer."""
        res: Tuple[int] = struct.unpack_from(">I", self._view, self._pos)
        self._pos += 4
        return res[0]

    def read_u32_le(self) -> int:
        """Read unsigned 32-bit little-endian integer."""
        res: Tuple[int] = struct.unpack_from("<I", self._view, self._pos)
        self._pos += 4
        return res[0]

    def read_i32_be(self) -> int:
        """Read signed 32-bit big-endian integer."""
        res: Tuple[int] = struct.unpack_from(">i", self._view, self._pos)
        self._pos += 4
        return res[0]

    def read_i32_le(self) -> int:
        """Read signed 32-bit little-endian integer."""
        res: Tuple[int] = struct.unpack_from("<i", self._view, self._pos)
        self._pos += 4
        return res[0]

    def read_u64_be(self) -> int:
        """Read unsigned 64-bit big-endian integer."""
        res: Tuple[int] = struct.unpack_from(">Q", self._view, self._pos)
        self._pos += 8
        return res[0]

    def read_u64_le(self) -> int:
        """Read unsigned 64-bit little-endian integer."""
        res: Tuple[int] = struct.unpack_from("<Q", self._view, self._pos)
        self._pos += 8
        return res[0]

    def read_f32_be(self) -> float:
        """Read 32-bit big-endian IEEE-754 float."""
        res: Tuple[float] = struct.unpack_from(">f", self._view, self._pos)
        self._pos += 4
        return res[0]

    def read_f32_le(self) -> float:
        """Read 32-bit little-endian IEEE-754 float."""
        res: Tuple[float] = struct.unpack_from("<f", self._view, self._pos)
        self._pos += 4
        return res[0]

    def read_f64_be(self) -> float:
        """Read 64-bit big-endian IEEE-754 double."""
        res: Tuple[float] = struct.unpack_from(">d", self._view, self._pos)
        self._pos += 8
        return res[0]

    def read_f64_le(self) -> float:
        """Read 64-bit little-endian IEEE-754 double."""
        res: Tuple[float] = struct.unpack_from("<d", self._view, self._pos)
        self._pos += 8
        return res[0]

    def read_fixed_16_16(self) -> float:
        """Read 16.16 signed fixed point number (used in sfnt font tables)."""
        val = self.read_i32_be()
        return val / 65536.0


class BitReader:
    """Bit-level stream reader for arbitrary bit-depth decoding.

    Supports reading 1-32 bits at a time in either MSB-first (standard PDF/image)
    or LSB-first (TIFF/PackBits/GIF) order.
    """

    __slots__ = ("_view", "_byte_pos", "_bit_pos", "_len", "_msb_first")

    def __init__(
        self,
        data: Union[bytes, bytearray, memoryview, ByteReader],
        msb_first: bool = True,
    ) -> None:
        if isinstance(data, ByteReader):
            self._view: memoryview = data.buffer
        elif isinstance(data, memoryview):
            self._view = data.cast("B") if data.format != "B" else data
        else:
            self._view = memoryview(data)

        self._byte_pos: int = 0
        self._bit_pos: int = 0  # 0 to 7
        self._len: int = len(self._view)
        self._msb_first: bool = msb_first

    @property
    def is_eof(self) -> bool:
        """Check if all bits have been consumed."""
        return self._byte_pos >= self._len

    @property
    def remaining_bits(self) -> int:
        """Total number of bits left to read."""
        if self._byte_pos >= self._len:
            return 0
        return (self._len - self._byte_pos) * 8 - self._bit_pos

    def bit_tell(self) -> int:
        """Total number of bits consumed since stream origin."""
        return self._byte_pos * 8 + self._bit_pos

    def bit_seek(self, bit_pos: int) -> None:
        """Seek to an absolute bit position."""
        if bit_pos < 0:
            raise ValueError(f"Bit position cannot be negative ({bit_pos})")
        self._byte_pos = min(bit_pos // 8, self._len)
        self._bit_pos = bit_pos % 8 if self._byte_pos < self._len else 0

    def align_to_byte(self) -> None:
        """Advance cursor to the start of the next byte if not currently byte-aligned."""
        if self._bit_pos != 0:
            self._bit_pos = 0
            self._byte_pos += 1

    def read_bit(self) -> int:
        """Read a single bit (0 or 1).

        Raises:
            EOFError: If no bits remain.
        """
        if self._byte_pos >= self._len:
            raise EOFError("Unexpected end of stream while reading bit")

        byte_val = self._view[self._byte_pos]
        if self._msb_first:
            # Bit 0 is highest bit (0x80), bit 7 is lowest (0x01)
            bit = (byte_val >> (7 - self._bit_pos)) & 1
        else:
            # Bit 0 is lowest bit (0x01), bit 7 is highest (0x80)
            bit = (byte_val >> self._bit_pos) & 1

        self._bit_pos += 1
        if self._bit_pos == 8:
            self._bit_pos = 0
            self._byte_pos += 1

        return bit

    def read_bits(self, n: int) -> int:
        """Read n bits as an unsigned integer (up to 32 bits).

        Args:
            n: Number of bits to read (0 to 32).

        Returns:
            Unsigned integer composed of the read bits.

        Raises:
            ValueError: If n < 0 or n > 32.
            EOFError: If fewer than n bits remain.
        """
        if n == 0:
            return 0
        if n < 0 or n > 32:
            raise ValueError(f"read_bits supports 0 to 32 bits, requested: {n}")
        if self.remaining_bits < n:
            raise EOFError(
                f"Requested {n} bits, but only {self.remaining_bits} bits remain"
            )

        value = 0
        if self._msb_first:
            for _ in range(n):
                byte_val = self._view[self._byte_pos]
                bit = (byte_val >> (7 - self._bit_pos)) & 1
                value = (value << 1) | bit
                self._bit_pos += 1
                if self._bit_pos == 8:
                    self._bit_pos = 0
                    self._byte_pos += 1
        else:
            for i in range(n):
                byte_val = self._view[self._byte_pos]
                bit = (byte_val >> self._bit_pos) & 1
                value |= bit << i
                self._bit_pos += 1
                if self._bit_pos == 8:
                    self._bit_pos = 0
                    self._byte_pos += 1

        return value

    def peek_bits(self, n: int) -> int:
        """Look ahead n bits without advancing the cursor."""
        saved_byte = self._byte_pos
        saved_bit = self._bit_pos
        try:
            return self.read_bits(n)
        finally:
            self._byte_pos = saved_byte
            self._bit_pos = saved_bit


__all__ = [
    "ByteReader",
    "BitReader",
    "PDF_WHITESPACE",
    "PDF_DELIMITERS",
]
