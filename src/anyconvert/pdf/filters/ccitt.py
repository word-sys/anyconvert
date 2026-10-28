"""Pure-Python CCITT Group 3 (1D & 2D) and Group 4 (2D) Fax Decompression Filter.

Implements zero-dependency decompression adhering to:
- ITU-T Recommendation T.4 (Group 3 1D & 2D Facsimile)
- ITU-T Recommendation T.6 (Group 4 2D Facsimile)
- ISO 32000-1:2008 §7.4.6 (CCITTFaxDecode Filter)
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple, Union

from anyconvert.exceptions import PDFUnsupportedFilterError
from anyconvert.pdf.parser import PDFDict, PDFName

# ITU-T T.4 Table 1a: Terminating White Codes (0..63)
_WHITE_TERMINATING: List[Tuple[str, int]] = [
    ("00110101", 0), ("000111", 1), ("0111", 2), ("1000", 3),
    ("1011", 4), ("1100", 5), ("1110", 6), ("1111", 7),
    ("10011", 8), ("10100", 9), ("00111", 10), ("01000", 11),
    ("001000", 12), ("000011", 13), ("110100", 14), ("110101", 15),
    ("101010", 16), ("101011", 17), ("0100111", 18), ("0001100", 19),
    ("0001000", 20), ("0010111", 21), ("0000011", 22), ("0000100", 23),
    ("0101000", 24), ("0101011", 25), ("0010011", 26), ("0100100", 27),
    ("0011000", 28), ("00000010", 29), ("00000011", 30), ("00011010", 31),
    ("00011011", 32), ("00010010", 33), ("00010011", 34), ("00010100", 35),
    ("00010101", 36), ("00010110", 37), ("00010111", 38), ("00101000", 39),
    ("00101001", 40), ("00101010", 41), ("00101011", 42), ("00101100", 43),
    ("00101101", 44), ("00000100", 45), ("00000101", 46), ("00001010", 47),
    ("00001011", 48), ("01010010", 49), ("01010011", 50), ("01010100", 51),
    ("01010101", 52), ("00100100", 53), ("00100101", 54), ("01011000", 55),
    ("01011001", 56), ("01011010", 57), ("01011011", 58), ("01001010", 59),
    ("01001011", 60), ("00110010", 61), ("00110011", 62), ("00110100", 63),
]

# ITU-T T.4 Table 1b: Make Up White Codes (64..1728)
_WHITE_MAKEUP: List[Tuple[str, int]] = [
    ("11011", 64), ("10010", 128), ("010111", 192), ("0110111", 256),
    ("00110110", 320), ("00110111", 384), ("01100100", 448), ("01100101", 512),
    ("01101000", 576), ("01100111", 640), ("011001100", 704), ("011001101", 768),
    ("011010010", 832), ("011010011", 896), ("011010100", 960), ("011010101", 1024),
    ("011010110", 1088), ("011010111", 1152), ("011011000", 1216), ("011011001", 1280),
    ("011011010", 1344), ("011011011", 1408), ("010011000", 1472), ("010011001", 1536),
    ("010011010", 1600), ("011000", 1664), ("010011011", 1728),
]

# ITU-T T.4 Table 2a: Terminating Black Codes (0..63)
_BLACK_TERMINATING: List[Tuple[str, int]] = [
    ("0000110111", 0), ("010", 1), ("11", 2), ("10", 3),
    ("011", 4), ("0011", 5), ("0010", 6), ("00011", 7),
    ("000101", 8), ("000100", 9), ("0000100", 10), ("0000101", 11),
    ("0000111", 12), ("00000100", 13), ("00000111", 14), ("000011000", 15),
    ("0000010111", 16), ("0000011000", 17), ("0000001000", 18), ("00001100111", 19),
    ("00001101000", 20), ("00001101100", 21), ("00000110111", 22), ("00000101000", 23),
    ("00000010111", 24), ("00000011000", 25), ("000011001010", 26), ("000011001011", 27),
    ("000011001100", 28), ("000011001101", 29), ("000001101000", 30), ("000001101001", 31),
    ("000001101010", 32), ("000001101011", 33), ("000011010010", 34), ("000011010011", 35),
    ("000011010100", 36), ("000011010101", 37), ("000011010110", 38), ("000011010111", 39),
    ("000001101100", 40), ("000001101101", 41), ("000011011010", 42), ("000011011011", 43),
    ("000001010100", 44), ("000001010101", 45), ("000001010110", 46), ("000001010111", 47),
    ("000001100100", 48), ("000001100101", 49), ("000001010010", 50), ("000001010011", 51),
    ("000000100100", 52), ("000000110111", 53), ("000000111000", 54), ("000000100111", 55),
    ("000000101000", 56), ("000001011000", 57), ("000001011001", 58), ("000000101011", 59),
    ("000000101100", 60), ("000001011010", 61), ("000001100110", 62), ("000001100111", 63),
]

# ITU-T T.4 Table 2b: Make Up Black Codes (64..1728)
_BLACK_MAKEUP: List[Tuple[str, int]] = [
    ("0000001111", 64), ("000011001000", 128), ("000011001001", 192),
    ("000001011011", 256), ("000000110011", 320), ("000000110100", 384),
    ("000000110101", 448), ("0000001101100", 512), ("0000001101101", 576),
    ("0000001001010", 640), ("0000001001011", 704), ("0000001001100", 768),
    ("0000001001101", 832), ("0000001110010", 896), ("0000001110011", 960),
    ("0000001110100", 1024), ("0000001110101", 1088), ("0000001110110", 1152),
    ("0000001110111", 1216), ("0000001010010", 1280), ("0000001010011", 1344),
    ("0000001010100", 1408), ("0000001010101", 1472), ("0000001011010", 1536),
    ("0000001011011", 1600), ("0000001100100", 1664), ("0000001100101", 1728),
]

# ITU-T T.4 Table 3: Extended Make Up Codes (Common to Black and White)
_EXTENDED_MAKEUP: List[Tuple[str, int]] = [
    ("00000001000", 1792), ("00000001100", 1856), ("00000001101", 1920),
    ("000000010010", 1984), ("000000010011", 2048), ("000000010100", 2112),
    ("000000010101", 2176), ("000000010110", 2240), ("000000010111", 2304),
    ("000000011100", 2368), ("000000011101", 2432), ("000000011110", 2496),
    ("000000011111", 2560),
]

# ITU-T T.6 Table 1: 2D Coding Mode Codes
_MODE_CODES: List[Tuple[str, Any]] = [
    ("1", 0),                # Vertical V(0)
    ("011", 1),              # Vertical V_R(1)
    ("010", -1),             # Vertical V_L(1)
    ("001", "H"),            # Horizontal Mode
    ("0001", "P"),           # Pass Mode
    ("000011", 2),           # Vertical V_R(2)
    ("000010", -2),          # Vertical V_L(2)
    ("0000011", 3),          # Vertical V_R(3)
    ("0000010", -3),          # Vertical V_L(3)
    ("0000001", "EXT"),      # Extension Mode
    ("000000000001", "EOL"), # EOL code word
]


def _build_tree(entries: List[Tuple[str, Any]]) -> List[Any]:
    """Construct a binary decision tree for variable-length prefix code matching."""
    root: List[Any] = [None, None]
    for code, val in entries:
        node = root
        for i, bit_char in enumerate(code):
            b = 1 if bit_char == "1" else 0
            if i == len(code) - 1:
                node[b] = val
            else:
                if node[b] is None:
                    node[b] = [None, None]
                node = node[b]
    return root


# Pre-built decision trees for rapid prefix matching
_WHITE_TREE = _build_tree(_WHITE_TERMINATING + _WHITE_MAKEUP + _EXTENDED_MAKEUP)
_BLACK_TREE = _build_tree(_BLACK_TERMINATING + _BLACK_MAKEUP + _EXTENDED_MAKEUP)
_MODE_TREE = _build_tree(_MODE_CODES)


class _CCITTBitReader:
    """Zero-copy bit reader operating directly on byte sequences MSB-first."""

    __slots__ = ("_data", "_pos", "_bit_pos", "_length")

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0
        self._bit_pos = 7
        self._length = len(data)

    def read_bit(self) -> int:
        if self._pos >= self._length:
            return 0
        bit = (self._data[self._pos] >> self._bit_pos) & 1
        if self._bit_pos == 0:
            self._bit_pos = 7
            self._pos += 1
        else:
            self._bit_pos -= 1
        return bit

    def align_to_byte(self) -> None:
        if self._bit_pos != 7:
            self._bit_pos = 7
            self._pos += 1

    @property
    def is_eof(self) -> bool:
        return self._pos >= self._length


def _read_code(reader: _CCITTBitReader, tree: List[Any]) -> Any:
    """Traverse decision tree bit-by-bit until a leaf value is matched."""
    node = tree
    while True:
        bit = reader.read_bit()
        child = node[bit]
        if child is None:
            return None
        if not isinstance(child, list):
            return child
        node = child


def _read_run(reader: _CCITTBitReader, tree: List[Any]) -> int:
    """Read a sequence of make-up codes terminated by a terminating code."""
    total_run = 0
    while True:
        code = _read_code(reader, tree)
        if code is None or not isinstance(code, int):
            return int(total_run)
        total_run += int(code)
        if code < 64:
            break
    return int(total_run)


def _pack_bits_to_row(bits: List[int], width: int, black_is_1: bool) -> bytes:
    """Pack an array of binary pixels into a scanline row of bytes."""
    bytes_per_row = (width + 7) // 8
    buf = bytearray(bytes_per_row)
    for i in range(width):
        b = bits[i]
        # In CCITT: 1 is White, 0 is Black.
        # In PDF raw samples:
        # If BlackIs1 is False (default): 0 is Black, 1 is White -> keep b
        # If BlackIs1 is True: 1 is Black, 0 is White -> invert (1 - b)
        val = (1 - b) if black_is_1 else b
        if val:
            buf[i >> 3] |= 1 << (7 - (i & 7))
    return bytes(buf)


def _decode_1d_row(reader: _CCITTBitReader, width: int) -> List[int]:
    """Decode a single 1D Modified Huffman scanline."""
    curline = [1] * width
    curpos = 0
    color = 1  # Always start with White run

    while curpos < width and not reader.is_eof:
        tree = _WHITE_TREE if color == 1 else _BLACK_TREE
        run = _read_run(reader, tree)
        if run < 0:
            break
        end = min(width, curpos + run)
        for i in range(curpos, end):
            curline[i] = color
        curpos += run
        color = 1 - color

    return curline


def _decode_2d_row(reader: _CCITTBitReader, refline: List[int], width: int) -> Tuple[List[int], bool]:
    """Decode a single 2D Modified READ scanline.

    Returns:
        Tuple of (decoded_line, is_eofb_flag).
    """
    curline = [1] * width
    curpos = -1
    color = 1

    while curpos < width and not reader.is_eof:
        mode = _read_code(reader, _MODE_TREE)
        if mode == "EOL":
            # Potential EOFB sequence
            return curline, True
        elif mode == "P":  # Pass mode
            x1 = curpos + 1
            while x1 < width:
                if x1 == 0:
                    if color == 1 and refline[x1] != color:
                        break
                elif refline[x1 - 1] == color and refline[x1] != color:
                    break
                x1 += 1
            while x1 < width:
                if x1 == 0:
                    if color == 0 and refline[x1] == color:
                        break
                elif refline[x1 - 1] != color and refline[x1] == color:
                    break
                x1 += 1
            for x in range(max(0, curpos), min(width, x1)):
                curline[x] = color
            curpos = x1
        elif mode == "H":  # Horizontal mode
            tree1 = _WHITE_TREE if color == 1 else _BLACK_TREE
            n1 = _read_run(reader, tree1)
            tree2 = _BLACK_TREE if color == 1 else _WHITE_TREE
            n2 = _read_run(reader, tree2)

            if curpos < 0:
                curpos = 0
            x = curpos
            for _ in range(n1):
                if x >= width:
                    break
                curline[x] = color
                x += 1
            for _ in range(n2):
                if x >= width:
                    break
                curline[x] = 1 - color
                x += 1
            curpos = x
        elif isinstance(mode, int):  # Vertical mode dx
            dx = mode
            x1 = curpos + 1
            while x1 < width:
                if x1 == 0:
                    if color == 1 and refline[x1] != color:
                        break
                elif refline[x1 - 1] == color and refline[x1] != color:
                    break
                x1 += 1
            target_x = max(0, min(width, x1 + dx))
            x0 = max(0, curpos)
            if target_x < x0:
                for x in range(target_x, x0):
                    curline[x] = color
            elif x0 < target_x:
                for x in range(x0, target_x):
                    curline[x] = color
            curpos = target_x
            color = 1 - color
        else:
            break

    return curline, False


def ccitt_decode(
    data: bytes,
    params: Optional[Union[dict[str, Any], PDFDict]] = None,
) -> bytes:
    """Decompress CCITT Group 3 or Group 4 facsimile stream payload.

    Args:
        data: Compressed CCITT bitstream.
        params: Stream /DecodeParms dictionary containing filter parameters.

    Returns:
        bytes: Raw unpacked bilevel image bytes aligned to row strides.
    """
    if not data:
        return b""

    # Extract parameters adhering to ISO 32000-1 §7.4.6 Table 9
    k = 0
    columns = 1728
    rows = 0
    end_of_line = False
    encoded_byte_align = False
    end_of_block = True
    black_is_1 = False

    if params is not None:
        k_val = params.get("K", 0)
        k = int(k_val) if isinstance(k_val, (int, float)) else 0

        cols_val = params.get("Columns", 1728)
        columns = int(cols_val) if isinstance(cols_val, (int, float)) else 1728

        rows_val = params.get("Rows", 0)
        rows = int(rows_val) if isinstance(rows_val, (int, float)) else 0

        end_of_line = bool(params.get("EndOfLine", False))
        encoded_byte_align = bool(params.get("EncodedByteAlign", False))
        end_of_block = bool(params.get("EndOfBlock", True))
        black_is_1 = bool(params.get("BlackIs1", False))

    if columns <= 0:
        columns = 1728

    reader = _CCITTBitReader(data)
    out_rows: List[bytes] = []
    refline = [1] * columns
    current_y = 0

    # Group 4 (2D, K < 0)
    if k < 0:
        while True:
            if rows > 0 and current_y >= rows:
                break
            if reader.is_eof and current_y > 0:
                break

            curline, is_eofb = _decode_2d_row(reader, refline, columns)
            if is_eofb and end_of_block:
                break

            out_rows.append(_pack_bits_to_row(curline, columns, black_is_1))
            refline = curline
            current_y += 1

            if encoded_byte_align:
                reader.align_to_byte()

    # Group 3 1D (K == 0)
    elif k == 0:
        while True:
            if rows > 0 and current_y >= rows:
                break
            if reader.is_eof and current_y > 0:
                break

            curline = _decode_1d_row(reader, columns)
            out_rows.append(_pack_bits_to_row(curline, columns, black_is_1))
            current_y += 1

            if encoded_byte_align:
                reader.align_to_byte()

    # Group 3 2D (K > 0)
    else:
        k_counter = 0
        while True:
            if rows > 0 and current_y >= rows:
                break
            if reader.is_eof and current_y > 0:
                break

            # In Group 3 2D, line begins with 1-D if k_counter == 0, else 1-bit tag
            is_1d = (k_counter == 0)
            if not is_1d:
                tag = reader.read_bit()
                is_1d = (tag == 1)

            if is_1d:
                curline = _decode_1d_row(reader, columns)
                k_counter = k - 1
            else:
                curline, is_eofb = _decode_2d_row(reader, refline, columns)
                if is_eofb and end_of_block:
                    break
                k_counter -= 1

            out_rows.append(_pack_bits_to_row(curline, columns, black_is_1))
            refline = curline
            current_y += 1

            if encoded_byte_align:
                reader.align_to_byte()

    # Pad remaining rows with white scanlines if stream ended prematurely
    if rows > 0 and len(out_rows) < rows:
        blank_row = _pack_bits_to_row([1] * columns, columns, black_is_1)
        while len(out_rows) < rows:
            out_rows.append(blank_row)

    return b"".join(out_rows)


__all__ = ["ccitt_decode"]
