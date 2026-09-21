"""PDF object parser and AST definitions.

Parses tokenized streams into strictly typed PDF object models:
- Primitive scalars: PDFBool, PDFNumber, PDFString, PDFHexString, PDFName, PDFNull.
- Containers: PDFArray, PDFDict.
- References and Streams: PDFIndirectRef, PDFStream, PDFIndirectObject.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional, Sequence, Union

from anyconvert.common.reader import ByteReader
from anyconvert.exceptions import PDFSyntaxError
from anyconvert.pdf.lexer import PDFLexer, Token, TokenType


# =====================================================================
# PDF AST Object Models
# =====================================================================


@dataclass(frozen=True, slots=True)
class PDFNull:
    """Represents a PDF null object."""

    def __repr__(self) -> str:
        return "PDFNull()"


@dataclass(frozen=True, slots=True)
class PDFName:
    """Represents a PDF Name object (/Name)."""

    name: str

    def __str__(self) -> str:
        return f"/{self.name}"

    def __repr__(self) -> str:
        return f"PDFName({self.name!r})"

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, PDFName):
            return self.name == other.name
        if isinstance(other, str):
            clean = other[1:] if other.startswith("/") else other
            return self.name == clean
        return False

    def __hash__(self) -> int:
        return hash(self.name)


@dataclass(frozen=True, slots=True)
class PDFString:
    """Represents a PDF literal string (...)."""

    value: bytes

    def as_bytes(self) -> bytes:
        """Return the raw byte content of the string."""
        if isinstance(self.value, bytes):
            return self.value
        if isinstance(self.value, memoryview):
            return bytes(self.value)
        return str(self.value).encode("latin-1")

    def as_text(self) -> str:
        """Decode literal string to text handling BOM and PDFDocEncoding / UTF-16."""
        val = self.as_bytes()
        if val.startswith(b"\xfe\xff"):
            return val[2:].decode("utf-16-be", errors="replace")
        elif val.startswith(b"\xff\xfe"):
            return val[2:].decode("utf-16-le", errors="replace")
        elif val.startswith(b"\xef\xbb\xbf"):
            return val[3:].decode("utf-8", errors="replace")
        return val.decode("latin-1", errors="replace")

    def __repr__(self) -> str:
        return f"PDFString({self.value!r})"


@dataclass(frozen=True, slots=True)
class PDFHexString:
    """Represents a PDF hexadecimal string <...>."""

    value: bytes

    def as_bytes(self) -> bytes:
        """Return the decoded byte content of the hexadecimal string."""
        if isinstance(self.value, bytes):
            return self.value
        if isinstance(self.value, memoryview):
            return bytes(self.value)
        return str(self.value).encode("latin-1")

    def as_text(self) -> str:
        """Decode hex string to text handling BOM and encodings."""
        val = self.as_bytes()
        if val.startswith(b"\xfe\xff"):
            return val[2:].decode("utf-16-be", errors="replace")
        elif val.startswith(b"\xff\xfe"):
            return val[2:].decode("utf-16-le", errors="replace")
        elif val.startswith(b"\xef\xbb\xbf"):
            return val[3:].decode("utf-8", errors="replace")
        return val.decode("latin-1", errors="replace")

    def __repr__(self) -> str:
        return f"PDFHexString({self.value!r})"


@dataclass(frozen=True, slots=True)
class PDFIndirectRef:
    """Represents an indirect reference to an object (X Y R)."""

    obj_id: int
    generation: int

    def __repr__(self) -> str:
        return f"PDFIndirectRef({self.obj_id} {self.generation} R)"


class PDFArray(List[Any]):
    """Represents a PDF array [...]."""

    def __repr__(self) -> str:
        return f"PDFArray({super().__repr__()})"


class PDFDict(Dict[str, Any]):
    """Represents a PDF dictionary <<...>>.

    Allows accessing keys with or without leading '/' and with PDFName instances.
    """

    @staticmethod
    def _normalize_key(key: Union[str, PDFName]) -> str:
        if isinstance(key, PDFName):
            return key.name
        if isinstance(key, str):
            return key[1:] if key.startswith("/") else key
        raise TypeError(f"Invalid dictionary key type: {type(key).__name__}")

    def __getitem__(self, key: Union[str, PDFName]) -> Any:
        return super().__getitem__(self._normalize_key(key))

    def __setitem__(self, key: Union[str, PDFName], value: Any) -> None:
        super().__setitem__(self._normalize_key(key), value)

    def __contains__(self, key: object) -> bool:
        if isinstance(key, (str, PDFName)):
            return super().__contains__(self._normalize_key(key))
        return False

    def get(self, key: Union[str, PDFName], default: Any = None) -> Any:
        return super().get(self._normalize_key(key), default)

    def __repr__(self) -> str:
        inner = ", ".join(f"/{k}: {v!r}" for k, v in self.items())
        return f"PDFDict({{{inner}}})"


@dataclass
class PDFStream:
    """Represents a PDF stream object containing a dictionary and raw payload.

    Attributes:
        dict: The stream dictionary containing metadata (Length, Filter, etc.).
        data: Zero-copy memoryview of the raw compressed stream payload.
    """

    dict: PDFDict
    data: memoryview

    def get_raw_bytes(self) -> bytes:
        """Return stream content as bytes."""
        return bytes(self.data)


@dataclass
class PDFIndirectObject:
    """Represents an indirect object definition (X Y obj ... endobj)."""

    obj_id: int
    generation: int
    value: Any


PDFObject = Union[
    bool,
    int,
    float,
    str,
    PDFNull,
    PDFName,
    PDFString,
    PDFHexString,
    PDFArray,
    PDFDict,
    PDFIndirectRef,
    PDFStream,
    PDFIndirectObject,
]


# =====================================================================
# PDF Object Parser
# =====================================================================


class PDFParser:
    """Recursive-descent parser for PDF objects."""

    __slots__ = ("_lexer",)

    def __init__(self, lexer: PDFLexer | ByteReader | bytes | bytearray | memoryview) -> None:
        """Initialize parser with lexer or byte source."""
        if isinstance(lexer, PDFLexer):
            self._lexer: PDFLexer = lexer
        else:
            self._lexer = PDFLexer(lexer)

    @property
    def lexer(self) -> PDFLexer:
        """Underlying PDFLexer instance."""
        return self._lexer

    def parse_object(self) -> Optional[PDFObject]:
        """Parse and return the next top-level or nested PDF object.

        Returns:
            Optional[PDFObject]: Parsed object, or None if EOF.
        """
        tok = self._lexer.peek_token()
        if tok.type == TokenType.EOF:
            return None

        # 1. Null
        if tok.type == TokenType.KEYWORD and tok.value == "null":
            self._lexer.next_token()
            return PDFNull()

        # 2. Boolean
        if tok.type == TokenType.BOOLEAN:
            self._lexer.next_token()
            return bool(tok.value)

        # 3. String literal
        if tok.type == TokenType.STRING:
            self._lexer.next_token()
            return PDFString(value=tok.value)

        # 4. Hex string
        if tok.type == TokenType.HEX_STRING:
            self._lexer.next_token()
            return PDFHexString(value=tok.value)

        # 5. Name
        if tok.type == TokenType.NAME:
            self._lexer.next_token()
            return PDFName(name=tok.value)

        # 6. Array
        if tok.type == TokenType.DELIMITER and tok.value == "[":
            return self._parse_array()

        # 7. Dictionary
        if tok.type == TokenType.DELIMITER and tok.value == "<<":
            return self._parse_dict()

        # 8. Numeric, Indirect Reference, or Indirect Object Definition
        if tok.type == TokenType.NUMBER and isinstance(tok.value, int):
            return self._parse_number_or_indirect()

        # 9. Real number
        if tok.type == TokenType.NUMBER:
            self._lexer.next_token()
            return float(tok.value)

        # 10. Keyword or operator token
        if tok.type == TokenType.KEYWORD:
            self._lexer.next_token()
            return str(tok.value)

        raise PDFSyntaxError(
            f"Unexpected token {tok} at offset {tok.offset}",
            offset=tok.offset,
        )

    def _parse_array(self) -> PDFArray:
        """Parse an array enclosed in '[' ... ']'."""
        start_tok = self._lexer.next_token()
        assert start_tok.value == "["

        arr = PDFArray()
        while True:
            tok = self._lexer.peek_token()
            if tok.type == TokenType.EOF:
                raise PDFSyntaxError(
                    f"Unterminated array starting at offset {start_tok.offset}",
                    offset=start_tok.offset,
                )
            if tok.type == TokenType.DELIMITER and tok.value == "]":
                self._lexer.next_token()  # Consume ']'
                break

            obj = self.parse_object()
            if obj is not None:
                arr.append(obj)

        return arr

    def _parse_dict(self) -> PDFDict:
        """Parse a dictionary enclosed in '<<' ... '>>'."""
        start_tok = self._lexer.next_token()
        assert start_tok.value == "<<"

        d = PDFDict()
        while True:
            tok = self._lexer.peek_token()
            if tok.type == TokenType.EOF:
                raise PDFSyntaxError(
                    f"Unterminated dictionary starting at offset {start_tok.offset}",
                    offset=start_tok.offset,
                )
            if tok.type == TokenType.DELIMITER and tok.value == ">>":
                self._lexer.next_token()  # Consume '>>'
                break

            # Dictionary keys must be Names
            if tok.type != TokenType.NAME:
                raise PDFSyntaxError(
                    f"Expected Name token for dictionary key at offset {tok.offset}, got {tok}",
                    offset=tok.offset,
                )

            key_tok = self._lexer.next_token()
            key = key_tok.value

            val = self.parse_object()
            if val is None:
                raise PDFSyntaxError(
                    f"Missing value for dictionary key /{key} at offset {key_tok.offset}",
                    offset=key_tok.offset,
                )
            d[key] = val

        return d

    def _parse_number_or_indirect(self) -> PDFObject:
        """Disambiguate between single integer, indirect reference (X Y R), and indirect object (X Y obj)."""
        first_tok = self._lexer.next_token()
        first_val = first_tok.value
        assert isinstance(first_val, int)

        second_tok = self._lexer.peek_token()
        if second_tok.type == TokenType.NUMBER and isinstance(second_tok.value, int):
            # Inspect third token by temporarily consuming second token
            self._lexer.next_token()
            third_tok = self._lexer.peek_token()

            if third_tok.type == TokenType.KEYWORD and third_tok.value == "R":
                self._lexer.next_token()  # Consume 'R'
                return PDFIndirectRef(obj_id=first_val, generation=second_tok.value)

            if third_tok.type == TokenType.KEYWORD and third_tok.value == "obj":
                self._lexer.next_token()  # Consume 'obj'
                return self._parse_indirect_object_body(first_val, second_tok.value)

            # Not an indirect ref or obj: push second token back into lexer peek cache
            # Since lexer peek cache holds 1 token, we create a compound reader position restoration
            # Restore reader to position right after first_tok
            self._lexer.reader.seek(first_tok.offset + len(first_tok.raw_bytes))
            self._lexer._peeked = None
            return first_val

        return first_val

    def _parse_indirect_object_body(self, obj_id: int, generation: int) -> PDFIndirectObject:
        """Parse the payload of an indirect object definition X Y obj ... endobj."""
        inner_obj = self.parse_object()

        # Check if this object is a stream: dict followed by keyword 'stream'
        if isinstance(inner_obj, PDFDict):
            nxt = self._lexer.peek_token()
            if nxt.type == TokenType.KEYWORD and nxt.value == "stream":
                inner_obj = self._parse_stream(inner_obj)

        # Consume optional 'endobj' keyword
        end_tok = self._lexer.peek_token()
        if end_tok.type == TokenType.KEYWORD and end_tok.value == "endobj":
            self._lexer.next_token()

        return PDFIndirectObject(obj_id=obj_id, generation=generation, value=inner_obj)

    def _parse_stream(self, stream_dict: PDFDict) -> PDFStream:
        """Parse stream content following 'stream' keyword up to 'endstream'."""
        stream_tok = self._lexer.next_token()
        assert stream_tok.value == "stream"

        reader = self._lexer.reader

        # PDF 32000-1 §7.3.8.1: keyword 'stream' shall be followed by either CRLF or LF
        b = reader.peek_byte()
        if b == 0x0D:  # CR
            reader.read_byte()
            if reader.peek_byte() == 0x0A:  # CRLF
                reader.read_byte()
        elif b == 0x0A:  # LF
            reader.read_byte()

        start_stream_pos = reader.pos

        # Check if Length is directly specified as integer
        length_val = stream_dict.get("Length")
        stream_bytes: memoryview

        if isinstance(length_val, int) and length_val >= 0:
            if reader.remaining >= length_val:
                candidate = reader.slice(start_stream_pos, start_stream_pos + length_val)
                # Verify endstream follows
                test_reader = ByteReader(reader.slice(start_stream_pos + length_val, reader.length))
                test_reader.skip_whitespace()
                if test_reader.match(b"endstream"):
                    stream_bytes = candidate
                    reader.seek(start_stream_pos + length_val)
                    reader.skip_whitespace()
                    if reader.match(b"endstream", consume=True):
                        return PDFStream(dict=stream_dict, data=stream_bytes)

        # Fallback: scan forward for 'endstream'
        end_idx = reader.find(b"endstream", start=start_stream_pos)
        if end_idx == -1:
            raise PDFSyntaxError(
                f"Missing 'endstream' keyword for stream starting at offset {start_stream_pos}",
                offset=start_stream_pos,
            )

        # Trim trailing CR/LF immediately preceding 'endstream'
        stream_end = end_idx
        if stream_end > start_stream_pos and bytes(reader.slice(stream_end - 1, stream_end)) == b"\n":
            stream_end -= 1
            if stream_end > start_stream_pos and bytes(reader.slice(stream_end - 1, stream_end)) == b"\r":
                stream_end -= 1
        elif stream_end > start_stream_pos and bytes(reader.slice(stream_end - 1, stream_end)) == b"\r":
            stream_end -= 1

        stream_bytes = reader.slice(start_stream_pos, stream_end)
        reader.seek(end_idx + len(b"endstream"))
        return PDFStream(dict=stream_dict, data=stream_bytes)
