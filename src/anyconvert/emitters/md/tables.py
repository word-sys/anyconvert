"""GFM and CommonMark tabular matrix formatting and alignment engine.

Handles 2D grid matrix normalization, multi-line cell text escaping,
col_span / row_span cell layout, column alignment auto-detection,
and Markdown pipe delimiter generation.
"""

from __future__ import annotations

import re
from typing import Callable, List, Optional, Sequence, Tuple

from anyconvert.ir.model import (
    Alignment,
    BlockNode,
    Paragraph,
    Table,
    TableCell,
    TableRow,
    TextRun,
)

# Numeric, currency, and percentage pattern for column alignment heuristics
_NUMERIC_RE = re.compile(
    r"^[\$€£¥₽₹]?\s*-?\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*%?$"
)

# Pipe characters that are not already escaped
_UNESCAPED_PIPE_RE = re.compile(r"(?<!\\)\|")


def escape_cell_text(text: str) -> str:
    """Escape cell text for GFM pipe table formatting.

    Replaces newlines with <br>, removes carriage returns,
    and escapes raw pipe characters.
    """
    if not text:
        return ""
    # Normalize carriage returns
    clean = text.replace("\r\n", "\n").replace("\r", "\n")
    # Replace internal newlines with <br>
    clean = clean.replace("\n", "<br>")
    # Escape unescaped pipe characters
    clean = _UNESCAPED_PIPE_RE.sub(r"\|", clean)
    return clean.strip()


def render_cell_content(
    cell: TableCell,
    run_renderer: Optional[Callable[[TextRun], str]] = None,
) -> str:
    """Render the inner BlockNode contents of a TableCell into a single cell string."""
    parts: List[str] = []
    for block in cell.content:
        if isinstance(block, Paragraph):
            if run_renderer is not None:
                p_text = "".join(run_renderer(r) for r in block.runs).strip()
            else:
                p_text = block.text.strip()
            if p_text:
                parts.append(p_text)
    joined = "<br>".join(parts) if len(parts) > 1 else ("".join(parts) if parts else "")
    return escape_cell_text(joined)


def build_table_matrix(
    table: Table,
    run_renderer: Optional[Callable[[TextRun], str]] = None,
) -> Tuple[List[List[str]], List[Alignment]]:
    """Build a normalized 2D matrix of cell strings and determine column alignments.

    Properly handles col_span and row_span, ensuring consistent column counts
    and alignment across ragged rows.
    """
    if not table.rows:
        return [], []

    # First pass: determine max dimensions considering spans
    num_rows = len(table.rows)
    # Track occupied grid positions: (row_idx, col_idx) -> cell_text
    grid: List[List[str]] = []
    occupancy: List[List[bool]] = []

    # Pre-allocate rows with dynamic column expansion
    for _ in range(num_rows):
        grid.append([])
        occupancy.append([])

    # Also track cell alignments per column to infer column alignment
    col_alignments_votes: List[List[Alignment]] = []

    for r_idx, row in enumerate(table.rows):
        c_idx = 0
        for cell in row.cells:
            # Advance past cells already occupied by row_span from previous rows
            while c_idx < len(occupancy[r_idx]) and occupancy[r_idx][c_idx]:
                c_idx += 1

            cell_str = render_cell_content(cell, run_renderer)
            col_span = max(1, cell.col_span)
            row_span = max(1, cell.row_span)

            # Determine cell alignment from paragraph content
            cell_align: Optional[Alignment] = None
            for b in cell.content:
                if isinstance(b, Paragraph) and b.alignment != Alignment.LEFT:
                    cell_align = b.alignment
                    break

            # Mark occupancy across row_span and col_span
            for dr in range(row_span):
                target_r = r_idx + dr
                # Expand rows if row_span exceeds initial row count
                while target_r >= len(grid):
                    grid.append([])
                    occupancy.append([])

                for dc in range(col_span):
                    target_c = c_idx + dc
                    # Expand columns for this row
                    while target_c >= len(grid[target_r]):
                        grid[target_r].append("")
                        occupancy[target_r].append(False)

                    occupancy[target_r][target_c] = True
                    # Place content only in top-left cell of the span
                    if dr == 0 and dc == 0:
                        grid[target_r][target_c] = cell_str
                    else:
                        grid[target_r][target_c] = ""

            # Record alignment votes for the starting column
            while len(col_alignments_votes) <= c_idx:
                col_alignments_votes.append([])
            if cell_align is not None:
                col_alignments_votes[c_idx].append(cell_align)
            elif _NUMERIC_RE.match(cell_str.replace("<br>", "").strip()):
                col_alignments_votes[c_idx].append(Alignment.RIGHT)
            elif cell_str.strip():
                col_alignments_votes[c_idx].append(Alignment.LEFT)

            c_idx += col_span

    # Normalize grid so every row has the maximum number of columns
    max_cols = max((len(r) for r in grid), default=0)
    if table.col_widths and len(table.col_widths) > max_cols:
        max_cols = len(table.col_widths)

    for r in grid:
        while len(r) < max_cols:
            r.append("")

    # Check if table has any heterogeneous column alignments
    has_column_signals = any(
        any(v in (Alignment.RIGHT, Alignment.CENTER) for v in votes)
        for votes in col_alignments_votes
    )

    resolved_alignments: List[Alignment] = []
    for c in range(max_cols):
        votes = col_alignments_votes[c] if c < len(col_alignments_votes) else []
        if has_column_signals:
            right_count = sum(1 for v in votes if v == Alignment.RIGHT)
            center_count = sum(1 for v in votes if v == Alignment.CENTER)
            total = len(votes)
            if total > 0 and right_count >= total / 2:
                resolved_alignments.append(Alignment.RIGHT)
            elif total > 0 and center_count >= total / 2:
                resolved_alignments.append(Alignment.CENTER)
            else:
                resolved_alignments.append(Alignment.LEFT)
        else:
            resolved_alignments.append(table.alignment)

    return grid, resolved_alignments


