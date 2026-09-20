"""Type 1 PostScript font parser and eexec decryptor.

Implements Adobe Type 1 Font Format specification:
- Binary eexec segment decryption using standard 55665 / 52845 cipher.
- PFB (Printer Font Binary) segment unpacker.
- ASCII header scanner: FontName, FontMatrix, FontBBox, Encoding.
- CharStrings decryption (cipher key 4330) and advance width (hsbw / sbw) extraction.
"""

from __future__ import annotations

import re
import struct
from typing import Dict, List, Optional, Tuple

from anyconvert.common.geometry import BoundingBox
from anyconvert.exceptions import PDFFontError
from anyconvert.pdf.typography.font import BaseFont, FontMetrics


def eexec_decrypt(ciphertext: bytes, key: int = 55665, discard: int = 4) -> bytes:
    """Decrypt eexec or CharString encrypted bytes.

    Cipher parameters defined in Adobe Type 1 Font Format §7.1:
        c1 = 52845
        c2 = 22703

    Args:
        ciphertext: Encrypted byte sequence.
        key: Initial 16-bit cipher key (55665 for eexec, 4330 for CharStrings).
        discard: Number of initial random bytes to discard (typically 4).

    Returns:
        bytes: Decrypted plain byte sequence.
    """
    c1 = 52845
    c2 = 22703
    r = key & 0xFFFF

    # Check if ciphertext is hex-encoded
    clean_data = ciphertext
    if len(ciphertext) >= 4 and all(
        (0x30 <= b <= 0x39) or (0x41 <= b <= 0x46) or (0x61 <= b <= 0x66) or b in (9, 10, 13, 32)
        for b in ciphertext[: min(64, len(ciphertext))]
    ):
        try:
            hex_str = "".join(chr(b) for b in ciphertext if b not in (9, 10, 13, 32))
            clean_data = bytes.fromhex(hex_str)
        except ValueError:
            clean_data = ciphertext

    out = bytearray(len(clean_data))
    for i, b in enumerate(clean_data):
        plain = (b ^ (r >> 8)) & 0xFF
        r = ((b + r) * c1 + c2) & 0xFFFF
        out[i] = plain

    if discard > 0 and len(out) >= discard:
        return bytes(out[discard:])
    return bytes(out)


def eexec_encrypt(plaintext: bytes, key: int = 55665, add_random: int = 4) -> bytes:
    """Encrypt plaintext using eexec or CharString cipher.

    Args:
        plaintext: Plain bytes to encrypt.
        key: Initial cipher key (55665 for eexec, 4330 for CharStrings).
        add_random: Number of dummy bytes to prepend (typically 4).

    Returns:
        bytes: Encrypted byte sequence.
    """
    c1 = 52845
    c2 = 22703
    r = key & 0xFFFF
    data = (b"\x00" * add_random) + plaintext
    out = bytearray(len(data))
    for i, p in enumerate(data):
        c = (p ^ (r >> 8)) & 0xFF
        r = ((c + r) * c1 + c2) & 0xFFFF
        out[i] = c
    return bytes(out)


def unpack_pfb(data: bytes) -> Tuple[bytes, int, int, int]:
    """Unpack PFB (Printer Font Binary) into concatenated raw data and segment lengths.

    Args:
        data: Binary PFB font content.

    Returns:
        Tuple[bytes, int, int, int]: (concatenated_bytes, length1, length2, length3)
    """
    if not data.startswith(b"\x80"):
        return data, len(data), 0, 0

    pos = 0
    length = len(data)
    chunks: List[bytes] = []
    length1 = 0
    length2 = 0
    length3 = 0

    while pos + 2 <= length and data[pos] == 0x80:
        rec_type = data[pos + 1]
        pos += 2
        if rec_type == 3:  # EOF marker
            break
        if pos + 4 > length:
            break
        seg_len = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        seg_data = data[pos : pos + seg_len]
        pos += seg_len
        chunks.append(seg_data)

        if rec_type == 1:
            length1 += seg_len
        elif rec_type == 2:
            length2 += seg_len

    if pos < length:
        tail = data[pos:]
        chunks.append(tail)
        length3 = len(tail)

    return b"".join(chunks), length1, length2, length3


