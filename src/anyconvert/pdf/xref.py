"""PDF cross-reference (xref) indexing and compressed object stream resolution.

Implements complete cross-reference resolution adhering to PDF 32000-1 §7.5:
- Backwards scanning from EOF to locate startxref.
- Classic ASCII xref tables and trailer dictionaries.
- Incremental updates and multi-revision /Prev pointer traversal.
- Cross-reference streams (/Type /XRef) with /W and /Index decoding.
- Flate / PNG predictor row reversal for cross-reference stream payloads.
- Compressed object streams (/Type /ObjStm) with /N and /First parsing.
"""

from __future__ import annotations

import io
import zlib
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from anyconvert.common.reader import ByteReader
from anyconvert.exceptions import PDFObjectError, PDFSyntaxError
from anyconvert.pdf.lexer import PDFLexer, TokenType
from anyconvert.pdf.parser import (
    PDFArray,
    PDFDict,
    PDFIndirectObject,
    PDFIndirectRef,
    PDFName,
    PDFObject,
    PDFParser,
    PDFStream,
)


@dataclass(frozen=True, slots=True)
class XRefEntry:
    """Represents a single cross-reference table or stream entry.

    Attributes:
        obj_id: Object identifier number.
        generation: Generation number.
        offset: Byte offset in the file (for Type 1) or next free object ID (for Type 0).
        is_free: True if the object is in the free list (Type 0).
        in_obj_stm: True if the object is stored inside a compressed /ObjStm (Type 2).
        obj_stm_id: Object ID of the containing /ObjStm stream (for Type 2).
        index_in_stm: Zero-based index within the /ObjStm (for Type 2).
    """

    obj_id: int
    generation: int
    offset: int
    is_free: bool = False
    in_obj_stm: bool = False
    obj_stm_id: Optional[int] = None
    index_in_stm: Optional[int] = None


class XRefTable:
    """Aggregated cross-reference index and trailer dictionary across all revisions."""

    __slots__ = ("entries", "trailer")

    def __init__(self) -> None:
        self.entries: Dict[int, XRefEntry] = {}
        self.trailer: PDFDict = PDFDict()

    def add_entry(self, entry: XRefEntry) -> None:
        """Add an entry if not already present (newer revisions take precedence)."""
        if entry.obj_id not in self.entries:
            self.entries[entry.obj_id] = entry

    def get_entry(self, obj_id: int) -> Optional[XRefEntry]:
        """Retrieve cross-reference entry for object ID."""
        return self.entries.get(obj_id)

    def __len__(self) -> int:
        return len(self.entries)

    def __repr__(self) -> str:
        return f"XRefTable(entries_count={len(self.entries)}, trailer_keys={list(self.trailer.keys())})"


def reverse_png_predictor(data: bytes, columns: int, bpp: int = 1) -> bytes:
    """Reverse PNG row predictors (10-15) for cross-reference or image stream data.

    Args:
        data: Compressed or raw data stream with predictor bytes.
        columns: Number of bytes per row excluding the 1-byte predictor tag.
        bpp: Bytes per pixel / bytes per sample (defaults to 1 for xref).

    Returns:
        bytes: Unpredicted decoded bytes.
    """
    row_len = 1 + columns
    if len(data) % row_len != 0:
        # If not an exact multiple, return raw data as fallback
        return data

    num_rows = len(data) // row_len
    out = bytearray(num_rows * columns)
    prev_row = bytearray(columns)

    for r in range(num_rows):
        row_start = r * row_len
        pred_type = data[row_start]
        row_data = data[row_start + 1 : row_start + row_len]
        curr_row = bytearray(columns)

        if pred_type == 0:  # None
            curr_row[:] = row_data
        elif pred_type == 1:  # Sub
            for c in range(columns):
                left = curr_row[c - bpp] if c >= bpp else 0
                curr_row[c] = (row_data[c] + left) & 0xFF
        elif pred_type == 2:  # Up
            for c in range(columns):
                up = prev_row[c]
                curr_row[c] = (row_data[c] + up) & 0xFF
        elif pred_type == 3:  # Average
            for c in range(columns):
                left = curr_row[c - bpp] if c >= bpp else 0
                up = prev_row[c]
                curr_row[c] = (row_data[c] + ((left + up) >> 1)) & 0xFF
        elif pred_type == 4:  # Paeth
            for c in range(columns):
                left = curr_row[c - bpp] if c >= bpp else 0
                up = prev_row[c]
                upper_left = prev_row[c - bpp] if c >= bpp else 0

                p = left + up - upper_left
                pa = abs(p - left)
                pb = abs(p - up)
                pc = abs(p - upper_left)

                if pa <= pb and pa <= pc:
                    pr = left
                elif pb <= pc:
                    pr = up
                else:
                    pr = upper_left

                curr_row[c] = (row_data[c] + pr) & 0xFF
        else:
            curr_row[:] = row_data

        out[r * columns : (r + 1) * columns] = curr_row
        prev_row = curr_row

    return bytes(out)


