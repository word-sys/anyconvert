"""PDF object parser for composite and primitive data structures.

Parses arrays (`[...]`), dictionaries (`<<...>>`), streams (`stream...endstream`),
indirect references (`N M R`), and indirect object definitions (`N M obj...endobj`)
from lexical token streams.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

from anyconvert.common.reader import ByteReader
from anyconvert.exceptions import (
    PDFMalformedStreamError,
    PDFSyntaxError,
)
from anyconvert.pdf.lexer import Lexer, Token, TokenType


class PDFName(str):
    """Represents a PDF Name object (e.g. `/Type`, `/Font`)."""

    def __repr__(self) -> str:
        return f"PDFName('/{self}')"


@dataclass(frozen=True)
class PDFString:
    """Represents a PDF literal or hexadecimal string.

    Attributes:
        data: The decoded raw byte sequence.
        is_hex: True if originally represented as `<...>` hex string.
    """

    data: bytes
    is_hex: bool = False

    def as_text(self, encoding: str = "latin-1") -> str:
        """Decode string to Unicode text.

        Handles UTF-16BE (with byte order mark 0xFEFF) and UTF-8,
        falling back to the specified 8-bit encoding (Latin-1 / PDFDocEncoding).
        """
        if self.data.startswith(b"\xfe\xff"):
            return self.data[2:].decode("utf-16-be", errors="replace")
        if self.data.startswith(b"\xff\xfe"):
            return self.data[2:].decode("utf-16-le", errors="replace")
        try:
            return self.data.decode("utf-8")
        except UnicodeDecodeError:
            return self.data.decode(encoding, errors="replace")

    def __repr__(self) -> str:
        return f"PDFString({self.data!r}, is_hex={self.is_hex})"


@dataclass(frozen=True)
class PDFRef:
    """Represents an indirect reference `obj_num gen_num R`."""

    obj_num: int
    gen_num: int

    def __repr__(self) -> str:
        return f"PDFRef({self.obj_num} {self.gen_num} R)"


@dataclass
class PDFStream:
    """Represents a PDF stream object `<< /Length ... >> stream ... endstream`.

    Attributes:
        dictionary: The stream metadata dictionary.
        raw_data: Zero-copy memoryview slice of the raw stream data.
        offset: Stream data byte offset in the underlying buffer.
    """

    dictionary: Dict[str, Any]
    raw_data: memoryview
    offset: int = 0

    @property
    def length(self) -> int:
        """Byte length of raw stream data."""
        return len(self.raw_data)

    def to_bytes(self) -> bytes:
        """Convert raw stream memoryview to bytes."""
        return bytes(self.raw_data)


@dataclass
class PDFIndirectObject:
    """Represents an indirect object definition `N M obj ... endobj`.

    Attributes:
        obj_num: Object number.
        gen_num: Generation number.
        value: Parsed object payload (Dict, Array, Stream, Number, etc.).
        offset: Byte offset in the file where object definition begins.
    """

    obj_num: int
    gen_num: int
    value: Any
    offset: int = 0

    def __repr__(self) -> str:
        return f"PDFIndirectObject({self.obj_num} {self.gen_num} obj: {type(self.value).__name__})"


class Parser:
    """Parser for decoding PDF objects from a Lexer."""

    __slots__ = ("_lexer", "_reader")

    def __init__(self, lexer: Union[Lexer, ByteReader, bytes, memoryview]) -> None:
        if isinstance(lexer, Lexer):
            self._lexer = lexer
        else:
            self._lexer = Lexer(lexer)
        self._reader: ByteReader = self._lexer.reader

    @property
    def lexer(self) -> Lexer:
        """Access the underlying Lexer."""
        return self._lexer

    @property
    def reader(self) -> ByteReader:
        """Access the underlying ByteReader."""
        return self._reader

    # --------------------------------------------------------------------------
    # Main Object Dispatcher
    # --------------------------------------------------------------------------

    def parse_object(self) -> Any:
        """Parse and return the next complete PDF object.

        Returns:
            One of: int, float, bool, None, PDFName, PDFString,
            List[Any], Dict[str, Any], PDFStream, PDFRef, PDFIndirectObject.
        """
        tok = self._lexer.next_token()
        if tok.type == TokenType.EOF:
            return None

        # ----------------------------------------------------------------------
        # 1. Primitives: Booleans, Numbers, Strings, Names, Null
        # ----------------------------------------------------------------------
        if tok.type == TokenType.BOOLEAN:
            return tok.value

        if tok.type == TokenType.REAL:
            return tok.value

        if tok.type == TokenType.STRING_LITERAL:
            return PDFString(tok.value, is_hex=False)

        if tok.type == TokenType.STRING_HEX:
            return PDFString(tok.value, is_hex=True)

        if tok.type == TokenType.NAME:
            return PDFName(tok.value)

        if tok.type == TokenType.KEYWORD:
            if tok.value is None or tok.value == "null":
                return None
            return tok.value

        # ----------------------------------------------------------------------
        # 2. Integers: Can be plain int, PDFRef (X Y R), or PDFIndirectObject (X Y obj)
        # ----------------------------------------------------------------------
        if tok.type == TokenType.INTEGER:
            return self._parse_integer_or_reference_or_object(tok)

        # ----------------------------------------------------------------------
        # 3. Delimiters: Array [ ... ], Dictionary << ... >>
        # ----------------------------------------------------------------------
        if tok.type == TokenType.DELIMITER:
            if tok.value == "[":
                return self.parse_array()
            if tok.value == "<<":
                return self.parse_dictionary_or_stream()
            if tok.value in ("]", ">>"):
                raise PDFSyntaxError(
                    f"Unexpected closing delimiter {tok.value!r}", offset=tok.offset
                )

        raise PDFSyntaxError(f"Unexpected token {tok.value!r}", offset=tok.offset)

    # --------------------------------------------------------------------------
    # Integer, Reference, or Indirect Object Resolver
    # --------------------------------------------------------------------------

    def _parse_integer_or_reference_or_object(self, first_tok: Token) -> Any:
        """Resolve whether an integer is a standalone number, a reference, or an object."""
        tok2 = self._lexer.next_token()
        if tok2.type == TokenType.INTEGER:
            tok3 = self._lexer.next_token()
            if tok3.type == TokenType.KEYWORD:
                if tok3.value == "R":
                    # X Y R -> PDFRef
                    return PDFRef(first_tok.value, tok2.value)
                if tok3.value == "obj":
                    # X Y obj -> PDFIndirectObject
                    return self._parse_indirect_object(first_tok.value, tok2.value, first_tok.offset)

            # Not a reference or object, push back tok3 and tok2
            self._lexer.push_token(tok3)
            self._lexer.push_token(tok2)
            return first_tok.value

        # Not an integer following first integer, push back tok2
        self._lexer.push_token(tok2)
        return first_tok.value

    def _parse_indirect_object(self, obj_num: int, gen_num: int, offset: int) -> PDFIndirectObject:
        """Parse the body of an indirect object definition up to `endobj`."""
        value = self.parse_object()

        # Consume trailing 'endobj' keyword if present
        tok = self._lexer.next_token()
        if tok.type == TokenType.KEYWORD and tok.value == "endobj":
            pass
        elif tok.type != TokenType.EOF:
            # Tolerant parser: some generators omit endobj after stream
            self._lexer.push_token(tok)

        return PDFIndirectObject(
            obj_num=obj_num,
            gen_num=gen_num,
            value=value,
            offset=offset,
        )

    # --------------------------------------------------------------------------
    # Array & Dictionary Parsing
    # --------------------------------------------------------------------------

    def parse_array(self) -> List[Any]:
        """Parse an array `[ ... ]`."""
        elements: List[Any] = []
        while True:
            tok = self._lexer.peek_token()
            if tok.type == TokenType.EOF:
                raise PDFSyntaxError("Unterminated array at EOF")
            if tok.type == TokenType.DELIMITER and tok.value == "]":
                self._lexer.next_token()  # consume ']'
                break
            elements.append(self.parse_object())
        return elements

    def parse_dictionary_or_stream(self) -> Union[Dict[str, Any], PDFStream]:
        """Parse a dictionary `<< ... >>`, and check if followed by a stream."""
        d: Dict[str, Any] = {}

        while True:
            tok = self._lexer.next_token()
            if tok.type == TokenType.EOF:
                raise PDFSyntaxError("Unterminated dictionary at EOF")
            if tok.type == TokenType.DELIMITER and tok.value == ">>":
                break

            if tok.type != TokenType.NAME:
                raise PDFSyntaxError(
                    f"Dictionary key must be a Name, received: {tok.value!r}",
                    offset=tok.offset,
                )

            key = str(tok.value)
            val = self.parse_object()
            d[key] = val

        # Check if immediately followed by 'stream'
        peek = self._lexer.peek_token()
        if peek.type == TokenType.KEYWORD and peek.value == "stream":
            self._lexer.next_token()  # consume 'stream' keyword
            return self.parse_stream(d)

        return d

    # --------------------------------------------------------------------------
    # Stream Content Isolation
    # --------------------------------------------------------------------------

    def parse_stream(self, stream_dict: Dict[str, Any]) -> PDFStream:
        """Isolate binary stream data following `stream` keyword up to `endstream`.

        PDF 32000-1 specification requires `stream` to be followed by CRLF or LF.
        Data terminates at `endstream`.
        """
        reader = self._reader

        # Advance past newline immediately following 'stream'
        # Can be \r\n or \n or \r
        b = reader.peek_byte()
        if b == 0x0D:  # CR
            reader.read_byte()
            if reader.peek_byte() == 0x0A:  # CRLF
                reader.read_byte()
        elif b == 0x0A:  # LF
            reader.read_byte()

        stream_start = reader.position

        # Try using /Length from stream dictionary if directly available as an integer
        length_val = stream_dict.get("Length")
        if isinstance(length_val, int) and length_val >= 0:
            candidate_end = stream_start + length_val
            if candidate_end <= len(reader):
                # Verify whether 'endstream' follows candidate_end (skipping optional whitespace/newlines)
                test_pos = candidate_end
                while test_pos < len(reader) and reader.peek_byte(test_pos - reader.position) in (0x0D, 0x0A, 0x20):
                    test_pos += 1

                test_window = bytes(reader.slice(test_pos, test_pos + 9))
                if test_window.startswith(b"endstream"):
                    raw_data = reader.slice(stream_start, candidate_end)
                    reader.seek(test_pos + 9)  # advance past 'endstream'
                    return PDFStream(dictionary=stream_dict, raw_data=raw_data, offset=stream_start)

        # Fallback: Scan forward for b"endstream"
        end_idx = reader.find(b"endstream", start=stream_start)
        if end_idx == -1:
            raise PDFMalformedStreamError(
                "Could not find 'endstream' marker for stream",
                offset=stream_start,
            )

        # Strip trailing \r\n, \n, or \r before endstream per PDF specification
        stream_end = end_idx
        if stream_end > stream_start:
            if reader.peek_byte(stream_end - 1 - reader.position) == 0x0A:
                stream_end -= 1
                if stream_end > stream_start and reader.peek_byte(stream_end - 1 - reader.position) == 0x0D:
                    stream_end -= 1
            elif reader.peek_byte(stream_end - 1 - reader.position) == 0x0D:
                stream_end -= 1

        raw_data = reader.slice(stream_start, stream_end)
        reader.seek(end_idx + 9)  # advance past 'endstream'

        return PDFStream(
            dictionary=stream_dict,
            raw_data=raw_data,
            offset=stream_start,
        )


__all__ = [
    "PDFName",
    "PDFString",
    "PDFRef",
    "PDFStream",
    "PDFIndirectObject",
    "Parser",
]