def _parse_type1_charstring_width(cs_plain: bytes) -> Optional[float]:
    """Parse advance width from decrypted Type 1 CharString bytes."""
    stack: List[float] = []
    pos = 0
    length = len(cs_plain)

    while pos < length:
        b0 = cs_plain[pos]
        pos += 1

        if 32 <= b0 <= 246:
            stack.append(float(b0 - 139))
        elif 247 <= b0 <= 250:
            if pos < length:
                b1 = cs_plain[pos]
                pos += 1
                stack.append(float((b0 - 247) * 256 + b1 + 108))
        elif 251 <= b0 <= 254:
            if pos < length:
                b1 = cs_plain[pos]
                pos += 1
                stack.append(float(-(b0 - 251) * 256 - b1 - 108))
        elif b0 == 255:
            if pos + 4 <= length:
                v = struct.unpack_from(">i", cs_plain, pos)[0]
                stack.append(float(v))
                pos += 4
        elif b0 == 13:
            # hsbw: sbx wx 13
            if len(stack) >= 2:
                return stack[1]
            break
        elif b0 == 12:
            # Two-byte operator
            if pos < length:
                b1 = cs_plain[pos]
                pos += 1
                if b1 == 7:
                    # sbw: sbx sby wx wy 12 7
                    if len(stack) >= 4:
                        return stack[2]
            break
        else:
            # Other operator reached before hsbw/sbw
            break

    return None


