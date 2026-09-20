"""Stream-based /ToUnicode CMap parser and character translator.

Adheres to ISO 32000-1 §9.10:
- Parses /ToUnicode CMaps containing begincodespacerange, beginbfchar, and beginbfrange.
- Decodes UTF-16BE hex strings, multi-character ligatures, and surrogate pairs (U+10000+).
- Supports both linear range (Form A) and array range (Form B) bfrange definitions.
- Provides string decoding for PDF content stream operands (Tj, TJ).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union


@dataclass(slots=True)
class CodeSpaceRange:
    """Represents a valid input character code space range."""

    low: int
    high: int
    byte_len: int

    def contains(self, code: int) -> bool:
        """Return True if code falls within this range."""
        return self.low <= code <= self.high


def decode_cmap_hex(hex_token: str) -> str:
    """Decode a CMap hex string token (<...>) to Unicode string.

    Supports:
    - Standard 2-byte UTF-16BE (e.g., '<0041>' -> 'A')
    - 4-byte surrogate pairs (e.g., '<D83DDE00>' -> '😀')
    - Multi-character ligatures (e.g., '<00460046>' -> 'FF')
    - 1-byte ASCII hex fallback (e.g., '<41>' -> 'A')

    Args:
        hex_token: Hex string with or without enclosing angle brackets.

    Returns:
        str: Decoded Unicode string.
    """
    clean = re.sub(r"[^0-9a-fA-F]", "", hex_token)
    if not clean:
        return ""

    if len(clean) % 2 != 0:
        clean = "0" + clean

    raw = bytes.fromhex(clean)

    # 1. Standard UTF-16BE decoding
    if len(raw) % 2 == 0:
        try:
            return raw.decode("utf-16be")
        except UnicodeDecodeError:
            pass

    # 2. 1-byte Latin-1 / ASCII fallback
    if len(raw) == 1:
        return chr(raw[0])

    try:
        return raw.decode("utf-16be", errors="replace")
    except Exception:
        return raw.decode("latin-1", errors="replace")


class CMap:
    """Parsed /ToUnicode CMap mapping character codes to Unicode strings."""

    __slots__ = (
        "name",
        "cmap_type",
        "codespaces",
        "mapping",
        "_max_code",
    )

    def __init__(
        self,
        name: str = "Custom-ToUnicode",
        cmap_type: int = 2,
    ) -> None:
        self.name: str = name
        self.cmap_type: int = cmap_type
        self.codespaces: List[CodeSpaceRange] = []
        self.mapping: Dict[int, str] = {}
        self._max_code: int = 0

    def add_codespace(self, low: int, high: int, byte_len: int) -> None:
        """Register a valid codespace range."""
        self.codespaces.append(CodeSpaceRange(low=low, high=high, byte_len=byte_len))

    def add_char(self, char_code: int, unicode_str: str) -> None:
        """Register a single character mapping."""
        self.mapping[char_code] = unicode_str
        if char_code > self._max_code:
            self._max_code = char_code

    def to_unicode(self, char_code: int) -> Optional[str]:
        """Lookup Unicode translation for character code."""
        return self.mapping.get(char_code)

    def decode_string(self, data: bytes) -> str:
        """Decode binary PDF string data to Unicode using this CMap.

        Partitions raw byte stream into character code tokens using defined codespaces
        or code value heuristics.

        Args:
            data: Raw content stream string bytes.

        Returns:
            str: Decoded Unicode string.
        """
        if not data:
            return ""

        out: List[str] = []
        pos = 0
        length = len(data)

        # Sort codespaces by byte length descending (match longer tokens first)
        sorted_codespaces = sorted(self.codespaces, key=lambda cs: cs.byte_len, reverse=True)

        while pos < length:
            matched = False

            if sorted_codespaces:
                for cs in sorted_codespaces:
                    blen = cs.byte_len
                    if pos + blen <= length:
                        code = int.from_bytes(data[pos : pos + blen], "big")
                        if cs.contains(code):
                            char = self.to_unicode(code)
                            if char is not None:
                                out.append(char)
                            elif blen == 1:
                                out.append(chr(code))
                            else:
                                out.append("\ufffd")
                            pos += blen
                            matched = True
                            break

            if not matched:
                # Heuristic fallback when codespace range is missing or unmatched
                if self._max_code > 255 and pos + 2 <= length:
                    code = int.from_bytes(data[pos : pos + 2], "big")
                    char = self.to_unicode(code)
                    if char is not None:
                        out.append(char)
                    else:
                        out.append("\ufffd")
                    pos += 2
                else:
                    code = data[pos]
                    char = self.to_unicode(code)
                    if char is not None:
                        out.append(char)
                    else:
                        out.append(chr(code))
                    pos += 1

        return "".join(out)

    @classmethod
    def parse(cls, stream_data: Union[bytes, str]) -> CMap:
        """Parse /ToUnicode CMap PostScript stream data.

        Args:
            stream_data: Raw byte stream or string containing CMap definition.

        Returns:
            CMap: Populated CMap instance.
        """
        if isinstance(stream_data, bytes):
            text = stream_data.decode("latin-1", errors="replace")
        else:
            text = stream_data

        cmap = cls()

        # Extract /CMapName
        name_match = re.search(r"/CMapName\s+/([^\s]+)", text)
        if name_match:
            cmap.name = name_match.group(1)

        # Extract /CMapType
        type_match = re.search(r"/CMapType\s+(\d+)", text)
        if type_match:
            try:
                cmap.cmap_type = int(type_match.group(1))
            except ValueError:
                pass

        # Tokenize ignoring comments (% ...)
        tokens = _tokenize_cmap(text)
        _parse_cmap_tokens(cmap, tokens)

        return cmap


def _tokenize_cmap(text: str) -> List[str]:
    """Tokenize CMap body into hex strings, delimiters, and keywords."""
    # Match:
    # 1. Hex string: <...>
    # 2. Literal string: (...)
    # 3. Delimiters: [ or ]
    # 4. Comments: %... (will be skipped)
    # 5. Non-whitespace tokens
    pattern = re.compile(r"<[^>]*>|\([^\)]*\)|\[|\]|%[^\r\n]*|[^\s<>[\]()%]+")
    tokens: List[str] = []

    for m in pattern.finditer(text):
        tok = m.group(0)
        if tok.startswith("%"):
            continue
        tokens.append(tok)

    return tokens


def _strip_hex(tok: str) -> str:
    """Strip '<' and '>' and whitespace from hex token."""
    if tok.startswith("<") and tok.endswith(">"):
        tok = tok[1:-1]
    return re.sub(r"[^0-9a-fA-F]", "", tok)


def _parse_cmap_tokens(cmap: CMap, tokens: List[str]) -> None:
    """Evaluate CMap token stream populating codespaces, bfchar, and bfrange."""
    idx = 0
    num_tokens = len(tokens)

    while idx < num_tokens:
        tok = tokens[idx]
        idx += 1

        if tok == "begincodespacerange":
            while idx < num_tokens and tokens[idx] != "endcodespacerange":
                if idx + 1 < num_tokens:
                    low_hex = _strip_hex(tokens[idx])
                    high_hex = _strip_hex(tokens[idx + 1])
                    idx += 2
                    if low_hex and high_hex:
                        try:
                            low = int(low_hex, 16)
                            high = int(high_hex, 16)
                            byte_len = max(1, len(low_hex) // 2)
                            cmap.add_codespace(low, high, byte_len)
                        except ValueError:
                            pass
                else:
                    idx += 1

        elif tok == "beginbfchar":
            while idx < num_tokens and tokens[idx] != "endbfchar":
                if idx + 1 < num_tokens:
                    src_tok = tokens[idx]
                    dst_tok = tokens[idx + 1]
                    idx += 2
                    src_hex = _strip_hex(src_tok)
                    if src_hex:
                        try:
                            src_code = int(src_hex, 16)
                            dst_str = _decode_dst_token(dst_tok)
                            cmap.add_char(src_code, dst_str)
                        except ValueError:
                            pass
                else:
                    idx += 1

        elif tok == "beginbfrange":
            while idx < num_tokens and tokens[idx] != "endbfrange":
                if idx + 2 < num_tokens:
                    src1_hex = _strip_hex(tokens[idx])
                    src2_hex = _strip_hex(tokens[idx + 1])
                    next_tok = tokens[idx + 2]
                    idx += 3

                    if src1_hex and src2_hex:
                        try:
                            src1 = int(src1_hex, 16)
                            src2 = int(src2_hex, 16)
                        except ValueError:
                            continue

                        if next_tok == "[":
                            # Array Form: <src1> <src2> [ <dst1> <dst2> ... ]
                            arr_tokens: List[str] = []
                            while idx < num_tokens and tokens[idx] != "]":
                                arr_tokens.append(tokens[idx])
                                idx += 1
                            if idx < num_tokens and tokens[idx] == "]":
                                idx += 1

                            for offset, dst_tok in enumerate(arr_tokens):
                                code = src1 + offset
                                if code <= src2:
                                    dst_str = _decode_dst_token(dst_tok)
                                    cmap.add_char(code, dst_str)

                        else:
                            # Linear Range Form: <src1> <src2> <dstStart>
                            dst_hex = _strip_hex(next_tok)
                            if dst_hex:
                                _expand_bfrange_linear(cmap, src1, src2, dst_hex)
                else:
                    idx += 1


def _decode_dst_token(tok: str) -> str:
    """Decode destination token which may be a hex string or literal string."""
    if tok.startswith("<") and tok.endswith(">"):
        return decode_cmap_hex(tok)
    if tok.startswith("(") and tok.endswith(")"):
        return tok[1:-1]
    return tok


def _expand_bfrange_linear(cmap: CMap, src1: int, src2: int, dst_hex: str) -> None:
    """Expand linear <src1> <src2> <dstStart> bfrange into cmap mappings."""
    if len(dst_hex) % 2 != 0:
        dst_hex = "0" + dst_hex

    raw_bytes = bytes.fromhex(dst_hex)
    byte_count = len(raw_bytes)

    if byte_count == 2:
        # Standard 2-byte UTF-16 code point
        start_val = int.from_bytes(raw_bytes, "big")
        for code in range(src1, src2 + 1):
            cur_val = start_val + (code - src1)
            if cur_val <= 0xFFFF:
                cmap.add_char(code, chr(cur_val))
            else:
                # Carried past BMP: encode as 4-byte surrogate
                cur_bytes = cur_val.to_bytes(4, "big")
                cmap.add_char(code, cur_bytes.decode("utf-16be", errors="replace"))

    elif byte_count == 4:
        # Check if single UTF-16 surrogate pair (e.g. U+10000..U+10FFFF)
        decoded = raw_bytes.decode("utf-16be", errors="ignore")
        if len(decoded) == 1:
            start_cp = ord(decoded[0])
            for code in range(src1, src2 + 1):
                cp = start_cp + (code - src1)
                if 0 <= cp <= 0x10FFFF:
                    cmap.add_char(code, chr(cp))
        else:
            # Multi-character or raw integer increment
            start_val = int.from_bytes(raw_bytes, "big")
            for code in range(src1, src2 + 1):
                cur_val = start_val + (code - src1)
                cur_bytes = cur_val.to_bytes(4, "big")
                cmap.add_char(code, cur_bytes.decode("utf-16be", errors="replace"))

    else:
        # Generic big-endian byte-increment fallback
        start_val = int.from_bytes(raw_bytes, "big")
        for code in range(src1, src2 + 1):
            cur_val = start_val + (code - src1)
            cur_bytes = cur_val.to_bytes(byte_count, "big")
            if byte_count % 2 == 0:
                cmap.add_char(code, cur_bytes.decode("utf-16be", errors="replace"))
            else:
                cmap.add_char(code, chr(cur_val & 0xFF))
