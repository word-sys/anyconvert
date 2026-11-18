"""Spatial Canvas Mode Plaintext 2D character-grid matrix emitter."""

from __future__ import annotations

import math
import re
from typing import Dict, List, Optional, Tuple

from anyconvert.emitters.base import BaseEmitter, ConversionMode
from anyconvert.exceptions import SerializationError
from anyconvert.ir.model import (
    DocumentIR,
    DocumentPage,
    ImageBlock,
    Paragraph,
    Table,
    VectorBlock,
)

# Directional bitmask flags for Unicode box-drawing junction merging
_BOX_N = 1
_BOX_E = 2
_BOX_S = 4
_BOX_W = 8

_MASK_TO_UNICODE: Dict[int, str] = {
    _BOX_N: "│",
    _BOX_S: "│",
    _BOX_N | _BOX_S: "│",
    _BOX_E: "─",
    _BOX_W: "─",
    _BOX_E | _BOX_W: "─",
    _BOX_S | _BOX_E: "┌",
    _BOX_S | _BOX_W: "┐",
    _BOX_N | _BOX_E: "└",
    _BOX_N | _BOX_W: "┘",
    _BOX_N | _BOX_S | _BOX_E: "├",
    _BOX_N | _BOX_S | _BOX_W: "┤",
    _BOX_S | _BOX_E | _BOX_W: "┬",
    _BOX_N | _BOX_E | _BOX_W: "┴",
    _BOX_N | _BOX_S | _BOX_E | _BOX_W: "┼",
}

_SVG_TOKEN_RE = re.compile(r"[A-Za-z]|[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?")


def _mask_to_ascii(mask: int) -> str:
    """Convert directional connectivity mask into classic ASCII box glyph."""
    has_horiz = bool(mask & (_BOX_E | _BOX_W))
    has_vert = bool(mask & (_BOX_N | _BOX_S))
    if has_horiz and has_vert:
        return "+"
    if has_horiz:
        return "-"
    if has_vert:
        return "|"
    return " "


def _parse_svg_segments(svg_path: str) -> List[Tuple[float, float, float, float]]:
    """Parse an SVG path string into drawable line segments (x0, y0, x1, y1)."""
    tokens = _SVG_TOKEN_RE.findall(svg_path)
    segments: List[Tuple[float, float, float, float]] = []
    if not tokens:
        return segments

    idx = 0
    n = len(tokens)
    cmd = ""
    curr_x = 0.0
    curr_y = 0.0
    start_x = 0.0
    start_y = 0.0

    def _next_float() -> Optional[float]:
        nonlocal idx
        if idx >= n or tokens[idx].isalpha():
            return None
        val = float(tokens[idx])
        idx += 1
        return val

    while idx < n:
        tok = tokens[idx]
        if tok.isalpha():
            cmd = tok
            idx += 1
            if cmd in ("Z", "z"):
                if abs(curr_x - start_x) > 1e-4 or abs(curr_y - start_y) > 1e-4:
                    segments.append((curr_x, curr_y, start_x, start_y))
                curr_x, curr_y = start_x, start_y
            continue

        if not cmd:
            idx += 1
            continue

        if cmd == "M":
            x = _next_float()
            y = _next_float()
            if x is None or y is None:
                break
            curr_x, curr_y = x, y
            start_x, start_y = x, y
            cmd = "L"
        elif cmd == "m":
            dx = _next_float()
            dy = _next_float()
            if dx is None or dy is None:
                break
            curr_x += dx
            curr_y += dy
            start_x, start_y = curr_x, curr_y
            cmd = "l"
        elif cmd == "L":
            x = _next_float()
            y = _next_float()
            if x is None or y is None:
                break
            segments.append((curr_x, curr_y, x, y))
            curr_x, curr_y = x, y
        elif cmd == "l":
            dx = _next_float()
            dy = _next_float()
            if dx is None or dy is None:
                break
            nx, ny = curr_x + dx, curr_y + dy
            segments.append((curr_x, curr_y, nx, ny))
            curr_x, curr_y = nx, ny
        elif cmd == "H":
            x = _next_float()
            if x is None:
                break
            segments.append((curr_x, curr_y, x, curr_y))
            curr_x = x
        elif cmd == "h":
            dx = _next_float()
            if dx is None:
                break
            nx = curr_x + dx
            segments.append((curr_x, curr_y, nx, curr_y))
            curr_x = nx
        elif cmd == "V":
            y = _next_float()
            if y is None:
                break
            segments.append((curr_x, curr_y, curr_x, y))
            curr_y = y
        elif cmd == "v":
            dy = _next_float()
            if dy is None:
                break
            ny = curr_y + dy
            segments.append((curr_x, curr_y, curr_x, ny))
            curr_y = ny
        elif cmd in ("C", "c"):
            vals = [_next_float() for _ in range(6)]
            if any(v is None for v in vals):
                break
            assert vals[4] is not None and vals[5] is not None
            ex = vals[4] if cmd == "C" else curr_x + vals[4]
            ey = vals[5] if cmd == "C" else curr_y + vals[5]
            segments.append((curr_x, curr_y, ex, ey))
            curr_x, curr_y = ex, ey
        else:
            idx += 1

    return segments


