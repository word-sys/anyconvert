"""TrueType and OpenType (SFNT) table directory and font metrics parser.

Parses binary SFNT containers adhering to ISO/IEC 14496-22 (OpenType) and Apple TrueType:
- Table directory: head, hhea, hmtx, maxp, cmap, OS/2, post.
- Extracts unitsPerEm, ascender, descender, horizontal advance widths, and glyph mappings.
- Supports cmap formats 0, 4, and 12.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from anyconvert.common.geometry import BoundingBox
from anyconvert.exceptions import PDFFontError
from anyconvert.pdf.typography.font import BaseFont, FontMetrics


@dataclass(frozen=True, slots=True)
class SFNTTableRecord:
    """Represents an entry in the SFNT table directory."""

    tag: str
    checksum: int
    offset: int
    length: int


class SFNTFont(BaseFont):
    """Parses and resolves TrueType / OpenType font tables and typographic metrics."""

    __slots__ = (
        "_data",
        "_tables",
        "_glyph_widths",
        "_cmap_char_to_glyph",
        "_num_glyphs",
    )

    def __init__(self, data: bytes, name: str = "EmbeddedFont") -> None:
        """Initialize SFNTFont by parsing raw TrueType/OpenType font bytes.

        Args:
            data: Raw SFNT binary data stream.
            name: Font name identifier.

        Raises:
            PDFFontError: If font data is malformed or missing required tables.
        """
        super().__init__(name=name)
        self._data: bytes = data
        self._tables: Dict[str, SFNTTableRecord] = {}
        self._glyph_widths: Dict[int, float] = {}
        self._cmap_char_to_glyph: Dict[int, int] = {}
        self._num_glyphs: int = 0

        self._parse_table_directory()
        self._parse_tables()

    def _get_table_data(self, tag: str) -> Optional[bytes]:
        """Return raw slice for table tag, or None if table is not present."""
        record = self._tables.get(tag)
        if record is None:
            return None
        end = record.offset + record.length
        if end > len(self._data):
            return None
        return self._data[record.offset : end]

    def _parse_table_directory(self) -> None:
        """Parse 12-byte SFNT header and table directory records."""
        data = self._data
        if len(data) < 12:
            raise PDFFontError("SFNT font data too small (< 12 bytes)", font_name=self.name)

        sfnt_version, num_tables = struct.unpack_from(">IH", data, 0)[:2]
        # Valid sfnt versions: 0x00010000 (TrueType), 0x4F54544F ('OTTO' OpenType/CFF), 0x74727565 ('true')
        valid_versions = (0x00010000, 0x4F54544F, 0x74727565)
        if sfnt_version not in valid_versions:
            # Fallback: check if 'OTTO' or 'true' in ascii
            pass

        pos = 12
        if len(data) < pos + num_tables * 16:
            raise PDFFontError(
                f"SFNT table directory truncated ({num_tables} tables expected)",
                font_name=self.name,
            )

        for _ in range(num_tables):
            tag_bytes, checksum, offset, length = struct.unpack_from(">4sIII", data, pos)
            pos += 16
            tag = tag_bytes.decode("ascii", errors="replace")
            self._tables[tag] = SFNTTableRecord(
                tag=tag,
                checksum=checksum,
                offset=offset,
                length=length,
            )

    def _parse_tables(self) -> None:
        """Parse head, maxp, hhea, hmtx, OS/2, post, and cmap tables."""
        # 1. Parse 'head'
        head_data = self._get_table_data("head")
        if head_data is None or len(head_data) < 54:
            raise PDFFontError("Missing or corrupt 'head' table in SFNT font", font_name=self.name)

        units_per_em = struct.unpack_from(">H", head_data, 18)[0]
        if units_per_em <= 0:
            units_per_em = 1000

        x_min, y_min, x_max, y_max = struct.unpack_from(">hhhh", head_data, 36)
        scale = 1000.0 / units_per_em

        self.metrics.units_per_em = units_per_em
        self.metrics.bbox = BoundingBox(
            x0=x_min * scale,
            y0=y_min * scale,
            x1=x_max * scale,
            y1=y_max * scale,
        )

        # 2. Parse 'maxp'
        maxp_data = self._get_table_data("maxp")
        num_glyphs = 0
        if maxp_data is not None and len(maxp_data) >= 6:
            num_glyphs = struct.unpack_from(">H", maxp_data, 4)[0]
        self._num_glyphs = num_glyphs

        # 3. Parse 'hhea'
        hhea_data = self._get_table_data("hhea")
        num_h_metrics = 0
        if hhea_data is not None and len(hhea_data) >= 36:
            ascender, descender = struct.unpack_from(">hh", hhea_data, 4)
            num_h_metrics = struct.unpack_from(">H", hhea_data, 34)[0]
            self.metrics.ascender = ascender * scale
            self.metrics.descender = descender * scale

        # 4. Parse 'hmtx' (Horizontal metrics)
        hmtx_data = self._get_table_data("hmtx")
        last_width = 0.0
        if hmtx_data is not None:
            pos = 0
            # Read advance widths for num_h_metrics glyphs
            for gid in range(num_h_metrics):
                if pos + 4 <= len(hmtx_data):
                    adv_width, _ = struct.unpack_from(">Hh", hmtx_data, pos)
                    norm_width = adv_width * scale
                    self._glyph_widths[gid] = norm_width
                    last_width = norm_width
                    pos += 4

            # Remaining glyphs share the last advance width
            for gid in range(num_h_metrics, num_glyphs):
                self._glyph_widths[gid] = last_width

        # Default width
        if 0 in self._glyph_widths:
            self.metrics.default_width = self._glyph_widths[0]
        elif last_width > 0:
            self.metrics.default_width = last_width

        # 5. Parse 'OS/2' (Optional)
        os2_data = self._get_table_data("OS/2")
        if os2_data is not None and len(os2_data) >= 64:
            us_weight = struct.unpack_from(">H", os2_data, 4)[0]
            fs_selection = struct.unpack_from(">H", os2_data, 62)[0]
            self.metrics.is_bold = (us_weight >= 700) or bool(fs_selection & 0x20)
            self.metrics.is_italic = bool(fs_selection & 0x01)

            if len(os2_data) >= 90:
                sx_height, s_cap_height = struct.unpack_from(">hh", os2_data, 86)
                if s_cap_height > 0:
                    self.metrics.cap_height = s_cap_height * scale
                if sx_height > 0:
                    self.metrics.x_height = sx_height * scale

        # 6. Parse 'post' (Optional)
        post_data = self._get_table_data("post")
        if post_data is not None and len(post_data) >= 16:
            italic_raw, is_fixed = struct.unpack_from(">iI", post_data, 4)[:2]
            self.metrics.italic_angle = italic_raw / 65536.0
            self.metrics.is_monospace = is_fixed != 0

        # 7. Parse 'cmap' table
        cmap_data = self._get_table_data("cmap")
        if cmap_data is not None:
            self._parse_cmap_table(cmap_data)

        # Build character code -> width map from cmap and glyph widths
        for char_code, gid in self._cmap_char_to_glyph.items():
            if gid in self._glyph_widths:
                self.widths[char_code] = self._glyph_widths[gid]

    def _parse_cmap_table(self, data: bytes) -> None:
        """Parse character-to-glyph mapping table."""
        if len(data) < 4:
            return

        version, num_subtables = struct.unpack_from(">HH", data, 0)
        subtable_offsets: List[int] = []

        # Find best subtable: Unicode 3.0 / BMP (platform 0, or platform 3 encoding 1 or 10)
        pos = 4
        for _ in range(num_subtables):
            if pos + 8 > len(data):
                break
            plat_id, enc_id, offset = struct.unpack_from(">HHI", data, pos)
            pos += 8
            subtable_offsets.append(offset)

        for offset in subtable_offsets:
            if offset + 6 > len(data):
                continue
            format_type = struct.unpack_from(">H", data, offset)[0]

            if format_type == 4:
                # Format 4: Segment mapping for BMP Unicode
                self._parse_cmap_format_4(data, offset)
                break
            elif format_type == 12:
                # Format 12: 32-bit segmented coverage
                self._parse_cmap_format_12(data, offset)
                break
            elif format_type == 0 and not self._cmap_char_to_glyph:
                # Format 0: 256-byte byte mapping
                self._parse_cmap_format_0(data, offset)

    def _parse_cmap_format_0(self, data: bytes, offset: int) -> None:
        """Parse cmap Format 0 (standard 256-byte table)."""
        if offset + 6 + 256 > len(data):
            return
        for char_code in range(256):
            gid = data[offset + 6 + char_code]
            if gid != 0:
                self._cmap_char_to_glyph[char_code] = gid

    def _parse_cmap_format_4(self, data: bytes, offset: int) -> None:
        """Parse cmap Format 4 (segmented mapping for 16-bit BMP Unicode)."""
        if offset + 14 > len(data):
            return

        length = struct.unpack_from(">H", data, offset + 2)[0]
        seg_count_x2 = struct.unpack_from(">H", data, offset + 6)[0]
        seg_count = seg_count_x2 // 2
        if offset + 14 + seg_count * 8 > len(data):
            return

        end_code_offset = offset + 14
        start_code_offset = end_code_offset + seg_count * 2 + 2  # Skip 2 reserved pad bytes
        id_delta_offset = start_code_offset + seg_count * 2
        id_range_offset_base = id_delta_offset + seg_count * 2

        end_codes = struct.unpack_from(f">{seg_count}H", data, end_code_offset)
        start_codes = struct.unpack_from(f">{seg_count}H", data, start_code_offset)
        id_deltas = struct.unpack_from(f">{seg_count}h", data, id_delta_offset)

        for i in range(seg_count):
            start = start_codes[i]
            end = end_codes[i]
            delta = id_deltas[i]
            range_off_pos = id_range_offset_base + i * 2
            range_off = struct.unpack_from(">H", data, range_off_pos)[0]

            if start == 0xFFFF or end == 0xFFFF:
                break

            for code in range(start, end + 1):
                if range_off == 0:
                    gid = (code + delta) & 0xFFFF
                else:
                    # Glyph ID is located in glyphIdArray
                    # Address = range_off_pos + range_off + (code - start) * 2
                    glyph_pos = range_off_pos + range_off + (code - start) * 2
                    if glyph_pos + 2 <= len(data):
                        val = struct.unpack_from(">H", data, glyph_pos)[0]
                        gid = (val + delta) & 0xFFFF if val != 0 else 0
                    else:
                        gid = 0

                if gid != 0:
                    self._cmap_char_to_glyph[code] = gid

    def _parse_cmap_format_12(self, data: bytes, offset: int) -> None:
        """Parse cmap Format 12 (segmented 32-bit Unicode coverage)."""
        if offset + 16 > len(data):
            return

        n_groups = struct.unpack_from(">I", data, offset + 12)[0]
        pos = offset + 16
        for _ in range(n_groups):
            if pos + 12 > len(data):
                break
            start_char, end_char, start_gid = struct.unpack_from(">III", data, pos)
            pos += 12

            for code in range(start_char, end_char + 1):
                gid = start_gid + (code - start_char)
                self._cmap_char_to_glyph[code] = gid

    def get_glyph_id(self, char_code: int) -> Optional[int]:
        """Return Glyph ID for character code, or None if unmapped."""
        return self._cmap_char_to_glyph.get(char_code)

    def get_glyph_width_by_id(self, glyph_id: int) -> float:
        """Return advance width for Glyph ID (normalized to 1/1000 units)."""
        return self._glyph_widths.get(glyph_id, self.metrics.default_width)
