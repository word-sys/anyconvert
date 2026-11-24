"""High-precision PDF table extraction and RFC 4180 CSV emitter.

Extracts structured Table IR nodes into normalized 2D cell grids with full
col_span/row_span occupancy tracking, automatic multi-page continuous table
merging (with repeated-header deduplication), multi-table indexing, and strict
RFC 4180 CSV serialization using only the Python standard library.
"""

from __future__ import annotations

import csv as _stdlib_csv
from dataclasses import dataclass, field
import io
from typing import List, Optional, Sequence, Tuple

from anyconvert.emitters.base import BaseEmitter, ConversionMode
from anyconvert.exceptions import SerializationError
from anyconvert.ir.model import (
    BlockNode,
    DocumentIR,
    DocumentPage,
    Paragraph,
    Table,
    TableCell,
)


@dataclass(slots=True)
class ExtractedTable:
    """A normalized, rectangular table extracted from one or more DocumentPages.

    Attributes:
        index: Zero-based logical table index across the document.
        page_numbers: Ordered list of 1-based page numbers spanned by this table.
        rows: Rectangular 2D matrix of cell text strings.
        header_row_count: Number of leading header rows in `rows`.
        col_widths: Column widths in typographic points (may be empty if unknown).
        merges: List of 0-based inclusive merged cell ranges (r0, c0, r1, c1).
    """

    index: int
    page_numbers: List[int] = field(default_factory=list)
    rows: List[List[str]] = field(default_factory=list)
    header_row_count: int = 0
    col_widths: List[float] = field(default_factory=list)
    merges: List[Tuple[int, int, int, int]] = field(default_factory=list)

    @property
    def num_rows(self) -> int:
        """Total number of rows in the normalized grid."""
        return len(self.rows)

    @property
    def num_cols(self) -> int:
        """Total number of columns in the normalized grid."""
        return len(self.rows[0]) if self.rows else 0


def _extract_cell_text(cell: TableCell) -> str:
    """Extract clean text from a TableCell, flattening nested paragraphs and sub-tables."""
    lines: List[str] = []
    for block in cell.content:
        if isinstance(block, Paragraph):
            txt = block.text.strip()
            if txt:
                lines.append(txt)
        elif isinstance(block, Table):
            sub_grid, _, _ = table_to_grid(block)
            for sub_row in sub_grid:
                joined = " | ".join(c for c in sub_row if c)
                if joined:
                    lines.append(joined)
    return "\n".join(lines)


def table_to_grid(
    table: Table,
    *,
    fill_merged_cells: bool = False,
) -> Tuple[List[List[str]], int, List[Tuple[int, int, int, int]]]:
    """Normalize a Table IR node into a rectangular 2D string grid.

    Resolves arbitrary col_span and row_span overlaps via a 2D occupancy matrix
    so columns never drift when cells span horizontally or vertically.

    Args:
        table: DocumentIR Table node.
        fill_merged_cells: When True, replicate the anchor cell text across all
            spanned slots; when False (default), covered slots contain "".

    Returns:
        Tuple of (grid, header_row_count, merges) where merges holds 0-based
        inclusive (r0, c0, r1, c1) tuples for cells with col_span > 1 or row_span > 1.
    """
    if not table.rows:
        return [], 0, []

    num_rows = len(table.rows)
    grid: List[List[str]] = [[] for _ in range(num_rows)]
    occupied: List[List[bool]] = [[] for _ in range(num_rows)]
    merges: List[Tuple[int, int, int, int]] = []
    max_cols = len(table.col_widths)

    def _ensure_dims(target_r: int, target_c: int) -> None:
        while len(grid) <= target_r:
            grid.append([])
            occupied.append([])
        while len(grid[target_r]) <= target_c:
            grid[target_r].append("")
            occupied[target_r].append(False)

    for r_idx, row in enumerate(table.rows):
        c_idx = 0
        for cell in row.cells:
            while c_idx < len(occupied[r_idx]) and occupied[r_idx][c_idx]:
                c_idx += 1

            c_span = max(1, int(cell.col_span))
            r_span = max(1, int(cell.row_span))
            cell_text = _extract_cell_text(cell)

            for dr in range(r_span):
                tr = r_idx + dr
                for dc in range(c_span):
                    tc = c_idx + dc
                    _ensure_dims(tr, tc)
                    occupied[tr][tc] = True
                    if dr == 0 and dc == 0:
                        grid[tr][tc] = cell_text
                    elif fill_merged_cells:
                        grid[tr][tc] = cell_text
                    else:
                        grid[tr][tc] = ""

            if c_span > 1 or r_span > 1:
                merges.append((r_idx, c_idx, r_idx + r_span - 1, c_idx + c_span - 1))

            if c_idx + c_span > max_cols:
                max_cols = c_idx + c_span
            c_idx += c_span

    # Pad every row to exact rectangular width
    if max_cols == 0:
        return [], 0, []
    for row_vals in grid:
        if len(row_vals) < max_cols:
            row_vals.extend([""] * (max_cols - len(row_vals)))

    header_row_count = 0
    for row in table.rows:
        if row.is_header:
            header_row_count += 1
        else:
            break

    return grid, header_row_count, merges