class TxtCanvasEmitter(BaseEmitter):
    """Spatial Canvas Plaintext emitter preserving coordinate layouts via 2D character grid."""

    __slots__ = ("char_width_pt", "line_height_pt", "unicode_boxes")

    def __init__(
        self,
        char_width_pt: float = 6.0,
        line_height_pt: float = 12.0,
        unicode_boxes: bool = True,
    ) -> None:
        """Initialize canvas emitter.

        Args:
            char_width_pt: Typographic points per character column (default 6.0 pt).
            line_height_pt: Typographic points per text row (default 12.0 pt).
            unicode_boxes: Render table borders and vector graphics using Unicode box-drawing characters.
        """
        self.char_width_pt: float = max(1.0, char_width_pt)
        self.line_height_pt: float = max(1.0, line_height_pt)
        self.unicode_boxes: bool = unicode_boxes

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

        # Allocate 2D character grid and parallel box-drawing junction bitmask grid
        grid: List[List[str]] = [[" " for _ in range(num_cols)] for _ in range(num_rows)]
        masks: List[List[int]] = [[0 for _ in range(num_cols)] for _ in range(num_rows)]

        # Pass 1: Draw vector lines, rules, and frames underneath text
        for block in page.blocks:
            if isinstance(block, VectorBlock):
                self._place_vector(grid, block, masks=masks)

        # Pass 2: Draw tables and images
        for block in page.blocks:
            if isinstance(block, Table):
                self._place_table(grid, block, masks=masks)
            elif isinstance(block, ImageBlock):
                self._place_image(grid, block, masks=masks)

        # Pass 3: Header, body paragraphs, and footer on top of borders
        if page.header:
            for p in page.header.content:
                self._place_paragraph(grid, p, default_y=18.0)

        for block in page.blocks:
            if isinstance(block, Paragraph):
                self._place_paragraph(grid, block, default_y=72.0)

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

    def _apply_mask_glyph(
        self,
        grid: List[List[str]],
        masks: List[List[int]],
        row: int,
        col: int,
        add_mask: int,
    ) -> None:
        """Merge directional box bits at (row, col) and update rendered glyph."""
        if not (0 <= row < len(grid)) or not (0 <= col < len(grid[0])):
            return
        new_mask = masks[row][col] | add_mask
        masks[row][col] = new_mask
        if self.unicode_boxes:
            grid[row][col] = _MASK_TO_UNICODE.get(new_mask, "+")
        else:
            grid[row][col] = _mask_to_ascii(new_mask)

    def _draw_hline(
        self,
        grid: List[List[str]],
        masks: List[List[int]],
        row: int,
        c_start: int,
        c_end: int,
    ) -> None:
        """Draw a horizontal line segment from c_start to c_end (inclusive)."""
        if not grid or not (0 <= row < len(grid)):
            return
        num_cols = len(grid[0])
        if c_start > c_end:
            c_start, c_end = c_end, c_start
        if c_end < 0 or c_start >= num_cols:
            return

        for c in range(max(0, c_start), min(num_cols, c_end + 1)):
            bit = 0
            if c > c_start:
                bit |= _BOX_W
            if c < c_end:
                bit |= _BOX_E
            if c_start == c_end:
                bit = _BOX_E | _BOX_W
            self._apply_mask_glyph(grid, masks, row, c, bit)

    def _draw_vline(
        self,
        grid: List[List[str]],
        masks: List[List[int]],
        col: int,
        r_start: int,
        r_end: int,
    ) -> None:
        """Draw a vertical line segment from r_start to r_end (inclusive)."""
        if not grid or not (0 <= col < len(grid[0])):
            return
        num_rows = len(grid)
        if r_start > r_end:
            r_start, r_end = r_end, r_start
        if r_end < 0 or r_start >= num_rows:
            return

        for r in range(max(0, r_start), min(num_rows, r_end + 1)):
            bit = 0
            if r > r_start:
                bit |= _BOX_N
            if r < r_end:
                bit |= _BOX_S
            if r_start == r_end:
                bit = _BOX_N | _BOX_S
            self._apply_mask_glyph(grid, masks, r, col, bit)

    def _draw_diagonal(
        self,
        grid: List[List[str]],
        c0: int,
        r0: int,
        c1: int,
        r1: int,
    ) -> None:
        """Draw a diagonal vector line via Bresenham stepping."""
        if not grid:
            return
        num_rows = len(grid)
        num_cols = len(grid[0])
        dc = abs(c1 - c0)
        dr = abs(r1 - r0)
        sc = 1 if c0 < c1 else -1
        sr = 1 if r0 < r1 else -1
        err = dc - dr

        # Choose slash orientation in top-down screen coordinates
        glyph = "/" if (sc * sr) < 0 else "\\"
        c, r = c0, r0
        while True:
            if 0 <= r < num_rows and 0 <= c < num_cols and grid[r][c] == " ":
                grid[r][c] = glyph
            if c == c1 and r == r1:
                break
            e2 = 2 * err
            if e2 > -dr:
                err -= dr
                c += sc
            if e2 < dc:
                err += dc
                r += sr

    def _draw_box(
        self,
        grid: List[List[str]],
        masks: List[List[int]],
        c0: int,
        r0: int,
        c_right: int,
        r_bottom: int,
    ) -> None:
        """Draw a closed rectangle with corners at (c0, r0) and (c_right, r_bottom)."""
        self._draw_hline(grid, masks, r0, c0, c_right)
        if r_bottom > r0:
            self._draw_hline(grid, masks, r_bottom, c0, c_right)
            self._draw_vline(grid, masks, c0, r0, r_bottom)
            if c_right > c0:
                self._draw_vline(grid, masks, c_right, r0, r_bottom)

    def _ensure_masks(
        self,
        grid: List[List[str]],
        masks: Optional[List[List[int]]],
    ) -> List[List[int]]:
        """Return existing mask grid or allocate an empty mask grid matching grid shape."""
        if masks is not None:
            return masks
        num_rows = len(grid)
        num_cols = len(grid[0]) if grid else 0
        return [[0 for _ in range(num_cols)] for _ in range(num_rows)]

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

    def _compute_col_edges(
        self,
        table: Table,
        c0: int,
        c_right: int,
        num_cols_tbl: int,
    ) -> List[int]:
        """Compute character column x-boundaries for each column in a table."""
        total_span = max(num_cols_tbl * 2, c_right - c0)
        weights: List[float] = []
        if table.col_widths and len(table.col_widths) >= num_cols_tbl:
            weights = [max(1.0, float(w)) for w in table.col_widths[:num_cols_tbl]]
        else:
            first_row = table.rows[0]
            for cell in first_row.cells:
                span = max(1, cell.col_span)
                per_col = max(1.0, float(cell.width) / span) if cell.width > 0 else 10.0
                weights.extend([per_col] * span)
            while len(weights) < num_cols_tbl:
                weights.append(10.0)
            weights = weights[:num_cols_tbl]

        total_w = max(1.0, sum(weights))
        edges: List[int] = [c0]
        accum = 0.0
        for idx, w in enumerate(weights):
            accum += w
            if idx == len(weights) - 1:
                edges.append(c_right)
            else:
                edge = c0 + int(round((accum / total_w) * total_span))
                min_edge = edges[-1] + 2
                max_edge = c_right - 2 * (len(weights) - 1 - idx)
                edge = max(min_edge, min(edge, max(min_edge, max_edge)))
                edges.append(edge)
        return edges

    def _place_table(
        self,
        grid: List[List[str]],
        table: Table,
        masks: Optional[List[List[int]]] = None,
    ) -> None:
        """Draw Unicode/ASCII table grid borders and cell contents into the canvas."""
        if not table.rows or not grid:
            return

        active_masks = self._ensure_masks(grid, masks)
        num_cols = len(grid[0])
        num_rows = len(grid)
        num_tbl_rows = len(table.rows)
        num_tbl_cols = max(
            (sum(max(1, c.col_span) for c in row.cells) for row in table.rows),
            default=1,
        )

        if table.bbox is not None:
            c0, r0 = self._pt_to_col_row(table.bbox.x0, table.bbox.y0)
            c1, r1 = self._pt_to_col_row(table.bbox.x1, table.bbox.y1)
        else:
            c0, r0 = self._pt_to_col_row(72.0, 100.0)
            est_w = sum(int(round(w / self.char_width_pt)) for w in table.col_widths)
            c1 = c0 + max(num_tbl_cols * 8, est_w + 1)
            r1 = r0 + num_tbl_rows * 2 + 1

        c0 = max(0, min(c0, num_cols - 1))
        c_right = max(c0 + 1, min(c1 - 1, num_cols - 1))
        r0 = max(0, min(r0, num_rows - 1))
        r_bottom = max(r0 + 2, min(r1 - 1, num_rows - 1))

        col_edges = self._compute_col_edges(table, c0, c_right, num_tbl_cols)
        c_right = col_edges[-1]

        # Draw outer frame
        self._draw_box(grid, active_masks, c0, r0, c_right, r_bottom)

        # Plan row text y-coordinates and horizontal row dividers
        inner_h = max(0, r_bottom - r0 - 1)
        draw_all_dividers = inner_h >= (2 * num_tbl_rows - 1) and num_tbl_rows > 1
        draw_header_divider = (
            not draw_all_dividers
            and num_tbl_rows > 1
            and inner_h >= num_tbl_rows + 1
            and table.rows[0].is_header
        )

        row_entries: List[Tuple[int, int, int, int]] = []  # (r_idx, row_y, band_top, band_bot)
        curr_r = r0 + 1
        prev_divider = r0

        for r_idx in range(num_tbl_rows):
            if curr_r >= r_bottom:
                break
            row_y = curr_r
            band_top = prev_divider
            curr_r += 1

            has_divider_below = (
                r_idx < num_tbl_rows - 1
                and curr_r < r_bottom
                and (draw_all_dividers or (draw_header_divider and r_idx == 0))
            )
            if has_divider_below:
                div_y = curr_r
                self._draw_hline(grid, active_masks, div_y, c0, c_right)
                band_bot = div_y
                prev_divider = div_y
                curr_r += 1
            elif r_idx == num_tbl_rows - 1 or curr_r >= r_bottom:
                band_bot = r_bottom
            else:
                band_bot = min(r_bottom, curr_r)
                prev_divider = row_y

            row_entries.append((r_idx, row_y, band_top, band_bot))

        # Extend last visible row band to r_bottom if table height exceeded row entries
        if row_entries:
            last_idx, last_ry, last_top, _ = row_entries[-1]
            row_entries[-1] = (last_idx, last_ry, last_top, r_bottom)

        # Draw per-row vertical column dividers (respecting col_span) and place cell text
        for r_idx, row_y, band_top, band_bot in row_entries:
            row = table.rows[r_idx]
            c_pos = 0
            for cell in row.cells:
                span = max(1, cell.col_span)
                end_col_idx = min(c_pos + span, len(col_edges) - 1)
                if c_pos >= len(col_edges) - 1:
                    break

                left_x = col_edges[c_pos]
                right_x = col_edges[end_col_idx]
                cell_span_w = right_x - left_x

                if 0 < c_pos < len(col_edges) - 1:
                    self._draw_vline(grid, active_masks, left_x, band_top, band_bot)
                if 0 < end_col_idx < len(col_edges) - 1:
                    self._draw_vline(grid, active_masks, right_x, band_top, band_bot)

                cell_txt = " ".join(
                    b.text.strip()
                    for b in cell.content
                    if isinstance(b, Paragraph) and b.text.strip()
                )
                if cell_txt and cell_span_w >= 2:
                    pad_left = 2 if cell_span_w >= 4 else 1
                    pad_right = 1 if cell_span_w >= 4 else 0
                    text_col = left_x + pad_left
                    max_chars = max(0, right_x - text_col - pad_right)
                    if max_chars > 0:
                        self._write_text(grid, cell_txt[:max_chars], text_col, row_y)

                c_pos = end_col_idx

    def _place_image(
        self,
        grid: List[List[str]],
        img: ImageBlock,
        masks: Optional[List[List[int]]] = None,
    ) -> None:
        """Draw image placeholder frame in the character grid."""
        if not grid:
            return
        active_masks = self._ensure_masks(grid, masks)
        c0, r0 = self._pt_to_col_row(img.bbox.x0, img.bbox.y0)
        c1, r1 = self._pt_to_col_row(img.bbox.x1, img.bbox.y1)

        num_cols = len(grid[0])
        num_rows = len(grid)

        c0 = max(0, min(c0, num_cols - 1))
        c_right = max(c0 + 1, min(c1 - 1, num_cols - 1))
        r0 = max(0, min(r0, num_rows - 1))
        r_bottom = max(r0 + 1, min(r1 - 1, num_rows - 1))

        if self.unicode_boxes:
            self._draw_box(grid, active_masks, c0, r0, c_right, r_bottom)
        else:
            for c in range(c0, c_right + 1):
                grid[r0][c] = "."
                grid[r_bottom][c] = "."
            for r in range(r0, r_bottom + 1):
                grid[r][c0] = ":"
                grid[r][c_right] = ":"

        alt = img.alt_text or "Image"
        label = f"[ {alt} ]"
        mid_r = (r0 + r_bottom) // 2
        mid_c = max(c0 + 1, (c0 + c_right + 1 - len(label)) // 2)
        self._write_text(grid, label, mid_c, mid_r)

    def _place_vector(
        self,
        grid: List[List[str]],
        vec: VectorBlock,
        masks: Optional[List[List[int]]] = None,
    ) -> None:
        """Render vector paths and graphic frames using box-drawing and diagonal glyphs."""
        if not grid:
            return
        active_masks = self._ensure_masks(grid, masks)
        segments = _parse_svg_segments(vec.svg_path) if vec.svg_path else []

        drew_segment = False
        for x0, y0, x1, y1 in segments:
            c0, r0 = self._pt_to_col_row(x0, y0)
            c1, r1 = self._pt_to_col_row(x1, y1)
            if c0 == c1 and r0 == r1:
                continue
            drew_segment = True
            if r0 == r1:
                self._draw_hline(grid, active_masks, r0, c0, c1)
            elif c0 == c1:
                self._draw_vline(grid, active_masks, c0, r0, r1)
            else:
                self._draw_diagonal(grid, c0, r0, c1, r1)

        if not drew_segment and vec.bbox is not None:
            c0, r0 = self._pt_to_col_row(vec.bbox.x0, vec.bbox.y0)
            c1, r1 = self._pt_to_col_row(vec.bbox.x1, vec.bbox.y1)
            num_cols = len(grid[0])
            num_rows = len(grid)
            c0 = max(0, min(c0, num_cols - 1))
            c_right = max(c0, min(c1, num_cols - 1))
            r0 = max(0, min(r0, num_rows - 1))
            r_bottom = max(r0, min(r1, num_rows - 1))

            if r0 == r_bottom and c_right > c0:
                self._draw_hline(grid, active_masks, r0, c0, c_right)
            elif c0 == c_right and r_bottom > r0:
                self._draw_vline(grid, active_masks, c0, r0, r_bottom)
            elif c_right > c0 and r_bottom > r0:
                self._draw_box(grid, active_masks, c0, r0, c_right, r_bottom)


__all__ = ["TxtCanvasEmitter"]
