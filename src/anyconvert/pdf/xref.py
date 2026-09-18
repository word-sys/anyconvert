"""Cross-reference (XRef) table indexer and object stream resolver.

Implements:
- Backward scanning to locate `startxref` pointers
- Parsing of classic ASCII xref tables and trailer dictionaries
- Parsing of binary cross-reference streams (`/Type /XRef`) introduced in PDF 1.5
- Decompression and unpacking of compressed object streams (`/Type /ObjStm`)
- Recursive traversal of `/Prev` pointers across incremental revisions
- Full in-memory object resolution caching
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import io
import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union
import zlib

from anyconvert.common.reader import ByteReader
from anyconvert.exceptions import (
    PDFMalformedStreamError,
    PDFObjectStreamError,
    PDFSyntaxError,
    PDFTrailerNotFoundError,
    PDFXRefError,
)
from anyconvert.pdf.lexer import Lexer, Token, TokenType
from anyconvert.pdf.parser import (
    PDFIndirectObject,
    PDFName,
    PDFRef,
    PDFStream,
    Parser,
)


class XRefType(Enum):
    """Type of cross-reference entry."""

    FREE = 0  # Object is free/deleted
    UNCOMPRESSED = 1  # Regular object with direct file byte offset
    COMPRESSED = 2  # Compressed object stored within an /ObjStm


@dataclass(frozen=True)
class XRefEntry:
    """Represents a single cross-reference entry.

    Attributes:
        obj_num: Object identifier number.
        entry_type: XRefType (FREE, UNCOMPRESSED, COMPRESSED).
        offset: Byte offset in file (for UNCOMPRESSED) or /ObjStm object number (for COMPRESSED).
        gen_or_idx: Generation number (for UNCOMPRESSED) or index in /ObjStm (for COMPRESSED).
    """

    obj_num: int
    entry_type: XRefType
    offset: int
    gen_or_idx: int = 0

    @property
    def is_in_use(self) -> bool:
        """True if the object is active (uncompressed or compressed)."""
        return self.entry_type in (XRefType.UNCOMPRESSED, XRefType.COMPRESSED)


@dataclass
class XRefTable:
    """Master cross-reference index combining all revisions.

    Attributes:
        entries: Mapping of object number -> XRefEntry.
        trailer: Consolidated trailer dictionary.
        startxref: Initial startxref byte offset.
    """

    entries: Dict[int, XRefEntry] = field(default_factory=dict)
    trailer: Dict[str, Any] = field(default_factory=dict)
    startxref: int = 0

    def add_entry(self, entry: XRefEntry) -> None:
        """Add an entry if not already indexed (preserving newer revisions)."""
        if entry.obj_num not in self.entries:
            self.entries[entry.obj_num] = entry

    def get_entry(self, obj_num: int) -> Optional[XRefEntry]:
        """Look up an entry by object number."""
        return self.entries.get(obj_num)

    def object_numbers(self) -> List[int]:
        """Return sorted list of all active object numbers."""
        return sorted(
            obj_num
            for obj_num, entry in self.entries.items()
            if entry.is_in_use
        )


def _decompress_flate(data: Union[bytes, memoryview]) -> bytes:
    """Decompress zlib/flate byte stream."""
    raw = bytes(data)
    try:
        return zlib.decompress(raw)
    except zlib.error:
        # Fallback for streams with raw deflate header missing
        return zlib.decompress(raw, -15)


def _apply_png_predictor(data: bytes, columns: int) -> bytes:
    """Apply inverse PNG row filters (PNG Predictors 10-15).

    Args:
        data: Raw decompressed bytes including 1 filter byte per row.
        columns: Number of data bytes per row (excluding filter byte).

    Returns:
        Reconstructed bytes without filter bytes.
    """
    row_len = columns + 1
    num_rows = len(data) // row_len
    out = bytearray(num_rows * columns)

    prev_row = bytearray(columns)

    for r in range(num_rows):
        row_offset = r * row_len
        filter_type = data[row_offset]
        row_data = data[row_offset + 1 : row_offset + row_len]
        curr_row = bytearray(columns)

        if filter_type == 0:  # None
            curr_row[:] = row_data
        elif filter_type == 1:  # Sub: Curr(x) = Raw(x) + Curr(x - bpp)
            for c in range(columns):
                left = curr_row[c - 1] if c > 0 else 0
                curr_row[c] = (row_data[c] + left) & 0xFF
        elif filter_type == 2:  # Up: Curr(x) = Raw(x) + Prior(x)
            for c in range(columns):
                above = prev_row[c]
                curr_row[c] = (row_data[c] + above) & 0xFF
        elif filter_type == 3:  # Average: Curr(x) = Raw(x) + floor((Left + Above)/2)
            for c in range(columns):
                left = curr_row[c - 1] if c > 0 else 0
                above = prev_row[c]
                curr_row[c] = (row_data[c] + ((left + above) >> 1)) & 0xFF
        elif filter_type == 4:  # Paeth
            for c in range(columns):
                a = curr_row[c - 1] if c > 0 else 0
                b = prev_row[c]
                c_val = prev_row[c - 1] if c > 0 else 0
                # Paeth predictor
                p = a + b - c_val
                pa = abs(p - a)
                pb = abs(p - b)
                pc = abs(p - c_val)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c_val)
                curr_row[c] = (row_data[c] + pr) & 0xFF
        else:
            curr_row[:] = row_data

        out_start = r * columns
        out[out_start : out_start + columns] = curr_row
        prev_row = curr_row

    return bytes(out)


class XRefParser:
    """Parser for extracting cross-reference tables and streams from PDF files."""

    __slots__ = ("_reader",)

    def __init__(self, reader: Union[ByteReader, bytes, bytearray, memoryview]) -> None:
        self._reader: ByteReader = (
            reader if isinstance(reader, ByteReader) else ByteReader(reader)
        )

    def locate_startxref(self) -> int:
        """Scan backward from end of stream to locate the `startxref` byte offset.

        Raises:
            PDFTrailerNotFoundError: If startxref token cannot be located.
        """
        reader = self._reader
        total_len = len(reader)
        if total_len < 10:
            raise PDFTrailerNotFoundError("PDF file is too small to contain a trailer")

        # Scan the last 4KB (or entire file if smaller)
        scan_size = min(total_len, 4096)
        scan_start = total_len - scan_size
        idx = reader.rfind(b"startxref", start=scan_start, end=total_len)

        # If not in last 4KB, scan entire file as a fallback for dirty files
        if idx == -1:
            idx = reader.rfind(b"startxref", start=0, end=total_len)

        if idx == -1:
            raise PDFTrailerNotFoundError("Could not find 'startxref' token in document")

        # Seek to startxref + 9 and read the integer offset
        reader.seek(idx + 9)
        reader.skip_whitespace_and_comments()

        offset_bytes = bytearray()
        while not reader.is_eof:
            b = reader.peek_byte()
            if b is None or b not in b"0123456789":
                break
            offset_bytes.append(reader.read_byte())

        if not offset_bytes:
            raise PDFTrailerNotFoundError("Missing byte offset following 'startxref'")

        return int(offset_bytes.decode("ascii"))

    def parse(self) -> XRefTable:
        """Parse all cross-reference tables, streams, and trailers across revisions.

        Returns:
            Fully populated XRefTable.
        """
        start_offset = self.locate_startxref()
        xref_table = XRefTable(startxref=start_offset)
        visited_offsets: Set[int] = set()

        curr_offset: Optional[int] = start_offset
        while curr_offset is not None and curr_offset > 0:
            if curr_offset in visited_offsets:
                # Cycle detected in /Prev chain
                break
            visited_offsets.add(curr_offset)

            if curr_offset >= len(self._reader):
                break

            self._reader.seek(curr_offset)
            self._reader.skip_whitespace_and_comments()

            # Check whether offset points to classic ASCII 'xref' or modern '/Type /XRef' stream
            if self._reader.starts_with(b"xref"):
                curr_offset = self._parse_classic_xref(xref_table)
            else:
                curr_offset = self._parse_xref_stream(curr_offset, xref_table)

        return xref_table

    def _parse_classic_xref(self, xref_table: XRefTable) -> Optional[int]:
        """Parse classic ASCII `xref` table and trailing dictionary."""
        reader = self._reader
        reader.match(b"xref")
        reader.skip_whitespace_and_comments()

        # Parse sub-sections: <start_obj_num> <count>
        while True:
            reader.skip_whitespace_and_comments()
            if reader.starts_with(b"trailer"):
                break
            if reader.is_eof:
                break

            # Read subsection header
            line = bytes(reader.read_line()).strip()
            if not line:
                continue
            if line.startswith(b"trailer"):
                # Hit trailer
                break

            parts = line.split()
            if len(parts) != 2:
                # Malformed subsection header
                break
            try:
                start_obj = int(parts[0])
                count = int(parts[1])
            except ValueError:
                break

            # Read <count> entries (nominally 20 bytes each, but line-endings vary)
            for i in range(count):
                entry_line = bytes(reader.read_line()).strip()
                if not entry_line:
                    continue
                parts = entry_line.split()
                if len(parts) < 3:
                    continue
                obj_num = start_obj + i
                try:
                    offset_val = int(parts[0])
                    gen_val = int(parts[1])
                    type_flag = parts[2]

                    if type_flag == b"n":
                        entry = XRefEntry(
                            obj_num=obj_num,
                            entry_type=XRefType.UNCOMPRESSED,
                            offset=offset_val,
                            gen_or_idx=gen_val,
                        )
                        xref_table.add_entry(entry)
                    elif type_flag == b"f":
                        entry = XRefEntry(
                            obj_num=obj_num,
                            entry_type=XRefType.FREE,
                            offset=offset_val,
                            gen_or_idx=gen_val,
                        )
                        xref_table.add_entry(entry)
                except (ValueError, IndexError):
                    continue


        # Parse trailer dictionary
        reader.skip_whitespace_and_comments()
        if reader.match(b"trailer"):
            reader.skip_whitespace_and_comments()
            parser = Parser(reader)
            trailer_dict = parser.parse_object()
            if isinstance(trailer_dict, dict):
                for k, v in trailer_dict.items():
                    if k not in xref_table.trailer:
                        xref_table.trailer[k] = v

                prev = trailer_dict.get("Prev")
                if isinstance(prev, int):
                    return prev

        return None

    def _parse_xref_stream(self, stream_offset: int, xref_table: XRefTable) -> Optional[int]:
        """Parse cross-reference stream (`/Type /XRef`)."""
        self._reader.seek(stream_offset)
        parser = Parser(self._reader)
        obj = parser.parse_object()

        if isinstance(obj, PDFIndirectObject):
            obj = obj.value

        if not isinstance(obj, PDFStream):
            raise PDFXRefError(f"Expected /Type /XRef stream at offset {stream_offset}")

        s_dict = obj.dictionary
        for k, v in s_dict.items():
            if k not in xref_table.trailer:
                xref_table.trailer[k] = v

        # Read /W (width array of 3 integers)
        w_array = s_dict.get("W")
        if not isinstance(w_array, list) or len(w_array) != 3:
            raise PDFXRefError("Invalid /W width array in cross-reference stream")

        w0, w1, w2 = int(w_array[0]), int(w_array[1]), int(w_array[2])
        entry_size = w0 + w1 + w2

        # Read /Size and /Index
        size_val = s_dict.get("Size", 0)
        index_array = s_dict.get("Index")
        if isinstance(index_array, list) and len(index_array) >= 2:
            subsections = [
                (int(index_array[i]), int(index_array[i + 1]))
                for i in range(0, len(index_array), 2)
            ]
        else:
            subsections = [(0, int(size_val))]

        # Decompress stream data
        raw_stream = obj.to_bytes()
        filter_val = s_dict.get("Filter")
        if filter_val == "FlateDecode" or (isinstance(filter_val, list) and "FlateDecode" in filter_val):
            decompressed = _decompress_flate(raw_stream)
        else:
            decompressed = raw_stream

        # Check /DecodeParms for Predictor
        decode_parms = s_dict.get("DecodeParms")
        if isinstance(decode_parms, dict):
            predictor = decode_parms.get("Predictor", 1)
            columns = decode_parms.get("Columns", entry_size)
            if predictor >= 10:  # PNG Predictors 10-15
                decompressed = _apply_png_predictor(decompressed, int(columns))

        # Unpack binary entries
        data_view = memoryview(decompressed)
        byte_pos = 0

        for start_obj, count in subsections:
            for i in range(count):
                if byte_pos + entry_size > len(data_view):
                    break
                obj_num = start_obj + i

                # Field 1: Type (w0 bytes, default 1 if w0 == 0)
                if w0 > 0:
                    field1 = int.from_bytes(data_view[byte_pos : byte_pos + w0], "big")
                    byte_pos += w0
                else:
                    field1 = 1

                # Field 2: Offset / ObjStm number (w1 bytes)
                field2 = int.from_bytes(data_view[byte_pos : byte_pos + w1], "big")
                byte_pos += w1

                # Field 3: Gen number / Index in ObjStm (w2 bytes)
                field3 = int.from_bytes(data_view[byte_pos : byte_pos + w2], "big")
                byte_pos += w2

                if field1 == 0:
                    entry = XRefEntry(obj_num, XRefType.FREE, field2, field3)
                elif field1 == 1:
                    entry = XRefEntry(obj_num, XRefType.UNCOMPRESSED, field2, field3)
                elif field1 == 2:
                    entry = XRefEntry(obj_num, XRefType.COMPRESSED, field2, field3)
                else:
                    continue

                xref_table.add_entry(entry)

        # Check /Prev
        prev = s_dict.get("Prev")
        return int(prev) if isinstance(prev, int) else None


class ObjectStreamUnpacker:
    """Decompresses and extracts individual objects from `/Type /ObjStm` object streams."""

    __slots__ = ("_reader", "_xref_table", "_cache")

    def __init__(self, reader: ByteReader, xref_table: XRefTable) -> None:
        self._reader: ByteReader = reader
        self._xref_table: XRefTable = xref_table
        # Cache mapping obj_stm_num -> dict of obj_num -> parsed object
        self._cache: Dict[int, Dict[int, Any]] = {}

    def unpack_object(self, obj_stm_num: int, target_obj_num: int) -> Any:
        """Extract a single object from a compressed object stream.

        Args:
            obj_stm_num: Object number of the container /ObjStm.
            target_obj_num: Object number of the target child object.

        Returns:
            Parsed object.
        """
        if obj_stm_num in self._cache:
            stm_dict = self._cache[obj_stm_num]
            if target_obj_num in stm_dict:
                return stm_dict[target_obj_num]

        entry = self._xref_table.get_entry(obj_stm_num)
        if not entry or entry.entry_type != XRefType.UNCOMPRESSED:
            raise PDFObjectStreamError(f"Container object stream {obj_stm_num} not found")

        self._reader.seek(entry.offset)
        parser = Parser(self._reader)
        obj = parser.parse_object()
        if isinstance(obj, PDFIndirectObject):
            obj = obj.value

        if not isinstance(obj, PDFStream):
            raise PDFObjectStreamError(
                f"Object {obj_stm_num} is not a valid stream (/Type /ObjStm expected)"
            )

        s_dict = obj.dictionary
        if s_dict.get("Type") != "ObjStm":
            # Some PDFs omit /Type, check /N and /First
            if "N" not in s_dict or "First" not in s_dict:
                raise PDFObjectStreamError(f"Stream {obj_stm_num} is not an /ObjStm")

        num_objects = int(s_dict["N"])
        first_offset = int(s_dict["First"])

        # Decompress stream
        raw_stream = obj.to_bytes()
        filter_val = s_dict.get("Filter")
        if filter_val == "FlateDecode" or (isinstance(filter_val, list) and "FlateDecode" in filter_val):
            decompressed = _decompress_flate(raw_stream)
        else:
            decompressed = raw_stream

        # Parse header: N pairs of [obj_num relative_offset]
        stream_reader = ByteReader(decompressed)
        header_lexer = Lexer(stream_reader)

        pairs: List[Tuple[int, int]] = []
        for _ in range(num_objects):
            tok_id = header_lexer.next_token()
            tok_off = header_lexer.next_token()
            if tok_id.type != TokenType.INTEGER or tok_off.type != TokenType.INTEGER:
                raise PDFObjectStreamError("Malformed header in /ObjStm")
            pairs.append((int(tok_id.value), int(tok_off.value)))

        # Cache all objects in this stream
        objects: Dict[int, Any] = {}
        for i, (oid, rel_off) in enumerate(pairs):
            abs_start = first_offset + rel_off
            # End offset is either the next object's offset or the end of the stream
            if i + 1 < len(pairs):
                abs_end = first_offset + pairs[i + 1][1]
            else:
                abs_end = len(decompressed)

            obj_data = decompressed[abs_start:abs_end]
            obj_parser = Parser(obj_data)
            objects[oid] = obj_parser.parse_object()

        self._cache[obj_stm_num] = objects
        if target_obj_num not in objects:
            raise PDFObjectStreamError(
                f"Object {target_obj_num} not found in object stream {obj_stm_num}"
            )

        return objects[target_obj_num]


class XRefResolver:
    """Unified object resolver navigating XRef tables, direct objects, and /ObjStm streams."""

    __slots__ = ("_reader", "_xref_table", "_unpacker", "_resolved_cache")

    def __init__(
        self,
        reader: Union[ByteReader, bytes, bytearray, memoryview],
        xref_table: Optional[XRefTable] = None,
    ) -> None:
        self._reader: ByteReader = (
            reader if isinstance(reader, ByteReader) else ByteReader(reader)
        )
        if xref_table is not None:
            self._xref_table = xref_table
        else:
            self._xref_table = XRefParser(self._reader).parse()

        self._unpacker = ObjectStreamUnpacker(self._reader, self._xref_table)
        self._resolved_cache: Dict[int, Any] = {}

    @property
    def reader(self) -> ByteReader:
        """Access underlying ByteReader."""
        return self._reader

    @property
    def xref_table(self) -> XRefTable:
        """Access the master XRefTable."""
        return self._xref_table

    @property
    def trailer(self) -> Dict[str, Any]:
        """Access the document trailer dictionary."""
        return self._xref_table.trailer

    def resolve_ref(self, ref: PDFRef) -> Any:
        """Resolve an indirect reference `PDFRef(N, M)` to its underlying value."""
        return self.resolve(ref.obj_num)

    def resolve(self, obj_num: int) -> Any:
        """Resolve an object by number, using cache to prevent redundant parsing.

        Raises:
            PDFXRefError: If the object number is not found or is free.
        """
        if obj_num in self._resolved_cache:
            return self._resolved_cache[obj_num]

        entry = self._xref_table.get_entry(obj_num)
        if not entry or not entry.is_in_use:
            raise PDFXRefError(f"Object {obj_num} is free or does not exist in XRef table")

        if entry.entry_type == XRefType.UNCOMPRESSED:
            self._reader.seek(entry.offset)
            parser = Parser(self._reader)
            obj = parser.parse_object()
            val = obj.value if isinstance(obj, PDFIndirectObject) else obj
        elif entry.entry_type == XRefType.COMPRESSED:
            val = self._unpacker.unpack_object(entry.offset, obj_num)
        else:
            raise PDFXRefError(f"Unsupported entry type for object {obj_num}")

        self._resolved_cache[obj_num] = val
        return val


__all__ = [
    "XRefType",
    "XRefEntry",
    "XRefTable",
    "XRefParser",
    "ObjectStreamUnpacker",
    "XRefResolver",
]
