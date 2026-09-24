"""Spatial Canvas Mode Plaintext 2D character-grid matrix emitter."""

from __future__ import annotations

import math
from typing import List, Tuple

from anyconvert.emitters.base import BaseEmitter, ConversionMode
from anyconvert.exceptions import SerializationError
from anyconvert.ir.model import (
    BlockNode,
    DocumentIR,
    DocumentPage,
    ImageBlock,
    Paragraph,
    Table,
    TextRun,
    VectorBlock,
)


class TxtCanvasEmitter(BaseEmitter):
    """Spatial Canvas Plaintext emitter preserving coordinate layouts via 2D character grid."""

    __slots__ = ("char_width_pt", "line_height_pt")

    def __init__(
        self,
        char_width_pt: float = 6.0,
        line_height_pt: float = 12.0,
    ) -> None:
        """Initialize canvas emitter.

        Args:
            char_width_pt: Typographic points per character column (default 6.0 pt).
            line_height_pt: Typographic points per text row (default 12.0 pt).
        """
        self.char_width_pt: float = max(1.0, char_width_pt)
        self.line_height_pt: float = max(1.0, line_height_pt)

    def emit(
        self,
        doc_ir: DocumentIR,
        mode: ConversionMode = ConversionMode.CANVAS,
    ) -> bytes:
        """Serialize DocumentIR into a 2D spatial character grid matrix.

        Args:
            doc_ir: Validated DocumentIR structure.
            mode: Layout mode (defaults to CANVAS).

        Returns:
            UTF-8 encoded bytes of the 2D spatial text matrix.
        """
        if not doc_ir.pages:
            raise SerializationError("Cannot emit plaintext from empty DocumentIR")

        page_strings: List[str] = []

        for page in doc_ir.pages:
            page_text = self._render_page_grid(page)
            page_strings.append(page_text)

        # Separate pages with standard form feed page breaks
        full_text = "\n\x0c\n".join(page_strings)
        return full_text.encode("utf-8")

    def _render_page_grid(self, page: DocumentPage) -> str:
        """Allocate and populate 2D character grid for a single page."""
        num_cols = max(1, int(math.ceil(page.width / self.char_width_pt)))
        num_rows = max(1, int(math.ceil(page.height / self.line_height_pt)))

        # Allocate 2D grid matrix
        grid: List[List[str]] = [[" " for _ in range(num_cols)] for _ in range(num_rows)]

        # Header
        if page.header:
            for p in page.header.content:
                self._place_paragraph(grid, p, default_y=18.0)

        # Blocks
        for block in page.blocks:
            if isinstance(block, Paragraph):
                self._place_paragraph(grid, block, default_y=72.0)
            elif isinstance(block, Table):
                self._place_table(grid, block)
            elif isinstance(block, ImageBlock):
                self._place_image(grid, block)
            elif isinstance(block, VectorBlock):
                pass

        # Footer
        if page.footer:
            for p in page.footer.content:
                self._place_paragraph(grid, p, default_y=page.height - 36.0)

        # Convert rows to string, strip trailing spaces per row
        lines = ["".join(row).rstrip() for row in grid]

        # Strip trailing blank lines from bottom of page
        while lines and not lines[-1]:
            lines.pop()

        return "\n".join(lines)

    def _pt_to_col_row(self, x: float, y: float) -> Tuple[int, int]:
        """Convert document points (x, y) to matrix (col, row)."""
        col = max(0, int(round(x / self.char_width_pt)))
        row = max(0, int(round(y / self.line_height_pt)))
        return col, row

    def _write_text(
        self,
        grid: List[List[str]],
        text: str,
        start_col: int,
        start_row: int,
    ) -> None:
        """Write a string of characters horizontally into the grid."""
        num_rows = len(grid)
        if not (0 <= start_row < num_rows):
            return

        row_cells = grid[start_row]
        num_cols = len(row_cells)

        for i, ch in enumerate(text):
            col = start_col + i
            if 0 <= col < num_cols:
                row_cells[col] = ch

    def _place_paragraph(
        self,
        grid: List[List[str]],
        p: Paragraph,
        default_y: float = 72.0,
    ) -> None:
        """Place paragraph text into grid at its bounding coordinates."""
        if p.bbox is not None:
            col, row = self._pt_to_col_row(p.bbox.x0, p.bbox.y0)
        else:
            col, row = self._pt_to_col_row(72.0, default_y)

        # For runs with individual bounding boxes, place them accurately
        has_run_boxes = any(r.bbox is not None for r in p.runs)
        if has_run_boxes:
            for r in p.runs:
                if r.bbox is not None:
                    r_col, r_row = self._pt_to_col_row(r.bbox.x0, r.bbox.y0)
                    self._write_text(grid, r.text, r_col, r_row)
                else:
                    self._write_text(grid, r.text, col, row)
                    col += len(r.text)
        else:
            self._write_text(grid, p.text, col, row)

    def _place_table(self, grid: List[List[str]], table: Table) -> None:
        """Draw table outline and cell contents into the character grid."""
        if not table.rows:
            return

        if table.bbox is not None:
            c0, r0 = self._pt_to_col_row(table.bbox.x0, table.bbox.y0)
            c1, r1 = self._pt_to_col_row(table.bbox.x1, table.bbox.y1)
        else:
            c0, r0 = self._pt_to_col_row(72.0, 100.0)
            c1 = c0 + max(20, sum(int(round(w / self.char_width_pt)) for w in table.col_widths))
            r1 = r0 + len(table.rows) * 2

        num_cols = len(grid[0]) if grid else 0
        num_rows = len(grid)

        c0 = max(0, min(c0, num_cols - 1))
        c1 = max(c0 + 1, min(c1, num_cols))
        r0 = max(0, min(r0, num_rows - 1))
        r1 = max(r0 + 1, min(r1, num_rows))

        # Draw top and bottom borders
        for c in range(c0, c1):
            if r0 < num_rows:
                grid[r0][c] = "-"
            if r1 - 1 < num_rows:
                grid[r1 - 1][c] = "-"

        # Draw side borders
        for r in range(r0, r1):
            grid[r][c0] = "|"
            if c1 - 1 < num_cols:
                grid[r][c1 - 1] = "|"

        # Corners
        if r0 < num_rows and c0 < num_cols:
            grid[r0][c0] = "+"
        if r0 < num_rows and c1 - 1 < num_cols:
            grid[r0][c1 - 1] = "+"
        if r1 - 1 < num_rows and c0 < num_cols:
            grid[r1 - 1][c0] = "+"
        if r1 - 1 < num_rows and c1 - 1 < num_cols:
            grid[r1 - 1][c1 - 1] = "+"

        # Place cell text inside table rows
        curr_r = r0 + 1
        for row in table.rows:
            if curr_r >= r1 - 1:
                break
            curr_c = c0 + 2
            for cell in row.cells:
                cell_txt = " ".join(b.text for b in cell.content if isinstance(b, Paragraph))
                cell_w_chars = int(round(cell.width / self.char_width_pt)) if cell.width > 0 else len(cell_txt)
                self._write_text(grid, cell_txt[:cell_w_chars], curr_c, curr_r)
                curr_c += max(cell_w_chars + 2, len(cell_txt) + 2)
            curr_r += 1

    def _place_image(self, grid: List[List[str]], img: ImageBlock) -> None:
        """Draw image placeholder frame in the character grid."""
        c0, r0 = self._pt_to_col_row(img.bbox.x0, img.bbox.y0)
        c1, r1 = self._pt_to_col_row(img.bbox.x1, img.bbox.y1)

        num_cols = len(grid[0]) if grid else 0
        num_rows = len(grid)

        c0 = max(0, min(c0, num_cols - 1))
        c1 = max(c0 + 1, min(c1, num_cols))
        r0 = max(0, min(r0, num_rows - 1))
        r1 = max(r0 + 1, min(r1, num_rows))

        # Draw box outline
        for c in range(c0, c1):
            if r0 < num_rows:
                grid[r0][c] = "."
            if r1 - 1 < num_rows:
                grid[r1 - 1][c] = "."
        for r in range(r0, r1):
            grid[r][c0] = ":"
            if c1 - 1 < num_cols:
                grid[r][c1 - 1] = ":"

        # Write image label inside
        alt = img.alt_text or "Image"
        label = f"[ {alt} ]"
        mid_r = (r0 + r1) // 2
        mid_c = max(c0 + 1, (c0 + c1 - len(label)) // 2)
        self._write_text(grid, label, mid_c, mid_r)


__all__ = ["TxtCanvasEmitter"]