class Type1Font(BaseFont):
    """Parses Adobe Type 1 embedded fonts (/FontFile or PFB)."""

    __slots__ = (
        "_raw_data",
        "_length1",
        "_length2",
        "_length3",
        "_font_matrix",
        "glyph_widths",
        "charstrings",
    )

    def __init__(
        self,
        data: bytes,
        name: str = "Type1Font",
        length1: Optional[int] = None,
        length2: Optional[int] = None,
        length3: Optional[int] = None,
    ) -> None:
        """Initialize and parse Type 1 font.

        Args:
            data: Raw font stream or PFB binary data.
            name: Font name identifier.
            length1: Length of ASCII portion in bytes.
            length2: Length of encrypted eexec portion in bytes.
            length3: Length of 512-zero trailer portion in bytes.
        """
        super().__init__(name=name)
        self._length1: Optional[int] = None
        self._length2: Optional[int] = None
        self._length3: Optional[int] = None

        if data.startswith(b"\x80\x01"):
            clean_data, l1, l2, l3 = unpack_pfb(data)
            self._raw_data: bytes = clean_data
            self._length1 = l1
            self._length2 = l2
            self._length3 = l3
        else:
            self._raw_data = data
            self._length1 = length1
            self._length2 = length2
            self._length3 = length3

        self._font_matrix: List[float] = [0.001, 0.0, 0.0, 0.001, 0.0, 0.0]
        self.glyph_widths: Dict[str, float] = {}
        self.charstrings: Dict[str, bytes] = {}

        self._parse()

    @property
    def font_matrix(self) -> List[float]:
        """Return 6-element font transformation matrix."""
        return list(self._font_matrix)

    def get_glyph_width(self, glyph_name: str) -> float:
        """Return advance width for glyph name in 1/1000 units."""
        return self.glyph_widths.get(glyph_name, self.metrics.default_width)

    def _parse(self) -> None:
        """Parse ASCII header, eexec segment, and CharStrings."""
        data = self._raw_data
        if not data:
            return

        # Determine ASCII portion
        ascii_text: str
        if self._length1 is not None and self._length1 > 0:
            ascii_chunk = data[: min(self._length1, len(data))]
            ascii_text = ascii_chunk.decode("latin-1", errors="replace")
        else:
            idx = data.find(b"eexec")
            if idx != -1:
                ascii_text = data[:idx].decode("latin-1", errors="replace")
            else:
                ascii_text = data[: min(4096, len(data))].decode("latin-1", errors="replace")

        # 1. Extract FontName: /FontName /Times-Roman def
        name_match = re.search(r"/FontName\s+/([^\s]+)", ascii_text)
        if name_match:
            self.name = name_match.group(1)

        # 2. Extract FontBBox: /FontBBox {-168 -218 1000 898}
        bbox_match = re.search(
            r"/FontBBox\s*\[?\s*\{?\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)",
            ascii_text,
        )
        if bbox_match:
            try:
                x0 = float(bbox_match.group(1))
                y0 = float(bbox_match.group(2))
                x1 = float(bbox_match.group(3))
                y1 = float(bbox_match.group(4))
                self.metrics.bbox = BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1)
                self.metrics.ascender = max(0.0, y1)
                self.metrics.descender = min(0.0, y0)
            except ValueError:
                pass

        # 3. Extract FontMatrix: /FontMatrix [0.001 0 0 0.001 0 0]
        matrix_match = re.search(
            r"/FontMatrix\s*\[\s*([-\d.eE]+)\s+([-\d.eE]+)\s+([-\d.eE]+)\s+([-\d.eE]+)\s+([-\d.eE]+)\s+([-\d.eE]+)\s*\]",
            ascii_text,
        )
        if matrix_match:
            try:
                self._font_matrix = [float(matrix_match.group(i)) for i in range(1, 7)]
            except ValueError:
                pass

        # 4. Extract ItalicAngle: /ItalicAngle -12 def
        italic_match = re.search(r"/ItalicAngle\s+([-\d.]+)", ascii_text)
        if italic_match:
            try:
                angle = float(italic_match.group(1))
                self.metrics.italic_angle = angle
                self.metrics.is_italic = angle != 0.0
            except ValueError:
                pass

        # 5. Extract isFixedPitch: /isFixedPitch true def
        pitch_match = re.search(r"/isFixedPitch\s+(true|false)", ascii_text)
        if pitch_match:
            self.metrics.is_monospace = pitch_match.group(1) == "true"

        # 6. Decrypt eexec portion
        decrypted_eexec: Optional[bytes] = None
        if self._length1 is not None and self._length2 is not None:
            eexec_start = self._length1
            eexec_end = eexec_start + self._length2
            if eexec_end <= len(data):
                ciphertext = data[eexec_start:eexec_end]
                try:
                    decrypted_eexec = eexec_decrypt(ciphertext)
                except Exception:
                    pass
        else:
            idx = data.find(b"eexec")
            if idx != -1:
                # Skip 'eexec' and following whitespace
                pos = idx + 5
                while pos < len(data) and data[pos] in (9, 10, 13, 32):
                    pos += 1
                ciphertext = data[pos:]
                try:
                    decrypted_eexec = eexec_decrypt(ciphertext)
                except Exception:
                    pass

        # 7. Extract CharStrings and widths from decrypted eexec
        if decrypted_eexec:
            self._extract_charstrings(decrypted_eexec)

    def _extract_charstrings(self, decrypted: bytes) -> None:
        """Scan decrypted eexec for /CharStrings and extract advance widths."""
        # Find entries like: /A 45 RD <45 bytes> ND or /A 45 -| <45 bytes> |-
        pattern = re.compile(rb"/([a-zA-Z0-9_.\-]+)\s+(\d+)\s+(?:RD|-\|)\s*")
        for m in pattern.finditer(decrypted):
            glyph_name = m.group(1).decode("ascii", errors="replace")
            cs_len = int(m.group(2))
            cs_start = m.end()
            cs_end = cs_start + cs_len
            if cs_end <= len(decrypted):
                cs_cipher = decrypted[cs_start:cs_end]
                try:
                    cs_plain = eexec_decrypt(cs_cipher, key=4330, discard=4)
                    self.charstrings[glyph_name] = cs_plain
                    w = _parse_type1_charstring_width(cs_plain)
                    if w is not None:
                        self.glyph_widths[glyph_name] = w
                        if glyph_name == ".notdef":
                            self.metrics.default_width = w
                except Exception:
                    pass
