"""Type 0 composite font and CIDFont (Type 0 and Type 2) resolver.

Adheres to PDF 32000-1 §9.7:
- Resolves Type 0 composite fonts and descendant CIDFontType0 / CIDFontType2 dictionaries.
- Unpacks complex /W width arrays supporting both Format 1 (c [w1 w2 ... wn]) and Format 2 (c_first c_last w).
- Resolves /DW default widths and /FontDescriptor typographic metrics.
"""

from __future__ import annotations

import struct
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from anyconvert.common.geometry import BoundingBox
from anyconvert.exceptions import PDFFontError
from anyconvert.pdf.filters import decode_stream
from anyconvert.pdf.parser import PDFArray, PDFDict, PDFIndirectRef, PDFName, PDFStream
from anyconvert.pdf.typography.cff import CFFFont
from anyconvert.pdf.typography.font import BaseFont, FontMetrics
from anyconvert.pdf.typography.sfnt import SFNTFont
from anyconvert.pdf.xref import XRefResolver


class CompositeFont(BaseFont):
    """Resolves Type 0 composite fonts and CIDFont width mappings."""

    __slots__ = (
        "_font_dict",
        "_cid_font_dict",
        "_resolver",
        "_default_width",
        "_cid_widths",
        "_is_vertical",
        "_vertical_widths",
        "_default_dw2",
        "_cid_to_gid_map",
        "_embedded_font",
    )

    def __init__(
        self,
        font_dict: PDFDict,
        resolver: Optional[XRefResolver] = None,
        name: str = "Type0Font",
    ) -> None:
        """Initialize CompositeFont from PDF Type 0 font dictionary.

        Args:
            font_dict: Top-level Type 0 font dictionary (/Subtype /Type0).
            resolver: Optional XRefResolver to dereference indirect objects.
            name: Font name identifier.
        """
        super().__init__(name=name)
        self._font_dict: PDFDict = font_dict
        self._resolver: Optional[XRefResolver] = resolver
        self._cid_font_dict: Optional[PDFDict] = None
        self._default_width: float = 1000.0
        self._cid_widths: Dict[int, float] = {}
        self._vertical_widths: Dict[int, Tuple[float, float, float]] = {}
        self._default_dw2: Tuple[float, float] = (880.0, -1000.0)  # (vy, w1y)
        self._is_vertical: bool = False
        self._cid_to_gid_map: Optional[bytes] = None
        self._embedded_font: Optional[BaseFont] = None

        self._parse()

    @property
    def is_vertical(self) -> bool:
        """Return True if writing mode is vertical (/Identity-V)."""
        return self._is_vertical

    @property
    def embedded_font(self) -> Optional[BaseFont]:
        """Return embedded descendant font instance if available."""
        return self._embedded_font

    def _dereference(self, obj: Any) -> Any:
        """Dereference indirect reference if resolver is available."""
        if self._resolver is not None:
            return self._resolver.dereference(obj)
        return obj

    def _parse(self) -> None:
        """Parse Type 0 font, DescendantFonts, /W, /DW, and /FontDescriptor."""
        # Check encoding for vertical orientation
        encoding = self._font_dict.get("Encoding")
        if encoding in ("Identity-V", PDFName("Identity-V")):
            self._is_vertical = True

        # BaseFont name
        bf_name = self._font_dict.get("BaseFont")
        if isinstance(bf_name, PDFName):
            self.name = bf_name.name
        elif isinstance(bf_name, str):
            self.name = bf_name

        # Extract DescendantFonts
        desc_fonts = self._font_dict.get("DescendantFonts")
        if desc_fonts is None:
            return

        desc_fonts_resolved = self._dereference(desc_fonts)
        if not isinstance(desc_fonts_resolved, (list, PDFArray)) or len(desc_fonts_resolved) == 0:
            return

        first_cid = self._dereference(desc_fonts_resolved[0])
        if not isinstance(first_cid, PDFDict):
            return

        self._cid_font_dict = first_cid

        # Extract /DW (Default Width, default 1000)
        dw_val = first_cid.get("DW", 1000)
        try:
            self._default_width = float(self._dereference(dw_val))
        except (ValueError, TypeError):
            self._default_width = 1000.0
        self.metrics.default_width = self._default_width

        # Extract /DW2 (Default Vertical Metrics, default [880, -1000])
        dw2_val = first_cid.get("DW2")
        if dw2_val is not None:
            dw2_resolved = self._dereference(dw2_val)
            if isinstance(dw2_resolved, (list, PDFArray)) and len(dw2_resolved) >= 2:
                try:
                    vy = float(self._dereference(dw2_resolved[0]))
                    w1y = float(self._dereference(dw2_resolved[1]))
                    self._default_dw2 = (vy, w1y)
                except (ValueError, TypeError):
                    pass

        # Parse /W (Widths array)
        raw_w = first_cid.get("W")
        if raw_w is not None:
            w_resolved = self._dereference(raw_w)
            if isinstance(w_resolved, (list, PDFArray)):
                self._unpack_w_array(w_resolved)

        # Parse /W2 (Vertical Widths array)
        raw_w2 = first_cid.get("W2")
        if raw_w2 is not None:
            w2_resolved = self._dereference(raw_w2)
            if isinstance(w2_resolved, (list, PDFArray)):
                self._unpack_w2_array(w2_resolved)

        # Parse /CIDToGIDMap
        cid_to_gid = first_cid.get("CIDToGIDMap")
        if cid_to_gid is not None:
            cg_obj = self._dereference(cid_to_gid)
            if isinstance(cg_obj, PDFStream):
                try:
                    raw_bytes = cg_obj.get_raw_bytes()
                    filt = cg_obj.dict.get("Filter")
                    parms = cg_obj.dict.get("DecodeParms")
                    self._cid_to_gid_map = decode_stream(raw_bytes, filt, parms)
                except Exception:
                    self._cid_to_gid_map = bytes(cg_obj.data)
            elif isinstance(cg_obj, (bytes, bytearray)):
                self._cid_to_gid_map = bytes(cg_obj)

        # Parse /FontDescriptor
        fd_ref = first_cid.get("FontDescriptor")
        if fd_ref is not None:
            fd_obj = self._dereference(fd_ref)
            if isinstance(fd_obj, PDFDict):
                self._parse_font_descriptor(fd_obj)

    def cid_to_gid(self, cid: int) -> int:
        """Map CID to TrueType Glyph ID (GID) via CIDToGIDMap."""
        if self._cid_to_gid_map is None:
            return cid
        offset = cid * 2
        if offset + 2 <= len(self._cid_to_gid_map):
            return int(struct.unpack_from(">H", self._cid_to_gid_map, offset)[0])
        return 0

    def _unpack_w_array(self, w_array: Sequence[Any]) -> None:
        """Unpack PDF CIDFont /W array supporting Format 1 and Format 2 mixed.

        Format 1: c [ w1 w2 ... wn ]
        Format 2: c_first c_last w
        """
        i = 0
        length = len(w_array)

        while i < length:
            item = self._dereference(w_array[i])
            if not isinstance(item, (int, float)):
                i += 1
                continue

            c_first = int(item)
            i += 1
            if i >= length:
                break

            next_item = self._dereference(w_array[i])
            i += 1

            if isinstance(next_item, (list, PDFArray)):
                # Format 1: sequential widths starting at c_first
                for offset, w_val in enumerate(next_item):
                    try:
                        self._cid_widths[c_first + offset] = float(self._dereference(w_val))
                    except (ValueError, TypeError):
                        pass
            elif isinstance(next_item, (int, float)):
                # Format 2: range c_first to c_last with constant width
                c_last = int(next_item)
                if i < length:
                    w_val = self._dereference(w_array[i])
                    i += 1
                    try:
                        width = float(w_val)
                        for cid in range(c_first, c_last + 1):
                            self._cid_widths[cid] = width
                    except (ValueError, TypeError):
                        pass

        self.widths = self._cid_widths

    def _unpack_w2_array(self, w2_array: Sequence[Any]) -> None:
        """Unpack PDF CIDFont /W2 vertical metrics array."""
        i = 0
        length = len(w2_array)
        while i < length:
            item = self._dereference(w2_array[i])
            if not isinstance(item, (int, float)):
                i += 1
                continue
            c_first = int(item)
            i += 1
            if i >= length:
                break

            next_item = self._dereference(w2_array[i])
            i += 1

            if isinstance(next_item, (list, PDFArray)):
                # Format 1: c [ w1y v1x v1y  w2y v2x v2y ... ]
                sub_len = len(next_item)
                for offset in range(0, sub_len, 3):
                    if offset + 2 < sub_len:
                        try:
                            w1y = float(self._dereference(next_item[offset]))
                            v1x = float(self._dereference(next_item[offset + 1]))
                            v1y = float(self._dereference(next_item[offset + 2]))
                            cid = c_first + (offset // 3)
                            self._vertical_widths[cid] = (w1y, v1x, v1y)
                        except (ValueError, TypeError):
                            pass
            elif isinstance(next_item, (int, float)):
                # Format 2: c_first c_last w1y v1x v1y
                c_last = int(next_item)
                if i + 2 < length:
                    try:
                        w1y = float(self._dereference(w2_array[i]))
                        v1x = float(self._dereference(w2_array[i + 1]))
                        v1y = float(self._dereference(w2_array[i + 2]))
                        i += 3
                        for cid in range(c_first, c_last + 1):
                            self._vertical_widths[cid] = (w1y, v1x, v1y)
                    except (ValueError, TypeError):
                        i += 3

    def _parse_font_descriptor(self, fd: PDFDict) -> None:
        """Extract typographic metrics from /FontDescriptor dictionary."""
        # Ascent, Descent, CapHeight, ItalicAngle, Flags
        ascent = fd.get("Ascent")
        if ascent is not None:
            try:
                self.metrics.ascender = float(self._dereference(ascent))
            except (ValueError, TypeError):
                pass

        descent = fd.get("Descent")
        if descent is not None:
            try:
                self.metrics.descender = float(self._dereference(descent))
            except (ValueError, TypeError):
                pass

        cap_height = fd.get("CapHeight")
        if cap_height is not None:
            try:
                self.metrics.cap_height = float(self._dereference(cap_height))
            except (ValueError, TypeError):
                pass

        italic_angle = fd.get("ItalicAngle")
        if italic_angle is not None:
            try:
                self.metrics.italic_angle = float(self._dereference(italic_angle))
                self.metrics.is_italic = self.metrics.italic_angle != 0.0
            except (ValueError, TypeError):
                pass

        flags = fd.get("Flags")
        if flags is not None:
            try:
                f_val = int(self._dereference(flags))
                self.metrics.is_monospace = bool(f_val & 1)  # Bit 1: FixedPitch
                self.metrics.is_italic = self.metrics.is_italic or bool(f_val & (1 << 6))  # Bit 7: Italic
            except (ValueError, TypeError):
                pass

        # FontBBox
        bbox_val = fd.get("FontBBox")
        if bbox_val is not None:
            bbox_resolved = self._dereference(bbox_val)
            if isinstance(bbox_resolved, (list, PDFArray)) and len(bbox_resolved) >= 4:
                try:
                    x0 = float(self._dereference(bbox_resolved[0]))
                    y0 = float(self._dereference(bbox_resolved[1]))
                    x1 = float(self._dereference(bbox_resolved[2]))
                    y1 = float(self._dereference(bbox_resolved[3]))
                    self.metrics.bbox = BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1)
                except (ValueError, TypeError):
                    pass

        # Embedded font streams: /FontFile2 (TrueType) or /FontFile3 (CFF / OpenType)
        font_file2 = fd.get("FontFile2")
        if font_file2 is not None:
            ff2_obj = self._dereference(font_file2)
            if isinstance(ff2_obj, PDFStream) and len(ff2_obj.data) > 0:
                try:
                    raw_bytes = ff2_obj.get_raw_bytes()
                    filt = ff2_obj.dict.get("Filter")
                    parms = ff2_obj.dict.get("DecodeParms")
                    dec = decode_stream(raw_bytes, filt, parms)
                    self._embedded_font = SFNTFont(dec, name=self.name)
                except Exception:
                    pass

        font_file3 = fd.get("FontFile3")
        if font_file3 is not None:
            ff3_obj = self._dereference(font_file3)
            if isinstance(ff3_obj, PDFStream) and len(ff3_obj.data) > 0:
                try:
                    raw_bytes = ff3_obj.get_raw_bytes()
                    filt = ff3_obj.dict.get("Filter")
                    parms = ff3_obj.dict.get("DecodeParms")
                    dec = decode_stream(raw_bytes, filt, parms)
                    subtype = ff3_obj.dict.get("Subtype")
                    if subtype in ("CIDFontType0C", PDFName("CIDFontType0C"), "Type1C", PDFName("Type1C")):
                        self._embedded_font = CFFFont(dec, name=self.name)
                    else:
                        self._embedded_font = SFNTFont(dec, name=self.name)
                except Exception:
                    pass

    def get_vertical_metrics(self, cid: int) -> Tuple[float, float, float]:
        """Return (w1y, v1x, v1y) vertical metric tuple for CID.

        Returns:
            Tuple[float, float, float]: (vertical_advance_y, origin_x, origin_y)
        """
        if cid in self._vertical_widths:
            return self._vertical_widths[cid]
        w0 = self.get_width(cid)
        return (self._default_dw2[1], w0 / 2.0, self._default_dw2[0])

    def get_width(self, char_code: int) -> float:
        """Return advance width for CID in 1/1000 units."""
        if char_code in self._cid_widths:
            return self._cid_widths[char_code]
        if self._embedded_font is not None:
            gid = self.cid_to_gid(char_code)
            w = self._embedded_font.get_width(gid)
            if w != self._embedded_font.metrics.default_width:
                return w
        return self._default_width
