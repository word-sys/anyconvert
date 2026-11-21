r"""RTF 1.9.1 table matrix generator (\trowd, \clbrdr*, \cellxN, \intbl, \cell, \row).

Translates DocumentIR Table structures into Word and LibreOffice compliant RTF
tables supporting:
- 2D occupancy grid resolution for horizontal (col_span) and vertical (row_span, \clvmgf/\clvmrg) merges.
- Twip column width normalization scaled to page printable width.
- Explicit or default grid cell borders (\clbrdrt, \clbrdrl, \clbrdrb, \clbrdrr).
- Cell background shading (\clcbpatN), header row repetition (\trhdr), and table alignment.
- Multi-paragraph cell content without trailing blank lines before \cell.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from anyconvert.common.color import Color
from anyconvert.emitters.base import pt_to_dxa
from anyconvert.ir.model import (
    Alignment,
    Border,
    Paragraph,
    Table,
    TableCell,
)

DEFAULT_TABLE_WIDTH_TWIPS = 9360  # 6.5 in (Letter width minus 2x 1 in margins)
MIN_COL_WIDTH_TWIPS = 360  # 0.25 in

_BORDER_STYLE_MAP: Dict[str, str] = {
    "solid": r"\brdrs",
    "dashed": r"\brdrdash",
    "dotted": r"\brdrdot",
    "double": r"\brdrdb",
}

_TABLE_ALIGN_MAP: Dict[Alignment, str] = {
    Alignment.LEFT: r"\trql",
    Alignment.CENTER: r"\trqc",
    Alignment.RIGHT: r"\trqr",
    Alignment.JUSTIFIED: r"\trql",
}

_BORDER_SIDES: Tuple[Tuple[str, str], ...] = (
    ("top", r"\clbrdrt"),
    ("left", r"\clbrdrl"),
    ("bottom", r"\clbrdrb"),
    ("right", r"\clbrdrr"),
)


@dataclass(slots=True)
class _GridSlot:
    """Resolved cell slot inside a normalized 2D RTF table matrix."""

    cell: Optional[TableCell]
    col_span: int
    is_vmerge_start: bool = False
    is_vmerge_cont: bool = False
    is_hmerge_cont: bool = False


def format_rtf_border(
    side_ctrl: str,
    border: Border,
    register_color_fn: Callable[[Optional[Color]], int],
) -> str:
    """Serialize a single cell border side (e.g. \\clbrdrl\\brdrs\\brdrw15\\brdrcf1)."""
    style = border.style.lower().strip()
    if style == "none":
        return ""
    style_ctrl = _BORDER_STYLE_MAP.get(style, r"\brdrs")
    width_twips = max(10, min(75, pt_to_dxa(border.width if border.width > 0 else 0.75)))
    cf_idx = register_color_fn(border.color)
    return f"{side_ctrl}{style_ctrl}\\brdrw{width_twips}\\brdrcf{cf_idx}"


def format_cell_borders(
    cell: Optional[TableCell],
    register_color_fn: Callable[[Optional[Color]], int],
    default_borders: bool = True,
) -> str:
    """Build all 4 border control word sequences for an RTF table cell."""
    if cell is not None and cell.borders:
        parts: List[str] = []
        for side_key, side_ctrl in _BORDER_SIDES:
            b = cell.borders.get(side_key)
            if b is not None:
                parts.append(format_rtf_border(side_ctrl, b, register_color_fn))
        return "".join(parts)

    if not default_borders:
        return ""

    default_cf = register_color_fn(Color(0, 0, 0))
    return "".join(
        f"{side_ctrl}\\brdrs\\brdrw10\\brdrcf{default_cf}"
        for _, side_ctrl in _BORDER_SIDES
    )


def _build_occupancy_matrix(table: Table) -> Tuple[List[List[_GridSlot]], int]:
    """Expand Table rows into a normalized 2D matrix resolving col_span and row_span."""
    if not table.rows:
        return [], 0

    num_rows = len(table.rows)
    grid: List[List[Optional[_GridSlot]]] = [[] for _ in range(num_rows)]

    for r_idx, row in enumerate(table.rows):
        c_idx = 0
        for cell in row.cells:
            while c_idx < len(grid[r_idx]) and grid[r_idx][c_idx] is not None:
                c_idx += 1

            c_span = max(1, int(cell.col_span))
            r_span = max(1, int(cell.row_span))

            for dr in range(r_span):
                tr = r_idx + dr
                while tr >= len(grid):
                    grid.append([])
                while len(grid[tr]) < c_idx + c_span:
                    grid[tr].append(None)

                for dc in range(c_span):
                    tc = c_idx + dc
                    if dc == 0:
                        grid[tr][tc] = _GridSlot(
                            cell=cell if dr == 0 else cell,
                            col_span=c_span,
                            is_vmerge_start=(r_span > 1 and dr == 0),
                            is_vmerge_cont=(r_span > 1 and dr > 0),
                            is_hmerge_cont=False,
                        )
                    else:
                        grid[tr][tc] = _GridSlot(
                            cell=None,
                            col_span=1,
                            is_hmerge_cont=True,
                        )

            c_idx += c_span

    max_cols = max((len(r) for r in grid), default=0)
    if table.col_widths and len(table.col_widths) > max_cols:
        max_cols = len(table.col_widths)

    normalized: List[List[_GridSlot]] = []
    for row_slots in grid:
        filled: List[_GridSlot] = []
        for c in range(max_cols):
            slot = row_slots[c] if c < len(row_slots) else None
            if slot is None:
                filled.append(_GridSlot(cell=None, col_span=1))
            else:
                filled.append(slot)
        normalized.append(filled)

    return normalized, max_cols


def compute_rtf_col_widths(
    table: Table,
    num_cols: int,
    max_width_twips: int = DEFAULT_TABLE_WIDTH_TWIPS,
) -> List[int]:
    """Compute twip widths for each table column, scaled cleanly within printable page width."""
    if num_cols <= 0:
        return []

    raw_twips: List[int] = []
    for c in range(num_cols):
        if c < len(table.col_widths) and table.col_widths[c] > 0:
            raw_twips.append(max(MIN_COL_WIDTH_TWIPS, pt_to_dxa(table.col_widths[c])))
        else:
            raw_twips.append(0)

    # Infer missing widths from first row cells if available
    if any(w == 0 for w in raw_twips) and table.rows:
        c_cursor = 0
        for cell in table.rows[0].cells:
            span = max(1, cell.col_span)
            if cell.width > 0:
                per_col = max(MIN_COL_WIDTH_TWIPS, pt_to_dxa(cell.width / span))
                for offset in range(span):
                    if c_cursor + offset < num_cols and raw_twips[c_cursor + offset] == 0:
                        raw_twips[c_cursor + offset] = per_col
            c_cursor += span

    # Fill any remaining unspecified columns evenly
    missing = [i for i, w in enumerate(raw_twips) if w == 0]
    if missing:
        used = sum(raw_twips)
        remaining = max(MIN_COL_WIDTH_TWIPS * len(missing), max_width_twips - used)
        per_missing = max(MIN_COL_WIDTH_TWIPS, remaining // len(missing))
        for idx in missing:
            raw_twips[idx] = per_missing

    total = sum(raw_twips)
    if total > max_width_twips and total > 0:
        scale = max_width_twips / float(total)
        raw_twips = [max(MIN_COL_WIDTH_TWIPS, int(round(w * scale))) for w in raw_twips]

    return raw_twips


def render_rtf_table(
    table: Table,
    render_paragraph_fn: Callable[[Paragraph], str],
    register_color_fn: Callable[[Optional[Color]], int],
    max_width_twips: int = DEFAULT_TABLE_WIDTH_TWIPS,
    default_borders: bool = True,
) -> str:
    """Render a Table IR node into RTF 1.9.1 table rows (\\trowd ... \\row)."""
    matrix, num_cols = _build_occupancy_matrix(table)
    if not matrix or num_cols == 0:
        return ""

    col_widths = compute_rtf_col_widths(table, num_cols, max_width_twips=max_width_twips)
    align_ctrl = _TABLE_ALIGN_MAP.get(table.alignment, r"\trql")

    row_strings: List[str] = []
    for r_idx, row_slots in enumerate(matrix):
        src_row = table.rows[r_idx] if r_idx < len(table.rows) else None
        row_header_parts: List[str] = [
            "\\trowd",
            "\\trgaph108",
            "\\trpaddl108\\trpaddr108\\trpaddt60\\trpaddb60",
            "\\trpaddfl3\\trpaddfr3\\trpaddft3\\trpaddfb3",
            align_ctrl,
            "\\trkeep",
        ]
        if src_row is not None:
            if src_row.is_header:
                row_header_parts.append("\\trhdr")
            if src_row.height > 0:
                row_header_parts.append(f"\\trrh{pt_to_dxa(src_row.height)}")

        cell_defs: List[str] = []
        cell_bodies: List[str] = []
        right_x = 0

        c_idx = 0
        while c_idx < num_cols:
            slot = row_slots[c_idx]
            if slot.is_hmerge_cont:
                c_idx += 1
                continue

            span = max(1, min(slot.col_span, num_cols - c_idx))
            span_width = sum(col_widths[c_idx : c_idx + span])
            right_x += span_width

            c_def: List[str] = ["\\clvertalt"]
            if slot.is_vmerge_start:
                c_def.append("\\clvmgf")
            elif slot.is_vmerge_cont:
                c_def.append("\\clvmrg")

            if slot.cell is not None and slot.cell.background_color is not None:
                bg_idx = register_color_fn(slot.cell.background_color)
                if bg_idx > 0:
                    c_def.append(f"\\clcbpat{bg_idx}")

            borders_rtf = format_cell_borders(
                slot.cell,
                register_color_fn=register_color_fn,
                default_borders=default_borders,
            )
            if borders_rtf:
                c_def.append(borders_rtf)

            c_def.append(f"\\cellx{right_x}")
            cell_defs.append("".join(c_def))

            # Build cell body (empty for vertical-merge continuations)
            if slot.is_vmerge_cont or slot.cell is None:
                cell_bodies.append("\\pard\\intbl\\ql \\cell")
            else:
                para_chunks: List[str] = []
                for sub in slot.cell.content:
                    if isinstance(sub, Paragraph):
                        rendered_p = render_paragraph_fn(sub)
                        if rendered_p:
                            para_chunks.append(rendered_p)
                if para_chunks:
                    cell_bodies.append("\\par ".join(para_chunks) + "\\cell")
                else:
                    cell_bodies.append("\\pard\\intbl\\ql \\cell")

            c_idx += span

        row_strings.append("".join(row_header_parts) + "".join(cell_defs) + "".join(cell_bodies) + "\\row")

    return "\n".join(row_strings)


__all__ = [
    "DEFAULT_TABLE_WIDTH_TWIPS",
    "MIN_COL_WIDTH_TWIPS",
    "format_rtf_border",
    "format_cell_borders",
    "compute_rtf_col_widths",
    "render_rtf_table",
]
