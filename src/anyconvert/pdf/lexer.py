"""PDF lexical analyzer and tokenizer.

Tokenizes raw PDF byte streams into typed tokens according to PDF 32000-1 §7.2:
- Whitespace and comment handling.
- Balanced nested parentheses in literal strings.
- Escape sequence and octal sequence decoding in strings.
- Hexadecimal strings with odd-nibble zero padding.
- Names with #XX hexadecimal escape decoding.
- Numbers, booleans, keywords, and structural delimiters.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Optional, Sequence

from anyconvert.common.reader import PDF_DELIMITERS, PDF_WHITESPACE, ByteReader
from anyconvert.exceptions import PDFSyntaxError


class TokenType(Enum):
    """Enumeration of lexical token types in PDF syntax."""

    BOOLEAN = auto()
    NUMBER = auto()
    STRING = auto()
    HEX_STRING = auto()
    NAME = auto()
    KEYWORD = auto()
    DELIMITER = auto()
    EOF = auto()


@dataclass(frozen=True, slots=True)
class Token:
    """Represents a lexical token.

    Attributes:
        type: The category of token.
        value: Decoded Python value (bool, int, float, str, bytes).
        raw_bytes: Raw byte slice from the stream representing this token.
        offset: Byte offset in the file where this token began.
    """

    type: TokenType
    value: Any
    raw_bytes: bytes
    offset: int

    def __repr__(self) -> str:
        return f"Token(type={self.type.name}, value={self.value!r}, offset={self.offset})"


class PDFLexer:
    """High-performance lexical analyzer for PDF streams backed by ByteReader."""

    __slots__ = ("_reader", "_peeked")

    def __init__(self, reader: ByteReader | bytes | bytearray | memoryview) -> None:
        """Initialize PDFLexer.

        Args:
            reader: ByteReader instance or raw bytes to tokenize.
        """
        self._reader: ByteReader = (
            reader if isinstance(reader, ByteReader) else ByteReader(reader)
        )
        self._peeked: Optional[Token] = None

    @property
    def reader(self) -> ByteReader:
        """Underlying ByteReader instance."""
        return self._reader

    def peek_token(self) -> Token:
        """Return the next token without advancing the lexer cursor."""
        if self._peeked is None:
            self._peeked = self.next_token()
        return self._peeked

    def next_token(self) -> Token:
        """Consume and return the next token from the stream.

        Returns:
            Token: Next token, or EOF token if end of stream is reached.

        Raises:
            PDFSyntaxError: If token syntax is invalid.
        """
        if self._peeked is not None:
            tok = self._peeked
            self._peeked = None
            return tok

        reader = self._reader
        reader.skip_whitespace_and_comments()

        if reader.is_eof:
            return Token(TokenType.EOF, None, b"", reader.pos)

        offset = reader.pos
        b = reader.peek_byte()
        assert b is not None

        # 1. String literal: (...)
        if b == 0x28:  # '('
            return self._scan_literal_string()

        # 2. Dictionary delimiter << or Hex String <...>
        if b == 0x3C:  # '<'
            if reader.match(b"<<", consume=True):
                return Token(TokenType.DELIMITER, "<<", b"<<", offset)
            return self._scan_hex_string()

        # 3. Dictionary close >>
        if b == 0x3E:  # '>'
            if reader.match(b">>", consume=True):
                return Token(TokenType.DELIMITER, ">>", b">>", offset)
            # Standalone '>' is unexpected outside hex string or dictionary
            reader.read_byte()
            raise PDFSyntaxError(f"Unexpected delimiter '>' at offset {offset}", offset=offset)

        # 4. Array delimiters [ and ]
        if b == 0x5B:  # '['
            reader.read_byte()
            return Token(TokenType.DELIMITER, "[", b"[", offset)
        if b == 0x5D:  # ']'
            reader.read_byte()
            return Token(TokenType.DELIMITER, "]", b"]", offset)

        # 5. Name: /Name
        if b == 0x2F:  # '/'
            return self._scan_name()

        # 6. Numeric or Keyword / Identifier
        return self._scan_number_or_keyword()

    def _scan_literal_string(self) -> Token:
        """Scan a literal string enclosed in parentheses: (Text with (nested) parens)."""
        reader = self._reader
        start_offset = reader.pos
        # Consume initial '('
        reader.read_byte()

        depth = 1
        out = bytearray()

        while not reader.is_eof:
            b = reader.read_byte()

            if b == 0x28:  # '('
                depth += 1
                out.append(b)
            elif b == 0x29:  # ')'
                depth -= 1
                if depth == 0:
                    raw = bytes(reader.slice(start_offset, reader.pos))
                    return Token(TokenType.STRING, bytes(out), raw, start_offset)
                out.append(b)
            elif b == 0x5C:  # '\' escape sequence
                if reader.is_eof:
                    break
                esc = reader.read_byte()
                if esc == 0x6E:  # \n
                    out.append(0x0A)
                elif esc == 0x72:  # \r
                    out.append(0x0D)
                elif esc == 0x74:  # \t
                    out.append(0x09)
                elif esc == 0x62:  # \b
                    out.append(0x08)
                elif esc == 0x66:  # \f
                    out.append(0x0C)
                elif esc == 0x28:  # \(
                    out.append(0x28)
                elif esc == 0x29:  # \)
                    out.append(0x29)
                elif esc == 0x5C:  # \\
                    out.append(0x5C)
                elif 0x30 <= esc <= 0x37:  # Octal escape \ddd (1 to 3 digits)
                    octal_digits = [esc]
                    for _ in range(2):
                        nxt = reader.peek_byte()
                        if nxt is not None and 0x30 <= nxt <= 0x37:
                            octal_digits.append(reader.read_byte())
                        else:
                            break
                    octal_val = int(bytes(octal_digits).decode("ascii"), 8)
                    out.append(octal_val & 0xFF)
                elif esc in (0x0A, 0x0D):  # Line continuation: '\' followed by newline
                    if esc == 0x0D and reader.peek_byte() == 0x0A:
                        reader.read_byte()  # Consume LF of CRLF
                    # Discard both backslash and newline
                    continue
                else:
                    # An unrecognized escape sequence: omit the backslash and retain the character
                    out.append(esc)
            else:
                out.append(b)

        raise PDFSyntaxError(
            f"Unterminated literal string starting at offset {start_offset}",
            offset=start_offset,
        )

    def _scan_hex_string(self) -> Token:
        """Scan a hexadecimal string enclosed in <...>: <48656C6C6F>."""
        reader = self._reader
        start_offset = reader.pos
        # Consume initial '<'
        reader.read_byte()

        hex_chars = bytearray()
        while not reader.is_eof:
            b = reader.read_byte()
            if b == 0x3E:  # '>'
                # Found end of hex string
                # If odd number of digits, append '0' per PDF specification
                if len(hex_chars) % 2 != 0:
                    hex_chars.append(0x30)  # '0'
                try:
                    decoded = bytes.fromhex(hex_chars.decode("ascii"))
                except ValueError as err:
                    raise PDFSyntaxError(
                        f"Malformed hex string at offset {start_offset}: {err}",
                        offset=start_offset,
                    ) from err

                raw = bytes(reader.slice(start_offset, reader.pos))
                return Token(TokenType.HEX_STRING, decoded, raw, start_offset)
            elif b in PDF_WHITESPACE:
                # Whitespace inside hex strings is ignored
                continue
            elif (0x30 <= b <= 0x39) or (0x41 <= b <= 0x46) or (0x61 <= b <= 0x66):
                # 0-9, A-F, a-f
                hex_chars.append(b)
            else:
                raise PDFSyntaxError(
                    f"Invalid character in hex string at offset {reader.pos - 1}: {chr(b)!r}",
                    offset=reader.pos - 1,
                )

        raise PDFSyntaxError(
            f"Unterminated hex string starting at offset {start_offset}",
            offset=start_offset,
        )

    def _scan_name(self) -> Token:
        """Scan a PDF Name token: /Name#20With#20Spaces."""
        reader = self._reader
        start_offset = reader.pos
        # Consume initial '/'
        reader.read_byte()

        name_bytes = bytearray()
        while not reader.is_eof:
            b = reader.peek_byte()
            assert b is not None
            if b in PDF_WHITESPACE or b in PDF_DELIMITERS:
                break

            reader.read_byte()
            if b == 0x23:  # '#' hex escape per PDF 1.2+
                if reader.remaining < 2:
                    name_bytes.append(b)
                    break
                h1 = reader.read_byte()
                h2 = reader.read_byte()
                try:
                    val = int(bytes([h1, h2]).decode("ascii"), 16)
                    name_bytes.append(val)
                except ValueError:
                    name_bytes.append(b)
                    name_bytes.append(h1)
                    name_bytes.append(h2)
            else:
                name_bytes.append(b)

        # Decode as utf-8 or fallback to latin-1
        try:
            name_str = name_bytes.decode("utf-8")
        except UnicodeDecodeError:
            name_str = name_bytes.decode("latin-1")

        raw = bytes(reader.slice(start_offset, reader.pos))
        return Token(TokenType.NAME, name_str, raw, start_offset)

    def _scan_number_or_keyword(self) -> Token:
        """Scan numeric literal or keyword token."""
        reader = self._reader
        start_offset = reader.pos

        chars = bytearray()
        while not reader.is_eof:
            b = reader.peek_byte()
            assert b is not None
            if b in PDF_WHITESPACE or b in PDF_DELIMITERS:
                break
            chars.append(reader.read_byte())

        raw = bytes(reader.slice(start_offset, reader.pos))
        text = chars.decode("latin-1", errors="replace")

        # 1. Booleans
        if text == "true":
            return Token(TokenType.BOOLEAN, True, raw, start_offset)
        if text == "false":
            return Token(TokenType.BOOLEAN, False, raw, start_offset)

        # 2. Null
        if text == "null":
            return Token(TokenType.KEYWORD, "null", raw, start_offset)

        # 3. Numeric: integer or float
        # Fast numeric check
        if _is_numeric(text):
            try:
                if "." in text:
                    return Token(TokenType.NUMBER, float(text), raw, start_offset)
                return Token(TokenType.NUMBER, int(text), raw, start_offset)
            except ValueError:
                pass

        # 4. Keyword / Operator identifier
        return Token(TokenType.KEYWORD, text, raw, start_offset)


def _is_numeric(s: str) -> bool:
    """Check if string matches PDF numeric syntax (+/- digits . digits)."""
    if not s:
        return False
    # Check leading sign
    start = 1 if s[0] in ("+", "-") else 0
    if start >= len(s):
        return False

    has_dot = False
    has_digit = False

    for ch in s[start:]:
        if ch.isdigit():
            has_digit = True
        elif ch == ".":
            if has_dot:
                return False
            has_dot = True
        else:
            return False

    return has_digit
