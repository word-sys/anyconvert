"""Pure-Python ISO/IEC 29500 SpreadsheetML (.xlsx) container packager.

Builds standards-compliant Office Open XML Workbook (.xlsx) archives using
OPCPackage with worksheets, shared strings table, cell styles, column widths,
and merged cell ranges (<mergeCell ref="..."/>) with zero external dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
from typing import Dict, List, Optional, Sequence, Set, Tuple

from anyconvert.exceptions import PackagingError
from anyconvert.packaging.opc import (
    CT_CORE_PROPERTIES,
    CT_EXTENDED_PROPERTIES,
    OPCPackage,
    RT_CORE_PROPERTIES,
    RT_EXTENDED_PROPERTIES,
    RT_OFFICE_DOCUMENT,
    RT_STYLES,
)

# ==============================================================================
# SpreadsheetML Namespaces, Content Types, and Relationship Types
# ==============================================================================

SPREADSHEETML_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
CORE_PROPS_NS = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
DC_NS = "http://purl.org/dc/elements/1.1/"
DCTERMS_NS = "http://purl.org/dc/terms/"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
EXT_PROPS_NS = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
VT_NS = "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"

CT_SPREADSHEET_WORKBOOK = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
)
CT_SPREADSHEET_WORKSHEET = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"
)
CT_SPREADSHEET_STYLES = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"
)
CT_SPREADSHEET_SHARED_STRINGS = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"
)

RT_WORKSHEET = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
)
RT_SHARED_STRINGS = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings"
)

_INVALID_SHEET_CHARS_RE = re.compile(r"[:\\/?*\[\]]")
_STRICT_NUMBER_RE = re.compile(r"^[+-]?(?:0|[1-9]\d*)(?:\.\d+)?$")


# ==============================================================================
# SpreadsheetML Coordinate & Sanitization Helpers
# ==============================================================================


def col_index_to_letter(col_idx: int) -> str:
    """Convert a 0-based column index to an Excel column label (0 -> 'A', 26 -> 'AA')."""
    if col_idx < 0:
        raise PackagingError(f"Column index must be non-negative, got {col_idx}")
    letters: List[str] = []
    n = col_idx + 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters.append(chr(ord("A") + rem))
    return "".join(reversed(letters))


def cell_ref(row_idx: int, col_idx: int) -> str:
    """Format a 0-based (row_idx, col_idx) coordinate as an A1 cell reference."""
    if row_idx < 0 or col_idx < 0:
        raise PackagingError(f"Cell coordinates must be non-negative, got ({row_idx}, {col_idx})")
    return f"{col_index_to_letter(col_idx)}{row_idx + 1}"


def merge_range_ref(r0: int, c0: int, r1: int, c1: int) -> str:
    """Format a 0-based inclusive (r0, c0, r1, c1) range as an A1:B2 reference."""
    if r0 < 0 or c0 < 0 or r1 < r0 or c1 < c0:
        raise PackagingError(
            f"Invalid merge cell bounds: ({r0}, {c0}) to ({r1}, {c1})"
        )
    if r0 == r1 and c0 == c1:
        raise PackagingError(
            f"Merge range must span at least 2 cells, got single cell ({r0}, {c0})"
        )
    return f"{cell_ref(r0, c0)}:{cell_ref(r1, c1)}"


def sanitize_sheet_name(raw_name: str, existing_names: Optional[Set[str]] = None) -> str:
    """Sanitize and deduplicate an Excel worksheet title (max 31 chars, no forbidden chars)."""
    cleaned = _INVALID_SHEET_CHARS_RE.sub(" ", raw_name or "").strip().strip("'")
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        cleaned = "Sheet"
    base = cleaned[:31].rstrip("'") or "Sheet"

    if existing_names is None:
        return base

    lower_used = {n.lower() for n in existing_names}
    if base.lower() not in lower_used:
        existing_names.add(base)
        return base

    counter = 2
    while True:
        suffix = f" ({counter})"
        max_base_len = 31 - len(suffix)
        candidate = f"{base[:max_base_len].rstrip()}{suffix}"
        if candidate.lower() not in lower_used:
            existing_names.add(candidate)
            return candidate
        counter += 1


def sanitize_xlsx_text(text: str) -> str:
    """Strip illegal XML 1.0 C0 control characters and escape XML entities."""
    if not text:
        return ""
    cleaned = "".join(
        ch
        for ch in text
        if ch in ("\t", "\n", "\r")
        or (0x20 <= ord(ch) <= 0xD7FF)
        or (0xE000 <= ord(ch) <= 0xFFFD)
        or (0x10000 <= ord(ch) <= 0x10FFFF)
    )
    return (
        cleaned.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _is_numeric_cell(value: str) -> bool:
    """Return True if value can be safely stored as an IEEE-754 SpreadsheetML number."""
    if not value or len(value) > 15:
        return False
    return bool(_STRICT_NUMBER_RE.match(value))


# ==============================================================================
# Data Models
# ==============================================================================


@dataclass(slots=True)
class XLSXSheet:
    """Worksheet specification for an XLSX workbook.

    Attributes:
        name: Worksheet tab title.
        rows: 2D rectangular grid of cell string values.
        header_row_count: Number of leading header rows styled with bold header format.
        col_widths: Column widths in typographic points (optional; auto-fitted when empty).
        merges: List of 0-based inclusive (r0, c0, r1, c1) merged cell ranges.
    """

    name: str
    rows: List[List[str]] = field(default_factory=list)
    header_row_count: int = 0
    col_widths: List[float] = field(default_factory=list)
    merges: List[Tuple[int, int, int, int]] = field(default_factory=list)


class _SharedStringsBuilder:
    """Deduplicating shared strings table builder for xl/sharedStrings.xml."""

    __slots__ = ("_index_map", "_items", "total_count")

    def __init__(self) -> None:
        self._index_map: Dict[str, int] = {}
        self._items: List[str] = []
        self.total_count: int = 0

    def intern(self, text: str) -> int:
        """Record a string occurrence and return its 0-based shared string index."""
        self.total_count += 1
        existing = self._index_map.get(text)
        if existing is not None:
            return existing
        idx = len(self._items)
        self._items.append(text)
        self._index_map[text] = idx
        return idx

    def to_xml(self) -> str:
        """Serialize xl/sharedStrings.xml."""
        lines = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            (
                f'<sst xmlns="{SPREADSHEETML_NS}" '
                f'count="{self.total_count}" uniqueCount="{len(self._items)}">'
            ),
        ]
        for item in self._items:
            escaped = sanitize_xlsx_text(item)
            needs_preserve = (
                bool(item)
                and (
                    item[0].isspace()
                    or item[-1].isspace()
                    or "\n" in item
                    or "\r" in item
                    or "\t" in item
                )
            )
            attr = ' xml:space="preserve"' if needs_preserve else ""
            lines.append(f"  <si><t{attr}>{escaped}</t></si>")
        lines.append("</sst>")
        return "\n".join(lines)


# ==============================================================================
# XLSX Package Builder
# ==============================================================================


class XLSXPackage:
    """Pure-Python ISO/IEC 29500-2 SpreadsheetML (.xlsx) workbook packager."""

    __slots__ = ("sheets", "metadata")

    def __init__(self, metadata: Optional[Dict[str, str]] = None) -> None:
        self.sheets: List[XLSXSheet] = []
        self.metadata: Dict[str, str] = dict(metadata) if metadata else {}

    def add_sheet(
        self,
        name: str,
        rows: Sequence[Sequence[str]],
        *,
        header_row_count: int = 0,
        col_widths: Optional[Sequence[float]] = None,
        merges: Optional[Sequence[Tuple[int, int, int, int]]] = None,
    ) -> XLSXSheet:
        """Add a worksheet to the workbook with automatic name sanitization and deduplication."""
        used_names = {s.name for s in self.sheets}
        safe_name = sanitize_sheet_name(name, used_names)
        sheet = XLSXSheet(
            name=safe_name,
            rows=[list(r) for r in rows],
            header_row_count=max(0, header_row_count),
            col_widths=list(col_widths) if col_widths else [],
            merges=list(merges) if merges else [],
        )
        self.sheets.append(sheet)
        return sheet

    def build_opc_package(self) -> OPCPackage:
        """Assemble all SpreadsheetML parts and relationships into an OPCPackage."""
        if not self.sheets:
            raise PackagingError("Cannot build XLSX package with zero worksheets")

        pkg = OPCPackage()
        sst = _SharedStringsBuilder()

        # 1. Build worksheets first (populates shared strings table)
        worksheet_xmls: List[str] = []
        for sheet in self.sheets:
            worksheet_xmls.append(self._build_worksheet_xml(sheet, sst))

        # 2. Add xl/workbook.xml and root relationship
        wb_xml = self._build_workbook_xml()
        pkg.add_part("xl/workbook.xml", wb_xml, content_type=CT_SPREADSHEET_WORKBOOK)
        pkg.add_package_relationship(RT_OFFICE_DOCUMENT, "xl/workbook.xml", rel_id="rId1")

        # 3. Add worksheets and workbook relationships
        for idx, ws_xml in enumerate(worksheet_xmls, start=1):
            part_path = f"xl/worksheets/sheet{idx}.xml"
            rel_target = f"worksheets/sheet{idx}.xml"
            pkg.add_part(part_path, ws_xml, content_type=CT_SPREADSHEET_WORKSHEET)
            pkg.add_part_relationship(
                "xl/workbook.xml",
                RT_WORKSHEET,
                rel_target,
                rel_id=f"rId{idx}",
            )

        # 4. Add xl/styles.xml
        styles_rel_id = f"rId{len(self.sheets) + 1}"
        pkg.add_part(
            "xl/styles.xml",
            self._build_styles_xml(),
            content_type=CT_SPREADSHEET_STYLES,
        )
        pkg.add_part_relationship(
            "xl/workbook.xml",
            RT_STYLES,
            "styles.xml",
            rel_id=styles_rel_id,
        )

        # 5. Add xl/sharedStrings.xml
        sst_rel_id = f"rId{len(self.sheets) + 2}"
        pkg.add_part(
            "xl/sharedStrings.xml",
            sst.to_xml(),
            content_type=CT_SPREADSHEET_SHARED_STRINGS,
        )
        pkg.add_part_relationship(
            "xl/workbook.xml",
            RT_SHARED_STRINGS,
            "sharedStrings.xml",
            rel_id=sst_rel_id,
        )

        # 6. Add docProps/core.xml and docProps/app.xml
        pkg.add_part(
            "docProps/core.xml",
            self._build_core_props_xml(),
            content_type=CT_CORE_PROPERTIES,
        )
        pkg.add_package_relationship(RT_CORE_PROPERTIES, "docProps/core.xml", rel_id="rId2")

        pkg.add_part(
            "docProps/app.xml",
            self._build_app_props_xml(),
            content_type=CT_EXTENDED_PROPERTIES,
        )
        pkg.add_package_relationship(RT_EXTENDED_PROPERTIES, "docProps/app.xml", rel_id="rId3")

        return pkg

    def to_bytes(self) -> bytes:
        """Serialize the complete XLSX package into an in-memory ZIP byte buffer."""
        return self.build_opc_package().to_bytes()

    def _build_workbook_xml(self) -> str:
        lines = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            f'<workbook xmlns="{SPREADSHEETML_NS}" xmlns:r="{OFFICE_REL_NS}">',
            "  <sheets>",
        ]
        for idx, sheet in enumerate(self.sheets, start=1):
            escaped_name = sanitize_xlsx_text(sheet.name)
            lines.append(
                f'    <sheet name="{escaped_name}" sheetId="{idx}" r:id="rId{idx}"/>'
            )
        lines.append("  </sheets>")
        lines.append("</workbook>")
        return "\n".join(lines)

    @staticmethod
    def _build_styles_xml() -> str:
        """Generate a clean ISO/IEC 29500-1 xl/styles.xml with header and data cell styles."""
        return "\n".join(
            [
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
                f'<styleSheet xmlns="{SPREADSHEETML_NS}">',
                '  <fonts count="2">',
                '    <font><sz val="11"/><name val="Calibri"/></font>',
                '    <font><b/><sz val="11"/><name val="Calibri"/></font>',
                "  </fonts>",
                '  <fills count="3">',
                '    <fill><patternFill patternType="none"/></fill>',
                '    <fill><patternFill patternType="gray125"/></fill>',
                '    <fill><patternFill patternType="solid"><fgColor rgb="FFF0F4F8"/><bgColor indexed="64"/></patternFill></fill>',
                "  </fills>",
                '  <borders count="2">',
                "    <border><left/><right/><top/><bottom/><diagonal/></border>",
                (
                    "    <border>"
                    '<left style="thin"><color rgb="FFD0D7DE"/></left>'
                    '<right style="thin"><color rgb="FFD0D7DE"/></right>'
                    '<top style="thin"><color rgb="FFD0D7DE"/></top>'
                    '<bottom style="thin"><color rgb="FFD0D7DE"/></bottom>'
                    "<diagonal/>"
                    "</border>"
                ),
                "  </borders>",
                '  <cellStyleXfs count="1">',
                '    <xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>',
                "  </cellStyleXfs>",
                '  <cellXfs count="3">',
                '    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>',
                (
                    '    <xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" '
                    'applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1">'
                    '<alignment vertical="center" wrapText="1"/>'
                    "</xf>"
                ),
                (
                    '    <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" '
                    'applyBorder="1" applyAlignment="1">'
                    '<alignment vertical="top" wrapText="1"/>'
                    "</xf>"
                ),
                "  </cellXfs>",
                '  <cellStyles count="1">',
                '    <cellStyle name="Normal" xfId="0" builtinId="0"/>',
                "  </cellStyles>",
                "</styleSheet>",
            ]
        )

    def _build_worksheet_xml(
        self,
        sheet: XLSXSheet,
        sst: _SharedStringsBuilder,
    ) -> str:
        num_rows = len(sheet.rows)
        num_cols = max((len(r) for r in sheet.rows), default=0)

        if num_rows > 0 and num_cols > 0:
            dim_ref = f"A1:{cell_ref(num_rows - 1, num_cols - 1)}"
        else:
            dim_ref = "A1"

        lines = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            f'<worksheet xmlns="{SPREADSHEETML_NS}" xmlns:r="{OFFICE_REL_NS}">',
            f'  <dimension ref="{dim_ref}"/>',
            '  <sheetViews><sheetView workbookViewId="0"/></sheetViews>',
            '  <sheetFormatPr defaultRowHeight="15"/>',
        ]

        # Column widths (<cols>)
        if num_cols > 0:
            col_widths_chars = self._compute_column_widths(sheet, num_cols)
            lines.append("  <cols>")
            for c_idx, width_ch in enumerate(col_widths_chars, start=1):
                lines.append(
                    f'    <col min="{c_idx}" max="{c_idx}" width="{width_ch:.2f}" customWidth="1"/>'
                )
            lines.append("  </cols>")

        # Validated non-overlapping merge ranges
        valid_merges = self._validate_sheet_merges(sheet.merges, num_rows, num_cols)
        covered_by_merge: Set[Tuple[int, int]] = set()
        for r0, c0, r1, c1 in valid_merges:
            for mr in range(r0, r1 + 1):
                for mc in range(c0, c1 + 1):
                    if not (mr == r0 and mc == c0):
                        covered_by_merge.add((mr, mc))

        # Sheet data (<sheetData>)
        if num_rows == 0 or num_cols == 0:
            lines.append("  <sheetData/>")
        else:
            lines.append("  <sheetData>")
            for r_idx, row in enumerate(sheet.rows):
                row_num = r_idx + 1
                style_id = 1 if r_idx < sheet.header_row_count else 2
                lines.append(f'    <row r="{row_num}">')
                for c_idx in range(num_cols):
                    ref = cell_ref(r_idx, c_idx)
                    raw_val = row[c_idx] if c_idx < len(row) else ""
                    if (r_idx, c_idx) in covered_by_merge and not raw_val:
                        # Emit empty styled cell so merged region borders are continuous
                        lines.append(f'      <c r="{ref}" s="{style_id}"/>')
                    elif not raw_val:
                        lines.append(f'      <c r="{ref}" s="{style_id}"/>')
                    elif _is_numeric_cell(raw_val):
                        lines.append(f'      <c r="{ref}" s="{style_id}"><v>{raw_val}</v></c>')
                    else:
                        s_idx = sst.intern(raw_val)
                        lines.append(f'      <c r="{ref}" s="{style_id}" t="s"><v>{s_idx}</v></c>')
                lines.append("    </row>")
            lines.append("  </sheetData>")

        # Merged cells (<mergeCells>)
        if valid_merges:
            lines.append(f'  <mergeCells count="{len(valid_merges)}">')
            for r0, c0, r1, c1 in valid_merges:
                m_ref = merge_range_ref(r0, c0, r1, c1)
                lines.append(f'    <mergeCell ref="{m_ref}"/>')
            lines.append("  </mergeCells>")

        lines.append("</worksheet>")
        return "\n".join(lines)

    @staticmethod
    def _compute_column_widths(sheet: XLSXSheet, num_cols: int) -> List[float]:
        """Compute Excel character-unit column widths from points or cell text lengths."""
        widths: List[float] = []
        for c_idx in range(num_cols):
            # 1. Estimate from cell content character length
            max_chars = 8
            for row in sheet.rows:
                if c_idx < len(row) and row[c_idx]:
                    for line in row[c_idx].splitlines():
                        if len(line) > max_chars:
                            max_chars = len(line)
            content_w = min(50.0, max(10.0, float(max_chars + 4)))

            # 2. If PDF column width in points is available, blend/use it (1 char ~ 5.25 pt)
            if c_idx < len(sheet.col_widths) and sheet.col_widths[c_idx] > 0.0:
                pt_w = min(60.0, max(8.0, sheet.col_widths[c_idx] / 5.25))
                widths.append(round(max(pt_w, min(content_w, 32.0)), 2))
            else:
                widths.append(round(content_w, 2))
        return widths

    @staticmethod
    def _validate_sheet_merges(
        merges: Sequence[Tuple[int, int, int, int]],
        num_rows: int,
        num_cols: int,
    ) -> List[Tuple[int, int, int, int]]:
        """Filter and validate non-overlapping merge ranges within sheet bounds."""
        if not merges or num_rows <= 0 or num_cols <= 0:
            return []
        accepted: List[Tuple[int, int, int, int]] = []
        occupied: Set[Tuple[int, int]] = set()
        for r0, c0, r1, c1 in merges:
            cr0 = max(0, min(r0, num_rows - 1))
            cc0 = max(0, min(c0, num_cols - 1))
            cr1 = max(cr0, min(r1, num_rows - 1))
            cc1 = max(cc0, min(c1, num_cols - 1))
            if cr0 == cr1 and cc0 == cc1:
                continue
            cells = {
                (r, c)
                for r in range(cr0, cr1 + 1)
                for c in range(cc0, cc1 + 1)
            }
            if cells & occupied:
                continue
            occupied.update(cells)
            accepted.append((cr0, cc0, cr1, cc1))
        return accepted

    def _build_core_props_xml(self) -> str:
        lowered = {
            k.lstrip("/").lower(): v.strip()
            for k, v in self.metadata.items()
            if v and v.strip()
        }
        title = sanitize_xlsx_text(lowered.get("title", ""))
        creator = sanitize_xlsx_text(lowered.get("author", "anyconvert"))
        subject = sanitize_xlsx_text(lowered.get("subject", ""))
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        lines = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            (
                f'<cp:coreProperties xmlns:cp="{CORE_PROPS_NS}" '
                f'xmlns:dc="{DC_NS}" xmlns:dcterms="{DCTERMS_NS}" '
                f'xmlns:xsi="{XSI_NS}">'
            ),
            f"  <dc:title>{title}</dc:title>",
            f"  <dc:subject>{subject}</dc:subject>",
            f"  <dc:creator>{creator}</dc:creator>",
            f'  <dcterms:created xsi:type="dcterms:W3CDTF">{now_iso}</dcterms:created>',
            f'  <dcterms:modified xsi:type="dcterms:W3CDTF">{now_iso}</dcterms:modified>',
            "</cp:coreProperties>",
        ]
        return "\n".join(lines)

    def _build_app_props_xml(self) -> str:
        lines = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            f'<Properties xmlns="{EXT_PROPS_NS}" xmlns:vt="{VT_NS}">',
            "  <Application>anyconvert</Application>",
            "  <HeadingPairs>",
            '    <vt:vector size="2" baseType="variant">',
            "      <vt:variant><vt:lpstr>Worksheets</vt:lpstr></vt:variant>",
            f"      <vt:variant><vt:i4>{len(self.sheets)}</vt:i4></vt:variant>",
            "    </vt:vector>",
            "  </HeadingPairs>",
            "  <TitlesOfParts>",
            f'    <vt:vector size="{len(self.sheets)}" baseType="lpstr">',
        ]
        for sheet in self.sheets:
            lines.append(f"      <vt:lpstr>{sanitize_xlsx_text(sheet.name)}</vt:lpstr>")
        lines.extend(
            [
                "    </vt:vector>",
                "  </TitlesOfParts>",
                "</Properties>",
            ]
        )
        return "\n".join(lines)


__all__ = [
    "SPREADSHEETML_NS",
    "OFFICE_REL_NS",
    "CT_SPREADSHEET_WORKBOOK",
    "CT_SPREADSHEET_WORKSHEET",
    "CT_SPREADSHEET_STYLES",
    "CT_SPREADSHEET_SHARED_STRINGS",
    "RT_WORKSHEET",
    "RT_SHARED_STRINGS",
    "XLSXSheet",
    "XLSXPackage",
    "col_index_to_letter",
    "cell_ref",
    "merge_range_ref",
    "sanitize_sheet_name",
    "sanitize_xlsx_text",
]