class XRefResolver:
    """Resolves cross-reference tables, xref streams, and compressed object streams."""

    __slots__ = ("_reader", "_table", "_obj_stm_cache", "_object_cache")

    def __init__(self, reader: ByteReader | bytes | bytearray | memoryview) -> None:
        """Initialize XRefResolver with byte data source."""
        self._reader: ByteReader = (
            reader if isinstance(reader, ByteReader) else ByteReader(reader)
        )
        self._table: Optional[XRefTable] = None
        self._obj_stm_cache: Dict[int, Dict[int, PDFObject]] = {}
        self._object_cache: Dict[int, PDFObject] = {}

    @property
    def reader(self) -> ByteReader:
        """Underlying byte reader."""
        return self._reader

    @property
    def table(self) -> XRefTable:
        """Cross-reference table (lazily loaded on first access)."""
        if self._table is None:
            self._table = self.load_xref_table()
        return self._table

    def locate_startxref(self) -> int:
        """Scan backwards from EOF to locate startxref pointer.

        Returns:
            int: Byte offset of the primary cross-reference section.

        Raises:
            PDFSyntaxError: If startxref keyword or pointer is missing.
        """
        reader = self._reader
        # Search in the last 4096 bytes of the file
        search_start = max(0, reader.length - 4096)
        idx = reader.rfind(b"startxref", start=search_start)
        if idx == -1:
            # Fallback search across entire file
            idx = reader.rfind(b"startxref")
            if idx == -1:
                raise PDFSyntaxError("Missing 'startxref' keyword in PDF trailer")

        # Parse integer offset following 'startxref'
        sub_reader = reader.sub_reader(idx + len(b"startxref"), reader.length)
        lexer = PDFLexer(sub_reader)
        tok = lexer.next_token()

        if tok.type != TokenType.NUMBER or not isinstance(tok.value, int):
            raise PDFSyntaxError(
                f"Expected integer offset after startxref at {idx}, got {tok}",
                offset=idx,
            )

        return int(tok.value)

    def load_xref_table(self) -> XRefTable:
        """Traverse all cross-reference sections and build complete XRefTable."""
        table = XRefTable()
        visited_offsets: Set[int] = set()

        next_offset: Optional[int] = self.locate_startxref()

        while next_offset is not None and next_offset > 0:
            if next_offset in visited_offsets:
                break  # Prevent circular revision loop
            visited_offsets.add(next_offset)

            self._reader.seek(next_offset)
            self._reader.skip_whitespace()

            # Determine whether this offset points to a classic 'xref' or an XRef stream
            if self._reader.match(b"xref"):
                prev = self._parse_classic_xref(table, next_offset)
            else:
                prev = self._parse_stream_xref(table, next_offset)

            next_offset = prev

        return table

    def _parse_classic_xref(self, table: XRefTable, offset: int) -> Optional[int]:
        """Parse classic ASCII xref table and trailer at offset."""
        reader = self._reader
        reader.seek(offset)
        reader.skip_whitespace()

        if not reader.match(b"xref", consume=True):
            raise PDFSyntaxError(f"Expected 'xref' at offset {offset}", offset=offset)

        # Parse subsections
        while True:
            reader.skip_whitespace_and_comments()
            if reader.match(b"trailer"):
                break

            # Read subsection header: start_id count
            header_line = reader.read_line().decode("ascii", errors="replace").strip()
            if not header_line:
                continue

            parts = header_line.split()
            if len(parts) != 2:
                break

            try:
                start_id = int(parts[0])
                count = int(parts[1])
            except ValueError:
                break

            # Read count entries (each 20 bytes: nnnnnnnnnn ggggg f|n \r\n)
            for i in range(count):
                entry_line = reader.read_bytes(20)
                line_str = bytes(entry_line).decode("ascii", errors="replace").strip()
                tokens = line_str.split()
                if len(tokens) < 3:
                    continue

                obj_id = start_id + i
                ent_offset = int(tokens[0])
                ent_gen = int(tokens[1])
                ent_type = tokens[2]

                is_free = ent_type == "f"
                entry = XRefEntry(
                    obj_id=obj_id,
                    generation=ent_gen,
                    offset=ent_offset,
                    is_free=is_free,
                )
                table.add_entry(entry)

        # Parse trailer
        reader.skip_whitespace_and_comments()
        if reader.match(b"trailer", consume=True):
            reader.skip_whitespace_and_comments()
            parser = PDFParser(reader)
            trailer_obj = parser.parse_object()

            if isinstance(trailer_obj, PDFDict):
                # Merge into table trailer (first read trailer values take precedence)
                for k, v in trailer_obj.items():
                    if k not in table.trailer:
                        table.trailer[k] = v

                # Follow /Prev pointer if present
                prev_val = trailer_obj.get("Prev")
                if isinstance(prev_val, int):
                    return prev_val

        return None

    def _parse_stream_xref(self, table: XRefTable, offset: int) -> Optional[int]:
        """Parse cross-reference stream (/Type /XRef) at offset."""
        self._reader.seek(offset)
        parser = PDFParser(self._reader)
        obj = parser.parse_object()

        if not isinstance(obj, PDFIndirectObject) or not isinstance(obj.value, PDFStream):
            raise PDFSyntaxError(
                f"Expected XRef stream at offset {offset}, got {type(obj).__name__}",
                offset=offset,
            )

        stream: PDFStream = obj.value
        sdict: PDFDict = stream.dict

        # Merge trailer dictionary entries
        for k, v in sdict.items():
            if k not in table.trailer:
                table.trailer[k] = v

        # Read /W array: [w0, w1, w2]
        w_array = sdict.get("W")
        if not isinstance(w_array, (list, PDFArray)) or len(w_array) < 3:
            raise PDFSyntaxError("XRef stream missing or invalid /W array", offset=offset)

        w0 = int(w_array[0])
        w1 = int(w_array[1])
        w2 = int(w_array[2])
        entry_size = w0 + w1 + w2

        # Read /Index array: pairs [start_id, count, ...]
        index_array = sdict.get("Index")
        ranges: List[Tuple[int, int]] = []

        if isinstance(index_array, (list, PDFArray)):
            for i in range(0, len(index_array), 2):
                if i + 1 < len(index_array):
                    ranges.append((int(index_array[i]), int(index_array[i + 1])))
        else:
            # Default is [0, Size]
            size_val = sdict.get("Size")
            if isinstance(size_val, int):
                ranges.append((0, size_val))

        # Decompress stream data
        raw_data = stream.get_raw_bytes()
        filter_val = sdict.get("Filter")

        decompressed: bytes
        if filter_val == PDFName("FlateDecode") or filter_val == "FlateDecode":
            try:
                decompressed = zlib.decompress(raw_data)
            except Exception as err:
                raise PDFSyntaxError(f"Failed to decompress XRef stream at {offset}: {err}") from err
        else:
            decompressed = raw_data

        # Check for /DecodeParms with Predictor
        dec_parms = sdict.get("DecodeParms")
        if isinstance(dec_parms, PDFDict):
            predictor = dec_parms.get("Predictor", 1)
            columns = dec_parms.get("Columns", entry_size)
            if isinstance(predictor, int) and predictor >= 10:
                decompressed = reverse_png_predictor(decompressed, columns=int(columns), bpp=1)

        # Parse binary entries
        data_len = len(decompressed)
        data_pos = 0

        for start_id, count in ranges:
            for i in range(count):
                if data_pos + entry_size > data_len:
                    break

                # Field 1: Type (default is 1 if w0 == 0)
                f0 = 1
                if w0 > 0:
                    f0 = int.from_bytes(decompressed[data_pos : data_pos + w0], "big")
                    data_pos += w0

                # Field 2: Offset or ObjStm ID
                f1 = 0
                if w1 > 0:
                    f1 = int.from_bytes(decompressed[data_pos : data_pos + w1], "big")
                    data_pos += w1

                # Field 3: Generation or Index within ObjStm
                f2 = 0
                if w2 > 0:
                    f2 = int.from_bytes(decompressed[data_pos : data_pos + w2], "big")
                    data_pos += w2

                obj_id = start_id + i

                if f0 == 0:  # Free object
                    table.add_entry(
                        XRefEntry(obj_id=obj_id, generation=f2, offset=f1, is_free=True)
                    )
                elif f0 == 1:  # Normal uncompressed object
                    table.add_entry(
                        XRefEntry(obj_id=obj_id, generation=f2, offset=f1, is_free=False)
                    )
                elif f0 == 2:  # Compressed in object stream
                    table.add_entry(
                        XRefEntry(
                            obj_id=obj_id,
                            generation=0,
                            offset=0,
                            is_free=False,
                            in_obj_stm=True,
                            obj_stm_id=f1,
                            index_in_stm=f2,
                        )
                    )

        # Follow /Prev pointer if present
        prev_val = sdict.get("Prev")
        if isinstance(prev_val, int):
            return prev_val

        return None

    def resolve_object(self, obj_id: int) -> PDFObject:
        """Resolve and return the PDFObject corresponding to obj_id.

        Args:
            obj_id: Indirect object ID.

        Returns:
            PDFObject: Parsed object.

        Raises:
            PDFObjectError: If object ID does not exist in xref table or cannot be read.
        """
        if obj_id in self._object_cache:
            return self._object_cache[obj_id]

        entry = self.table.get_entry(obj_id)
        if entry is None or entry.is_free:
            raise PDFObjectError(f"Object {obj_id} not found in cross-reference table", obj_id=obj_id)

        obj: PDFObject

        # Case 1: Compressed within an /ObjStm
        if entry.in_obj_stm:
            assert entry.obj_stm_id is not None
            assert entry.index_in_stm is not None
            obj = self._resolve_from_obj_stm(entry.obj_stm_id, obj_id, entry.index_in_stm)
            self._object_cache[obj_id] = obj
            return obj

        # Case 2: Standard uncompressed object at file offset
        self._reader.seek(entry.offset)
        parser = PDFParser(self._reader)
        parsed = parser.parse_object()
        if parsed is None:
            raise PDFObjectError(f"Failed to parse object {obj_id} at offset {entry.offset}", obj_id=obj_id)

        if isinstance(parsed, PDFIndirectObject):
            obj = parsed.value
        else:
            obj = parsed

        self._object_cache[obj_id] = obj
        return obj

    def _resolve_from_obj_stm(
        self, obj_stm_id: int, target_obj_id: int, index_in_stm: int
    ) -> PDFObject:
        """Resolve an object stored inside a compressed object stream (/Type /ObjStm)."""
        if obj_stm_id in self._obj_stm_cache:
            cached_stm = self._obj_stm_cache[obj_stm_id]
            if target_obj_id in cached_stm:
                return cached_stm[target_obj_id]

        # Resolve the /ObjStm container object itself
        stm_obj = self.resolve_object(obj_stm_id)
        if not isinstance(stm_obj, PDFStream):
            raise PDFObjectError(
                f"Object {obj_stm_id} expected to be /ObjStm stream, got {type(stm_obj).__name__}",
                obj_id=obj_stm_id,
            )

        sdict = stm_obj.dict
        num_objects = sdict.get("N")
        first_offset = sdict.get("First")

        if not isinstance(num_objects, int) or not isinstance(first_offset, int):
            raise PDFObjectError(
                f"/ObjStm {obj_stm_id} missing /N or /First parameters",
                obj_id=obj_stm_id,
            )

        # Decompress stream
        raw = stm_obj.get_raw_bytes()
        filter_name = sdict.get("Filter")
        uncompressed: bytes
        if filter_name == PDFName("FlateDecode") or filter_name == "FlateDecode":
            uncompressed = zlib.decompress(raw)
        else:
            uncompressed = raw

        # Parse header: N pairs of integers [obj_id, relative_offset]
        header_reader = ByteReader(uncompressed)
        lexer = PDFLexer(header_reader)

        entries: List[Tuple[int, int]] = []
        for _ in range(num_objects):
            tok_id = lexer.next_token()
            tok_off = lexer.next_token()
            if tok_id.type != TokenType.NUMBER or tok_off.type != TokenType.NUMBER:
                break
            entries.append((int(tok_id.value), int(tok_off.value)))

        # Parse each object from the uncompressed stream
        stm_cache: Dict[int, PDFObject] = {}
        for i, (oid, rel_off) in enumerate(entries):
            abs_start = first_offset + rel_off
            abs_end = (
                first_offset + entries[i + 1][1]
                if i + 1 < len(entries)
                else len(uncompressed)
            )

            obj_reader = ByteReader(uncompressed[abs_start:abs_end])
            parser = PDFParser(obj_reader)
            obj_val = parser.parse_object()
            if obj_val is not None:
                stm_cache[oid] = obj_val

        self._obj_stm_cache[obj_stm_id] = stm_cache

        if target_obj_id in stm_cache:
            return stm_cache[target_obj_id]

        raise PDFObjectError(
            f"Object {target_obj_id} not found in /ObjStm {obj_stm_id}",
            obj_id=target_obj_id,
        )

    def dereference(self, obj: Any) -> Any:
        """Resolve PDFIndirectRef recursively to its concrete underlying value."""
        if isinstance(obj, PDFIndirectRef):
            return self.dereference(self.resolve_object(obj.obj_id))
        return obj
