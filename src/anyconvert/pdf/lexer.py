"""High-performance lexical scanner (tokenizer) for PDF documents.

Tokenizes raw PDF byte streams into typed lexical tokens:
- Booleans (`true`, `false`)
- Numbers (integers, floats)
- Literal strings with nested balanced parentheses and escape decoding
- Hexadecimal strings with whitespace ignoring and odd-nibble zero-padding
- Names with `#XX` hex character decoding
- Delimiters (`[`, `]`, `<<`, `>>`, `{`, `}`)
- Keywords (`obj`, `endobj`, `stream`, `endstream`, `xref`, `trailer`, `startxref`, `R`, `null`)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
import re
from typing import Any, List, Optional, Set, Tuple, Union

from anyconvert.common.reader import (
    PDF_DELIMITERS,
    PDF_WHITESPACE,
    ByteReader,
)
from anyconvert.exceptions import PDFSyntaxError


class TokenType(Enum):
    """Lexical token types defined by ISO 32000-1."""

    BOOLEAN = auto()
    INTEGER = auto()
    REAL = auto()
    STRING_LITERAL = auto()
    STRING_HEX = auto()
    NAME = auto()
    DELIMITER = auto()
    KEYWORD = auto()
    EOF = auto()


@dataclass(frozen=True)
class Token:
    """Represents a lexical token extracted from a PDF stream.

    Attributes:
        type: The category of token.
        value: The typed Python value of the token.
        offset: The byte offset in the stream where the token began.
        raw: The raw bytes corresponding to this token.
    """

    type: TokenType
    value: Any
    offset: int
    raw: bytes


# Pre-compiled regex for integer and float numbers
_INT_PATTERN = re.compile(rb"^[+-]?[0-9]+$")
_REAL_PATTERN = re.compile(rb"^[+-]?([0-9]+\.[0-9]*|\.[0-9]+)$")

# Recognized PDF structural keywords
PDF_KEYWORDS: Set[bytes] = {
    b"obj",
    b"endobj",
    b"stream",
    b"endstream",
    b"xref",
    b"trailer",
    b"startxref",
    b"R",
    b"null",
    b"true",
    b"false",
}


class Lexer:
    """PDF lexical scanner operating over zero-copy ByteReader."""

    __slots__ = ("_reader", "_pushed_tokens")

    def __init__(self, reader: Union[ByteReader, bytes, bytearray, memoryview]) -> None:
        self._reader: ByteReader = (
            reader if isinstance(reader, ByteReader) else ByteReader(reader)
        )
        self._pushed_tokens: List[Token] = []

    @property
    def reader(self) -> ByteReader:
        """Access the underlying ByteReader."""
        return self._reader

    @property
    def position(self) -> int:
        """Current stream position."""
        return self._reader.position

    def push_token(self, token: Token) -> None:
        """Push a token back into the stream for lookahead/backtracking."""
        self._pushed_tokens.append(token)

    def peek_token(self) -> Token:
        """Inspect the next token without consuming it."""
        tok = self.next_token()
        self.push_token(tok)
        return tok

    def skip_whitespace_and_comments(self) -> int:
        """Skip any whitespace and PDF comments."""
        return self._reader.skip_whitespace_and_comments()

    def next_token(self) -> Token:
        """Extract and return the next lexical token from the stream.

        Raises:
            PDFSyntaxError: If tokenization encounters invalid syntax.
        """
        if self._pushed_tokens:
            return self._pushed_tokens.pop()

        self.skip_whitespace_and_comments()

        if self._reader.is_eof:
            return Token(TokenType.EOF, None, self._reader.position, b"")

        start_offset = self._reader.position
        b = self._reader.read_byte()

        # ----------------------------------------------------------------------
        # 1. Delimiters: (), <>, [], {}
        # ----------------------------------------------------------------------

        # Literal String: (...)
        if b == 0x28:  # '('
            return self._scan_literal_string(start_offset)

        # Dictionary << or Hex String <...>
        if b == 0x3C:  # '<'
            next_b = self._reader.peek_byte()
            if next_b == 0x3C:  # '<<'
                self._reader.read_byte()  # consume second '<'
                return Token(TokenType.DELIMITER, "<<", start_offset, b"<<")
            return self._scan_hex_string(start_offset)

        # Dictionary >> or stray >
        if b == 0x3E:  # '>'
            next_b = self._reader.peek_byte()
            if next_b == 0x3E:  # '>>'
                self._reader.read_byte()  # consume second '>'
                return Token(TokenType.DELIMITER, ">>", start_offset, b">>")
            return Token(TokenType.DELIMITER, ">", start_offset, b">")

        # Array brackets: [ or ]
        if b == 0x5B:  # '['
            return Token(TokenType.DELIMITER, "[", start_offset, b"[")
        if b == 0x5D:  # ']'
            return Token(TokenType.DELIMITER, "]", start_offset, b"]")

        # Procedure braces: { or }
        if b == 0x7B:  # '{'
            return Token(TokenType.DELIMITER, "{", start_offset, b"{")
        if b == 0x7D:  # '}'
            return Token(TokenType.DELIMITER, "}", start_offset, b"}")

        # ----------------------------------------------------------------------
        # 2. Names: /Name
        # ----------------------------------------------------------------------
        if b == 0x2F:  # '/'
            return self._scan_name(start_offset)

        # ----------------------------------------------------------------------
        # 3. Regular Tokens: Numbers, Booleans, Keywords
        # ----------------------------------------------------------------------
        token_bytes = bytearray([b])
        while not self._reader.is_eof:
            peek = self._reader.peek_byte()
            if peek is None or peek in PDF_WHITESPACE or peek in PDF_DELIMITERS:
                break
            token_bytes.append(self._reader.read_byte())

        raw = bytes(token_bytes)

        # Boolean
        if raw == b"true":
            return Token(TokenType.BOOLEAN, True, start_offset, raw)
        if raw == b"false":
            return Token(TokenType.BOOLEAN, False, start_offset, raw)
        if raw == b"null":
            return Token(TokenType.KEYWORD, None, start_offset, raw)

        # Integer
        if _INT_PATTERN.match(raw):
            return Token(TokenType.INTEGER, int(raw), start_offset, raw)

        # Real / Float
        if _REAL_PATTERN.match(raw):
            return Token(TokenType.REAL, float(raw), start_offset, raw)

        # Keyword
        if raw in PDF_KEYWORDS:
            return Token(TokenType.KEYWORD, raw.decode("latin-1"), start_offset, raw)

        # Generic unclassified keyword / operator
        return Token(TokenType.KEYWORD, raw.decode("latin-1", errors="replace"), start_offset, raw)

    # --------------------------------------------------------------------------
    # Sub-Scanners for Complex Tokens
    # --------------------------------------------------------------------------

    def _scan_literal_string(self, start_offset: int) -> Token:
        """Scan a literal string `( ... )` handling nested parentheses and escapes."""
        result = bytearray()
        depth = 1

        while depth > 0:
            if self._reader.is_eof:
                raise PDFSyntaxError("Unterminated literal string at EOF", offset=start_offset)

            b = self._reader.read_byte()

            if b == 0x28:  # '('
                depth += 1
                result.append(b)
            elif b == 0x29:  # ')'
                depth -= 1
                if depth > 0:
                    result.append(b)
            elif b == 0x5C:  # '\\'
                if self._reader.is_eof:
                    break
                esc = self._reader.read_byte()
                if esc == 0x6E:  # \n
                    result.append(0x0A)
                elif esc == 0x72:  # \r
                    result.append(0x0D)
                elif esc == 0x74:  # \t
                    result.append(0x09)
                elif esc == 0x62:  # \b
                    result.append(0x08)
                elif esc == 0x66:  # \f
                    result.append(0x0C)
                elif esc == 0x28:  # \(
                    result.append(0x28)
                elif esc == 0x29:  # \)
                    result.append(0x29)
                elif esc == 0x5C:  # \\
                    result.append(0x5C)
                elif esc in (0x0A, 0x0D):  # Line continuation (\ followed by newline)
                    if esc == 0x0D and self._reader.peek_byte() == 0x0A:
                        self._reader.read_byte()  # consume \r\n
                elif 0x30 <= esc <= 0x37:  # Octal escape \ddd (1 to 3 digits)
                    octal_digits = bytearray([esc])
                    for _ in range(2):
                        nxt = self._reader.peek_byte()
                        if nxt is not None and 0x30 <= nxt <= 0x37:
                            octal_digits.append(self._reader.read_byte())
                        else:
                            break
                    octal_val = int(octal_digits, 8) & 0xFF
                    result.append(octal_val)
                else:
                    # An unrecognized escape character is treated as the character itself
                    result.append(esc)
            elif b == 0x0D:  # Convert bare CR in literal string to LF per spec
                if self._reader.peek_byte() == 0x0A:
                    self._reader.read_byte()
                result.append(0x0A)
            else:
                result.append(b)

        raw = bytes(self._reader.slice(start_offset, self._reader.position))
        return Token(TokenType.STRING_LITERAL, bytes(result), start_offset, raw)

    def _scan_hex_string(self, start_offset: int) -> Token:
        """Scan a hexadecimal string `< ... >` ignoring whitespace."""
        hex_digits = bytearray()

        while True:
            if self._reader.is_eof:
                raise PDFSyntaxError("Unterminated hexadecimal string at EOF", offset=start_offset)

            b = self._reader.read_byte()
            if b == 0x3E:  # '>'
                break
            if b in PDF_WHITESPACE:
                continue
            if (
                (0x30 <= b <= 0x39)  # 0-9
                or (0x41 <= b <= 0x46)  # A-F
                or (0x61 <= b <= 0x66)  # a-f
            ):
                hex_digits.append(b)
            else:
                raise PDFSyntaxError(
                    f"Invalid character in hexadecimal string: {chr(b)!r}",
                    offset=self._reader.position - 1,
                )

        # PDF Spec: Odd number of hex digits is padded with a trailing '0'
        if len(hex_digits) % 2 != 0:
            hex_digits.append(0x30)  # '0'

        result = bytes.fromhex(hex_digits.decode("ascii"))
        raw = bytes(self._reader.slice(start_offset, self._reader.position))
        return Token(TokenType.STRING_HEX, result, start_offset, raw)

    def _scan_name(self, start_offset: int) -> Token:
        """Scan a PDF Name token `/Name#20With#20Escapes`."""
        name_bytes = bytearray()

        while not self._reader.is_eof:
            peek = self._reader.peek_byte()
            if peek is None or peek in PDF_WHITESPACE or peek in PDF_DELIMITERS:
                break
            b = self._reader.read_byte()
            if b == 0x23:  # '#' hex escape sequence #XX
                hex_b1 = self._reader.read_byte() if not self._reader.is_eof else None
                hex_b2 = self._reader.read_byte() if not self._reader.is_eof else None
                if hex_b1 is not None and hex_b2 is not None:
                    try:
                        decoded_b = int(bytes([hex_b1, hex_b2]).decode("ascii"), 16)
                        name_bytes.append(decoded_b)
                        continue
                    except ValueError:
                        pass
                # Fallback if invalid hex escape
                name_bytes.append(0x23)
                if hex_b1 is not None:
                    name_bytes.append(hex_b1)
                if hex_b2 is not None:
                    name_bytes.append(hex_b2)
            else:
                name_bytes.append(b)

        # PDF names are commonly UTF-8 or Latin-1
        try:
            name_str = name_bytes.decode("utf-8")
        except UnicodeDecodeError:
            name_str = name_bytes.decode("latin-1")

        raw = bytes(self._reader.slice(start_offset, self._reader.position))
        return Token(TokenType.NAME, name_str, start_offset, raw)


__all__ = [
    "TokenType",
    "Token",
    "Lexer",
    "PDF_KEYWORDS",
]