def build_delimiter_cells(
    col_widths: Sequence[int],
    alignments: Sequence[Alignment],
) -> List[str]:
    """Construct Markdown alignment delimiter tokens (e.g. :---, :---:, ---:)."""
    delims: List[str] = []
    for i, w in enumerate(col_widths):
        align = alignments[i] if i < len(alignments) else Alignment.LEFT
        width = max(3, w)
        if align == Alignment.CENTER:
            delims.append(f":{'-' * (width - 2)}:")
        elif align == Alignment.RIGHT:
            delims.append(f"{'-' * (width - 1)}:")
        else:
            delims.append(f":{'-' * (width - 1)}")
    return delims


def pad_cell(text: str, width: int, alignment: Alignment) -> str:
    """Pad cell text to specified width according to column alignment."""
    if alignment == Alignment.RIGHT:
        return text.rjust(width)
    return text.ljust(width)


def format_table_matrix(
    table: Table,
    run_renderer: Optional[Callable[[TextRun], str]] = None,
    default_alignment: Optional[Alignment] = None,
) -> str:
    """Render a Table IR object into a clean GFM pipe-delimited Markdown table.

    Produces aligned columns, escapes special characters, and handles
    spanned cells gracefully.
    """
    grid, alignments = build_table_matrix(table, run_renderer)
    if not grid or not grid[0]:
        return ""

    num_cols = len(grid[0])
    if default_alignment is not None:
        alignments = [default_alignment] * num_cols

    # Calculate required column widths (minimum width 3)
    col_widths = [3] * num_cols
    for row in grid:
        for c_idx, cell_str in enumerate(row):
            col_widths[c_idx] = max(col_widths[c_idx], len(cell_str))

    lines: List[str] = []

    # Header row (row 0)
    header_row = grid[0]
    hdr_cells = [
        pad_cell(cell, col_widths[i], alignments[i])
        for i, cell in enumerate(header_row)
    ]
    lines.append(f"| {' | '.join(hdr_cells)} |")

    # Delimiter row
    delims = build_delimiter_cells(col_widths, alignments)
    lines.append(f"| {' | '.join(delims)} |")

    # Body rows
    for row in grid[1:]:
        body_cells = [
            pad_cell(cell, col_widths[i], alignments[i])
            for i, cell in enumerate(row)
        ]
        lines.append(f"| {' | '.join(body_cells)} |")

    return "\n".join(lines)


__all__ = [
    "build_delimiter_cells",
    "build_table_matrix",
    "escape_cell_text",
    "format_table_matrix",
    "pad_cell",
    "render_cell_content",
]
