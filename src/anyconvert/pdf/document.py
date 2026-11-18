"""PDF document high-level object model and catalog/page tree resolver.

Provides access to document metadata, catalog, encryption dictionary,
and hierarchical page tree traversal with attribute inheritance.
"""

from __future__ import annotations

import pathlib
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from anyconvert.common.reader import ByteReader
from anyconvert.exceptions import (
    PDFError,
    PDFObjectError,
    PDFPasswordRequiredError,
    PDFSecurityError,
    PDFSyntaxError,
)
from anyconvert.pdf.crypto.handler import SecurityHandler
from anyconvert.pdf.filters import decode_stream
from anyconvert.pdf.parser import (
    PDFArray,
    PDFDict,
    PDFHexString,
    PDFIndirectRef,
    PDFName,
    PDFNull,
    PDFObject,
    PDFStream,
    PDFString,
)
from anyconvert.pdf.xref import XRefResolver


_PDF_DATE_RE = re.compile(
    r"^D:(\d{4})"
    r"(?:(\d{2})"
    r"(?:(\d{2})"
    r"(?:(\d{2})"
    r"(?:(\d{2})"
    r"(?:(\d{2}))?)?)?)?)?"
    r"(?:([Z+-])(?:(\d{2})'?(\d{2})?'?)?)?$"
)


def parse_pdf_date(raw_date: str) -> str:
    """Convert a PDF date string (D:YYYYMMDDHHmmSSOHH'mm') to ISO 8601 when valid."""
    cleaned = raw_date.strip()
    if not cleaned:
        return ""
    match = _PDF_DATE_RE.match(cleaned)
    if not match:
        return cleaned

    year_s, mon_s, day_s, hour_s, min_s, sec_s, tz_sign, tz_h_s, tz_m_s = match.groups()
    if mon_s is not None and not (1 <= int(mon_s) <= 12):
        return cleaned
    if day_s is not None and not (1 <= int(day_s) <= 31):
        return cleaned
    if hour_s is not None and not (0 <= int(hour_s) <= 23):
        return cleaned
    if min_s is not None and not (0 <= int(min_s) <= 59):
        return cleaned
    if sec_s is not None and not (0 <= int(sec_s) <= 59):
        return cleaned

    date_parts = [year_s]
    if mon_s is not None:
        date_parts.append(mon_s)
        if day_s is not None:
            date_parts.append(day_s)
    iso = "-".join(date_parts)

    if hour_s is not None:
        time_h = hour_s
        time_m = min_s or "00"
        time_s = sec_s or "00"
        iso = f"{iso}T{time_h}:{time_m}:{time_s}"
        if tz_sign == "Z":
            iso = f"{iso}Z"
        elif tz_sign in ("+", "-") and tz_h_s is not None:
            tz_h = tz_h_s
            tz_m = tz_m_s or "00"
            iso = f"{iso}{tz_sign}{tz_h}:{tz_m}"

    return iso


