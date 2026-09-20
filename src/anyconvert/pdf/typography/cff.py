"""Compact Font Format (CFF / Type 2) font parser.

Adheres to Adobe Technical Note #5176:
- CFF Header, Name INDEX, Top DICT INDEX, String INDEX, Global Subr INDEX.
- DICT operand decoding (variable-length integers and BCD-encoded reals).
- CharStrings INDEX and advance width extraction.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple, Union

from anyconvert.common.geometry import BoundingBox
from anyconvert.exceptions import PDFFontError
from anyconvert.pdf.typography.font import BaseFont, FontMetrics


class CFFIndex:
    """Represents a CFF INDEX structure containing variable-length binary items."""

    __slots__ = ("items",)

    def __init__(self, items: List[bytes]) -> None:
        self.items: List[bytes] = items

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, idx: int) -> bytes:
        return self.items[idx]

    def __iter__(self) -> Iterator[bytes]:
        return iter(self.items)

    @classmethod
    def parse(cls, data: bytes, offset: int) -> Tuple[CFFIndex, int]:
        """Parse CFF INDEX at offset.

        Returns:
            Tuple[CFFIndex, int]: Parsed index and next byte offset.
        """
        if offset + 2 > len(data):
            return cls([]), offset

        count = struct.unpack_from(">H", data, offset)[0]
        if count == 0:
            return cls([]), offset + 2

        if offset + 3 > len(data):
            return cls([]), offset + 2

        off_size = data[offset + 2]
        if off_size < 1 or off_size > 4:
            return cls([]), offset + 3

        pos = offset + 3
        num_offsets = count + 1
        if pos + num_offsets * off_size > len(data):
            return cls([]), pos

        offsets: List[int] = []
        for _ in range(num_offsets):
            val = int.from_bytes(data[pos : pos + off_size], "big")
            offsets.append(val)
            pos += off_size

        data_start = pos - 1
        items: List[bytes] = []
        for i in range(count):
            start = data_start + offsets[i]
            end = data_start + offsets[i + 1]
            if end <= len(data):
                items.append(data[start:end])
            else:
                items.append(b"")

        next_pos = data_start + offsets[-1]
        return cls(items), next_pos

    @classmethod
    def build(cls, items: Sequence[bytes]) -> bytes:
        """Serialize a sequence of byte items into binary CFF INDEX format.

        Args:
            items: Sequence of binary objects.

        Returns:
            bytes: Serialized CFF INDEX bytes.
        """
        count = len(items)
        if count == 0:
            return struct.pack(">H", 0)

        # Offsets start at 1 (1-based relative to data start - 1)
        offsets: List[int] = [1]
        cur = 1
        for item in items:
            cur += len(item)
            offsets.append(cur)

        max_off = cur
        if max_off < 256:
            off_size = 1
        elif max_off < 65536:
            off_size = 2
        elif max_off < 16777216:
            off_size = 3
        else:
            off_size = 4

        header = bytearray(struct.pack(">HB", count, off_size))
        for off in offsets:
            header.extend(off.to_bytes(off_size, "big"))

        for item in items:
            header.extend(item)

        return bytes(header)


class CFFFont(BaseFont):
    """Parses Compact Font Format (CFF) data streams."""

    __slots__ = (
        "_raw_data",
        "_top_dict",
        "_strings",
        "_charstrings",
        "_default_width_x",
        "_nominal_width_x",
        "_font_matrix",
    )

    def __init__(self, data: bytes, name: str = "CFFFont") -> None:
        """Initialize and parse CFF font.

        Args:
            data: Raw CFF binary payload.
            name: Font name identifier.
        """
        super().__init__(name=name)
        self._raw_data: bytes = data
        self._top_dict: Dict[int, List[Any]] = {}
        self._strings: List[str] = []
        self._charstrings: List[bytes] = []
        self._default_width_x: float = 0.0
        self._nominal_width_x: float = 0.0
        self._font_matrix: List[float] = [0.001, 0.0, 0.0, 0.001, 0.0, 0.0]

        self._parse()

    @property
    def font_matrix(self) -> List[float]:
        """Return 6-element font transformation matrix."""
        return list(self._font_matrix)

    @property
    def default_width_x(self) -> float:
        """Return default advance width from Private DICT."""
        return self._default_width_x

    @property
    def nominal_width_x(self) -> float:
        """Return nominal advance width from Private DICT."""
        return self._nominal_width_x

    def _parse(self) -> None:
        """Parse CFF header, Name INDEX, Top DICT, String INDEX, and CharStrings."""
        data = self._raw_data
        if len(data) < 4:
            return

        major, minor, hdr_size, off_size = struct.unpack_from(">BBBB", data, 0)
        if hdr_size < 4 or hdr_size > len(data):
            return
        pos = hdr_size

        # 1. Name INDEX
        name_index, pos = CFFIndex.parse(data, pos)
        if len(name_index) > 0:
            self.name = name_index[0].decode("ascii", errors="replace")

        # 2. Top DICT INDEX
        top_dict_index, pos = CFFIndex.parse(data, pos)

        # 3. String INDEX
        string_index, pos = CFFIndex.parse(data, pos)
        self._strings = [s.decode("latin-1", errors="replace") for s in string_index]

        # 4. Global Subr INDEX
        global_subrs, pos = CFFIndex.parse(data, pos)

        # Parse Top DICT key-value pairs
        if len(top_dict_index) > 0:
            self._top_dict = self._parse_dict(top_dict_index[0])

        # FontBBox (operator 5)
        if 5 in self._top_dict and len(self._top_dict[5]) >= 4:
            try:
                x0 = float(self._top_dict[5][0])
                y0 = float(self._top_dict[5][1])
                x1 = float(self._top_dict[5][2])
                y1 = float(self._top_dict[5][3])
                self.metrics.bbox = BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1)
                self.metrics.ascender = max(0.0, y1)
                self.metrics.descender = min(0.0, y0)
            except (ValueError, TypeError):
                pass

        # isFixedPitch (operator (12, 1) = 3073)
        if 3073 in self._top_dict and len(self._top_dict[3073]) >= 1:
            try:
                self.metrics.is_monospace = bool(self._top_dict[3073][0])
            except (ValueError, TypeError):
                pass

        # ItalicAngle (operator (12, 2) = 3074)
        if 3074 in self._top_dict and len(self._top_dict[3074]) >= 1:
            try:
                angle = float(self._top_dict[3074][0])
                self.metrics.italic_angle = angle
                self.metrics.is_italic = angle != 0.0
            except (ValueError, TypeError):
                pass

        # FontMatrix (operator (12, 7) = 3079)
        if 3079 in self._top_dict and len(self._top_dict[3079]) >= 6:
            try:
                self._font_matrix = [float(self._top_dict[3079][i]) for i in range(6)]
            except (ValueError, TypeError):
                pass

        # Private DICT (operator 18: size, offset)
        if 18 in self._top_dict and len(self._top_dict[18]) >= 2:
            priv_size = int(self._top_dict[18][0])
            priv_offset = int(self._top_dict[18][1])
            if priv_offset + priv_size <= len(data):
                priv_dict = self._parse_dict(data[priv_offset : priv_offset + priv_size])
                # defaultWidthX (operator 20)
                if 20 in priv_dict and len(priv_dict[20]) >= 1:
                    self._default_width_x = float(priv_dict[20][0])
                # nominalWidthX (operator 21)
                if 21 in priv_dict and len(priv_dict[21]) >= 1:
                    self._nominal_width_x = float(priv_dict[21][0])

        # CharStrings (operator 17)
        if 17 in self._top_dict and len(self._top_dict[17]) >= 1:
            charstrings_offset = int(self._top_dict[17][0])
            if charstrings_offset < len(data):
                charstrings_index, _ = CFFIndex.parse(data, charstrings_offset)
                self._charstrings = list(charstrings_index.items)
                self._extract_widths()

    def _parse_dict(self, data: bytes) -> Dict[int, List[Any]]:
        """Parse binary CFF DICT operators and operands."""
        res: Dict[int, List[Any]] = {}
        stack: List[Any] = []
        pos = 0
        length = len(data)

        while pos < length:
            b0 = data[pos]
            pos += 1

            if b0 == 28:
                # 16-bit signed integer
                if pos + 2 <= length:
                    val = struct.unpack_from(">h", data, pos)[0]
                    stack.append(val)
                    pos += 2
            elif b0 == 29:
                # 32-bit signed integer
                if pos + 4 <= length:
                    val = struct.unpack_from(">i", data, pos)[0]
                    stack.append(val)
                    pos += 4
            elif b0 == 30:
                # Real number (BCD encoded)
                num_str = ""
                while pos < length:
                    nibbles = (data[pos] >> 4, data[pos] & 0x0F)
                    pos += 1
                    done = False
                    for nibble in nibbles:
                        if 0 <= nibble <= 9:
                            num_str += str(nibble)
                        elif nibble == 0x0A:
                            num_str += "."
                        elif nibble == 0x0B:
                            num_str += "E"
                        elif nibble == 0x0C:
                            num_str += "E-"
                        elif nibble == 0x0E:
                            num_str += "-"
                        elif nibble == 0x0F:
                            done = True
                            break
                    if done:
                        break
                try:
                    stack.append(float(num_str))
                except ValueError:
                    stack.append(0.0)
            elif 32 <= b0 <= 246:
                stack.append(b0 - 139)
            elif 247 <= b0 <= 250:
                if pos < length:
                    b1 = data[pos]
                    pos += 1
                    stack.append((b0 - 247) * 256 + b1 + 108)
            elif 251 <= b0 <= 254:
                if pos < length:
                    b1 = data[pos]
                    pos += 1
                    stack.append(-(b0 - 251) * 256 - b1 - 108)
            elif b0 == 12:
                # Two-byte operator
                if pos < length:
                    b1 = data[pos]
                    pos += 1
                    op_code = (12 << 8) | b1
                    res[op_code] = list(stack)
                    stack.clear()
            else:
                # Single-byte operator (0 to 31)
                res[b0] = list(stack)
                stack.clear()

        return res

    def _extract_widths(self) -> None:
        """Extract advance widths from Type 2 CharStrings."""
        for gid, cs_data in enumerate(self._charstrings):
            w = self._parse_charstring_width(cs_data)
            self.widths[gid] = w

        if 0 in self.widths:
            self.metrics.default_width = self.widths[0]

    def _parse_charstring_width(self, data: bytes) -> float:
        """Parse advance width from Type 2 CharString."""
        if not data:
            return self._default_width_x

        stack: List[float] = []
        pos = 0
        length = len(data)

        while pos < length:
            b0 = data[pos]
            pos += 1

            if b0 == 28:
                if pos + 2 <= length:
                    val = struct.unpack_from(">h", data, pos)[0]
                    stack.append(float(val))
                    pos += 2
            elif 32 <= b0 <= 246:
                stack.append(float(b0 - 139))
            elif 247 <= b0 <= 250:
                if pos < length:
                    b1 = data[pos]
                    pos += 1
                    stack.append(float((b0 - 247) * 256 + b1 + 108))
            elif 251 <= b0 <= 254:
                if pos < length:
                    b1 = data[pos]
                    pos += 1
                    stack.append(float(-(b0 - 251) * 256 - b1 - 108))
            elif b0 == 255:
                # 16.16 fixed point
                if pos + 4 <= length:
                    fixed_val = struct.unpack_from(">i", data, pos)[0]
                    stack.append(fixed_val / 65536.0)
                    pos += 4
            elif b0 == 12:
                # 2-byte operator
                if pos < length:
                    pos += 1
                if stack:
                    return self._nominal_width_x + stack[0]
                return self._default_width_x
            else:
                # Single-byte operator
                if b0 in (1, 3, 18, 23):
                    # Stem operators: pairs of stems; odd length means width is prepended
                    if len(stack) % 2 != 0:
                        return self._nominal_width_x + stack[0]
                elif b0 in (4, 22):
                    # vmoveto (4) / hmoveto (22): 1 operand, width makes 2
                    if len(stack) > 1:
                        return self._nominal_width_x + stack[0]
                elif b0 == 21:
                    # rmoveto (21): 2 operands (dx, dy), width makes 3
                    if len(stack) > 2:
                        return self._nominal_width_x + stack[0]
                elif b0 == 14:
                    # endchar (14): 0 operands, width makes 1
                    if len(stack) >= 1:
                        return self._nominal_width_x + stack[0]
                else:
                    if len(stack) % 2 != 0:
                        return self._nominal_width_x + stack[0]
                return self._default_width_x

        return self._default_width_x