def _normalize_row_signature(row: Sequence[str]) -> Tuple[str, ...]:
    """Normalize a row's cells for repeated-header comparison across page breaks."""
    return tuple(" ".join(cell.split()).lower() for cell in row)


def _col_widths_compatible(w1: Sequence[float], w2: Sequence[float], tol: float = 0.25) -> bool:
    """Return True if two column-width vectors are dimensionally compatible."""
    if not w1 or not w2:
        return True
    if len(w1) != len(w2):
        return False
    for a, b in zip(w1, w2):
        denom = max(a, b, 1.0)
        if abs(a - b) / denom > tol:
            return False
    return True


def _is_meaningful_prose(block: BlockNode) -> bool:
    """Return True if block is non-empty prose/heading that breaks table continuity."""
    if isinstance(block, Paragraph):
        return bool(block.text.strip())
    return False


def _find_page_tables(page: DocumentPage) -> List[Tuple[Table, bool, bool]]:
    """Return (table, is_first_meaningful, is_last_meaningful) tuples for a page."""
    meaningful_indices = [
        idx
        for idx, blk in enumerate(page.blocks)
        if isinstance(blk, Table) or _is_meaningful_prose(blk)
    ]
    if not meaningful_indices:
        return []
    first_idx = meaningful_indices[0]
    last_idx = meaningful_indices[-1]

    found: List[Tuple[Table, bool, bool]] = []
    for idx in meaningful_indices:
        blk = page.blocks[idx]
        if isinstance(blk, Table):
            found.append((blk, idx == first_idx, idx == last_idx))
    return found


def extract_tables_from_ir(
    doc_ir: DocumentIR,
    *,
    merge_multipage: bool = True,
    fill_merged_cells: bool = False,
) -> List[ExtractedTable]:
    """Extract all tables from DocumentIR with optional multi-page continuation merging.

    When `merge_multipage=True`, a table starting at the top of page P+1 immediately
    following a table at the bottom of page P with matching column count and compatible
    column widths (or identical repeated header row) is merged into a single logical
    ExtractedTable, deduplicating any repeated header row.

    Args:
        doc_ir: Validated DocumentIR structure.
        merge_multipage: Merge continuous tables split across consecutive pages.
        fill_merged_cells: Replicate anchor text across covered col_span/row_span slots.

    Returns:
        Ordered list of ExtractedTable objects indexed 0..N-1.
    """
    extracted: List[ExtractedTable] = []
    prev_ended_page = False
    prev_page_num = -1

    for page in doc_ir.pages:
        page_tables = _find_page_tables(page)
        if not page_tables:
            prev_ended_page = False
            prev_page_num = page.page_number
            continue

        for tbl, is_first, is_last in page_tables:
            grid, hdr_count, merges = table_to_grid(
                tbl,
                fill_merged_cells=fill_merged_cells,
            )
            if not grid:
                continue

            col_widths = list(tbl.col_widths)
            num_cols = len(grid[0])

            # Check multi-page continuation criteria
            can_merge = (
                merge_multipage
                and bool(extracted)
                and prev_ended_page
                and is_first
                and page.page_number == prev_page_num + 1
                and extracted[-1].num_cols == num_cols
            )
            if can_merge:
                prev_tbl = extracted[-1]
                same_first_row = bool(prev_tbl.rows) and (
                    _normalize_row_signature(prev_tbl.rows[0]) == _normalize_row_signature(grid[0])
                )
                widths_ok = _col_widths_compatible(prev_tbl.col_widths, col_widths)
                if widths_ok or same_first_row:
                    # Deduplicate repeated header row on continuation page
                    skip_rows = 0
                    if same_first_row and (prev_tbl.header_row_count > 0 or hdr_count > 0):
                        skip_rows = 1

                    row_offset = prev_tbl.num_rows
                    appended_rows = grid[skip_rows:]
                    prev_tbl.rows.extend(appended_rows)
                    for r0, c0, r1, c1 in merges:
                        if r1 < skip_rows:
                            continue
                        adj_r0 = max(0, r0 - skip_rows) + row_offset
                        adj_r1 = max(0, r1 - skip_rows) + row_offset
                        prev_tbl.merges.append((adj_r0, c0, adj_r1, c1))
                    if page.page_number not in prev_tbl.page_numbers:
                        prev_tbl.page_numbers.append(page.page_number)
                    prev_ended_page = is_last
                    prev_page_num = page.page_number
                    continue

            extracted.append(
                ExtractedTable(
                    index=len(extracted),
                    page_numbers=[page.page_number],
                    rows=grid,
                    header_row_count=hdr_count,
                    col_widths=col_widths,
                    merges=merges,
                )
            )
            prev_ended_page = is_last
            prev_page_num = page.page_number

    return extracted