class PDFDocument:
    """Represents a parsed PDF document with access to trailer, catalog, and page tree."""

    __slots__ = (
        "_resolver",
        "_catalog",
        "_info",
        "_page_refs",
        "_page_dicts",
        "_security_handler",
    )

    def __init__(
        self,
        source: Union[str, pathlib.Path, bytes, bytearray, ByteReader],
        password: str = "",
        auth_key: str = "",
    ) -> None:
        """Initialize PDFDocument from file path, bytes, or ByteReader.

        Args:
            source: File path, raw bytes, or ByteReader.
            password: Optional password for encrypted documents.
            auth_key: Optional authentication key for encrypted documents.
        """
        reader: ByteReader
        if isinstance(source, (str, pathlib.Path)):
            data = pathlib.Path(source).read_bytes()
            reader = ByteReader(data)
        elif isinstance(source, ByteReader):
            reader = source
        else:
            reader = ByteReader(source)

        self._resolver: XRefResolver = XRefResolver(reader)
        self._catalog: Optional[PDFDict] = None
        self._info: Optional[PDFDict] = None
        self._page_refs: Optional[List[PDFDict]] = None
        self._page_dicts: Dict[int, PDFDict] = {}
        self._security_handler: Optional[SecurityHandler] = None

        key_val = auth_key if auth_key else password

        # Authenticate if encrypted
        if "Encrypt" in self.trailer:
            encrypt_obj = self._resolver.dereference(self.trailer.get("Encrypt"))
            if isinstance(encrypt_obj, PDFDict):
                doc_ids = self.trailer.get("ID")
                id_seq = doc_ids if isinstance(doc_ids, (list, PDFArray)) else None
                handler = SecurityHandler(encrypt_obj, id_seq)
                if not handler.authenticate(auth_key=key_val):
                    raise PDFPasswordRequiredError(
                        "PDF document is password protected; incorrect or missing password"
                    )
                self._security_handler = handler

    @property
    def resolver(self) -> XRefResolver:
        """Underlying XRefResolver."""
        return self._resolver

    def close(self) -> None:
        """Release underlying PDF reader and parser resources."""
        self._resolver.close()

    def __enter__(self) -> PDFDocument:
        """Context management entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context management exit releasing resources."""
        self.close()

    @property
    def trailer(self) -> PDFDict:
        """Merged trailer dictionary."""
        return self._resolver.table.trailer

    @property
    def catalog(self) -> PDFDict:
        """Root document catalog dictionary (/Root)."""
        if self._catalog is None:
            root_ref = self.trailer.get("Root")
            if root_ref is None:
                raise PDFSyntaxError("PDF trailer missing /Root catalog pointer")
            catalog_obj = self._resolver.dereference(root_ref)
            if not isinstance(catalog_obj, PDFDict):
                raise PDFSyntaxError(
                    f"Expected PDFDict for /Root catalog, got {type(catalog_obj).__name__}"
                )
            self._catalog = catalog_obj
        return self._catalog

    @property
    def info(self) -> Optional[PDFDict]:
        """Document information metadata dictionary (/Info), if present."""
        if self._info is None and "Info" in self.trailer:
            info_ref = self.trailer.get("Info")
            info_obj = self._resolver.dereference(info_ref)
            if isinstance(info_obj, PDFDict):
                self._info = info_obj
        return self._info

    @property
    def is_encrypted(self) -> bool:
        """Return True if the document has an /Encrypt dictionary."""
        return "Encrypt" in self.trailer

    @property
    def page_count(self) -> int:
        """Total number of pages in the document."""
        self._ensure_page_tree()
        assert self._page_refs is not None
        return len(self._page_refs)

    def _ensure_page_tree(self) -> None:
        """Traverse the page tree (/Pages -> /Kids) and cache all leaf /Page dictionaries."""
        if self._page_refs is not None:
            return

        pages_root_ref = self.catalog.get("Pages")
        if pages_root_ref is None:
            raise PDFSyntaxError("Catalog dictionary missing /Pages pointer")

        pages_root = self._resolver.dereference(pages_root_ref)
        if not isinstance(pages_root, PDFDict):
            raise PDFSyntaxError("Catalog /Pages is not a dictionary")

        leaves: List[PDFDict] = []
        # Inheritable attributes stack
        self._collect_pages(pages_root, inherited={}, out_leaves=leaves)
        self._page_refs = leaves

    def _collect_pages(
        self,
        node: PDFDict,
        inherited: Dict[str, Any],
        out_leaves: List[PDFDict],
    ) -> None:
        """Recursively collect leaf Page dictionaries, propagating inherited attributes."""
        # Update inherited attributes from this node
        curr_inherited = dict(inherited)
        for attr in ("MediaBox", "CropBox", "Resources", "Rotate"):
            if attr in node:
                curr_inherited[attr] = node[attr]

        node_type = node.get("Type")
        if node_type == "Page" or node_type == PDFName("Page"):
            # Leaf page: apply inherited attributes that are not already defined on the leaf
            page_dict = PDFDict(node)
            for attr, val in curr_inherited.items():
                if attr not in page_dict:
                    page_dict[attr] = val
            out_leaves.append(page_dict)
            return

        # Intermediate Pages node: traverse /Kids
        kids = node.get("Kids")
        if isinstance(kids, (list, PDFArray)):
            for kid_ref in kids:
                kid_obj = self._resolver.dereference(kid_ref)
                if isinstance(kid_obj, PDFDict):
                    self._collect_pages(kid_obj, curr_inherited, out_leaves)

    def get_page(self, page_index: int) -> PDFDict:
        """Retrieve the page dictionary for zero-based page index.

        Args:
            page_index: Zero-based index (0 <= page_index < page_count).

        Returns:
            PDFDict: Page dictionary with inherited attributes resolved.

        Raises:
            IndexError: If page_index is out of range.
        """
        self._ensure_page_tree()
        assert self._page_refs is not None

        if page_index < 0 or page_index >= len(self._page_refs):
            raise IndexError(
                f"Page index {page_index} out of range (total pages: {len(self._page_refs)})"
            )

        return self._page_refs[page_index]

    def get_page_box(
        self, page_dict: PDFDict, box_name: str = "MediaBox"
    ) -> Tuple[float, float, float, float]:
        """Extract bounding box coordinates [x0, y0, x1, y1] for a page.

        Args:
            page_dict: Target page dictionary.
            box_name: 'MediaBox', 'CropBox', 'BleedBox', 'TrimBox', or 'ArtBox'.

        Returns:
            Tuple[float, float, float, float]: (x0, y0, x1, y1). Defaults to standard letter (0, 0, 612, 792).
        """
        raw_box = page_dict.get(box_name)
        if raw_box is None and box_name != "MediaBox":
            raw_box = page_dict.get("MediaBox")

        if isinstance(raw_box, (list, PDFArray)) and len(raw_box) >= 4:
            try:
                x0 = float(self._resolver.dereference(raw_box[0]))
                y0 = float(self._resolver.dereference(raw_box[1]))
                x1 = float(self._resolver.dereference(raw_box[2]))
                y1 = float(self._resolver.dereference(raw_box[3]))
                return (x0, y0, x1, y1)
            except (ValueError, TypeError):
                pass

        # Standard Letter fallback (8.5 x 11 inches at 72 dpi)
        return (0.0, 0.0, 612.0, 792.0)

    def get_page_rotation(self, page_dict: PDFDict) -> int:
        """Return clockwise page rotation in degrees (0, 90, 180, 270)."""
        rot = page_dict.get("Rotate", 0)
        if isinstance(rot, int):
            return rot % 360
        return 0

    @property
    def security_handler(self) -> Optional[SecurityHandler]:
        """Security handler if document is encrypted."""
        return self._security_handler

    def get_metadata(self) -> Dict[str, str]:
        """Extract document metadata key-value pairs from /Info dictionary."""
        meta: Dict[str, str] = {}
        info_dict = self.info
        if not info_dict:
            return meta

        info_ref = self.trailer.get("Info")
        enclosing_ref: Optional[Tuple[int, int]] = (
            (info_ref.obj_id, info_ref.generation)
            if isinstance(info_ref, PDFIndirectRef)
            else None
        )

        for k, raw_v in info_dict.items():
            key_name = str(k).lstrip("/")
            obj_ref = enclosing_ref
            v: Any = raw_v
            if isinstance(raw_v, PDFIndirectRef):
                obj_ref = (raw_v.obj_id, raw_v.generation)
                v = self._resolver.dereference(raw_v)

            if v is None or isinstance(v, PDFNull):
                continue

            val_str = ""
            if isinstance(v, (PDFString, PDFHexString)):
                if self._security_handler is not None and obj_ref is not None:
                    try:
                        dec_bytes = self._security_handler.decrypt_data(
                            v.as_bytes(),
                            obj_id=obj_ref[0],
                            gen=obj_ref[1],
                            is_stream=False,
                        )
                        v = PDFString(value=dec_bytes)
                    except Exception:
                        pass
                val_str = v.as_text()
            elif isinstance(v, PDFName):
                val_str = v.name
            elif isinstance(v, str):
                val_str = v
            elif isinstance(v, bytes):
                val_str = v.decode("latin-1", errors="replace")
            else:
                val_str = str(v)

            val_str = val_str.strip("\x00").strip()
            if not val_str:
                continue

            if key_name in ("CreationDate", "ModDate"):
                val_str = parse_pdf_date(val_str)

            meta[key_name] = val_str
        return meta

    def get_page_content_bytes(self, page_dict: PDFDict) -> bytes:
        """Extract, decrypt, decompress, and concatenate all /Contents stream payloads for a page.

        Returns:
            bytes: Decompressed content stream bytes.
        """
        contents_ref = page_dict.get("Contents")
        if contents_ref is None:
            return b""

        stream_entries: List[Tuple[PDFStream, Optional[Tuple[int, int]]]] = []

        if isinstance(contents_ref, PDFIndirectRef):
            obj = self._resolver.resolve_object(contents_ref.obj_id)
            if isinstance(obj, PDFStream):
                stream_entries.append((obj, (contents_ref.obj_id, contents_ref.generation)))
            elif isinstance(obj, (list, PDFArray)):
                for item in obj:
                    if isinstance(item, PDFIndirectRef):
                        s = self._resolver.resolve_object(item.obj_id)
                        if isinstance(s, PDFStream):
                            stream_entries.append((s, (item.obj_id, item.generation)))
                    elif isinstance(item, PDFStream):
                        stream_entries.append((item, None))
        elif isinstance(contents_ref, PDFStream):
            stream_entries.append((contents_ref, None))
        elif isinstance(contents_ref, (list, PDFArray)):
            for item in contents_ref:
                if isinstance(item, PDFIndirectRef):
                    s = self._resolver.resolve_object(item.obj_id)
                    if isinstance(s, PDFStream):
                        stream_entries.append((s, (item.obj_id, item.generation)))
                elif isinstance(item, PDFStream):
                    stream_entries.append((item, None))

        out_chunks: List[bytes] = []
        for stm, ref_tuple in stream_entries:
            raw = stm.get_raw_bytes()
            if self._security_handler is not None and ref_tuple is not None:
                try:
                    raw = self._security_handler.decrypt_data(
                        raw, obj_id=ref_tuple[0], gen=ref_tuple[1], is_stream=True
                    )
                except Exception:
                    pass

            filter_val = stm.dict.get("Filter")
            parms_val = stm.dict.get("DecodeParms")
            try:
                decompressed = decode_stream(raw, filter_val, parms_val)
                out_chunks.append(decompressed)
            except Exception:
                out_chunks.append(raw)

        return b"\n".join(out_chunks)