def serialize_table_to_csv(
    table: ExtractedTable,
    *,
    delimiter: str = ",",
    lineterminator: str = "\r\n",
) -> str:
    """Serialize a single ExtractedTable into an RFC 4180 CSV string."""
    buf = io.StringIO()
    writer = _stdlib_csv.writer(
        buf,
        delimiter=delimiter,
        quotechar='"',
        quoting=_stdlib_csv.QUOTE_MINIMAL,
        doublequote=True,
        lineterminator=lineterminator,
    )
    for row in table.rows:
        writer.writerow(row)
    return buf.getvalue()


class CsvEmitter(BaseEmitter):
    """Pure-Python RFC 4180 CSV table extraction emitter."""

    __slots__ = (
        "table_index",
        "merge_multipage",
        "fill_merged_cells",
        "export_tables_only",
        "delimiter",
        "lineterminator",
        "utf8_bom",
    )

    def __init__(
        self,
        table_index: Optional[int] = None,
        merge_multipage: bool = True,
        fill_merged_cells: bool = False,
        export_tables_only: bool = False,
        delimiter: str = ",",
        lineterminator: str = "\r\n",
        utf8_bom: bool = False,
    ) -> None:
        if len(delimiter) != 1:
            raise ValueError(f"CSV delimiter must be a single character, got {delimiter!r}")
        self.table_index: Optional[int] = table_index
        self.merge_multipage: bool = merge_multipage
        self.fill_merged_cells: bool = fill_merged_cells
        self.export_tables_only: bool = export_tables_only
        self.delimiter: str = delimiter
        self.lineterminator: str = lineterminator
        self.utf8_bom: bool = utf8_bom

    def extract_tables(self, doc_ir: DocumentIR) -> List[ExtractedTable]:
        """Extract all normalized tables from DocumentIR using emitter settings."""
        return extract_tables_from_ir(
            doc_ir,
            merge_multipage=self.merge_multipage,
            fill_merged_cells=self.fill_merged_cells,
        )

    def render(self, doc_ir: DocumentIR) -> str:
        """Render extracted tables into an RFC 4180 CSV string."""
        if not doc_ir.pages:
            raise SerializationError("Cannot emit CSV from empty DocumentIR")

        tables = self.extract_tables(doc_ir)
        if self.table_index is not None:
            if not tables:
                raise SerializationError(
                    f"No tables found in document (requested table_index={self.table_index})"
                )
            if self.table_index < 0 or self.table_index >= len(tables):
                raise SerializationError(
                    f"table_index {self.table_index} out of range (found {len(tables)} table(s): 0..{len(tables) - 1})"
                )
            selected = [tables[self.table_index]]
        else:
            selected = tables

        if not selected:
            if self.export_tables_only:
                raise SerializationError("No tables found in document (--export-tables-only)")
            return ""

        chunks = [
            serialize_table_to_csv(
                tbl,
                delimiter=self.delimiter,
                lineterminator=self.lineterminator,
            )
            for tbl in selected
        ]
        # Separate multiple tables with a single RFC 4180 blank line
        return self.lineterminator.join(chunks)

    def emit(
        self,
        doc_ir: DocumentIR,
        mode: ConversionMode = ConversionMode.FLOW,
    ) -> bytes:
        """Serialize detected tables from DocumentIR into UTF-8 RFC 4180 CSV bytes."""
        text = self.render(doc_ir)
        encoding = "utf-8-sig" if self.utf8_bom else "utf-8"
        return text.encode(encoding)


__all__ = [
    "ExtractedTable",
    "CsvEmitter",
    "table_to_grid",
    "extract_tables_from_ir",
    "serialize_table_to_csv",
]
