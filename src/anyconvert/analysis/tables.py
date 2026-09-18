"""
Table detection engine for anyconvert.
Detects bordered (lattice) and borderless (stream) tables, reconstructs cell spans,
calculates exact column widths and row heights, and reconstructs cell shading and borders
from vector graphics.
"""

from typing import List, Optional, Set, Tuple
import pymupdf

from anyconvert.core.models import (
    Block,
    Color,
    ParagraphBlock,
    Rect,
    TableBlock,
    TableCell,
    VectorShapeBlock,
)
from anyconvert.core.options import ConversionOptions


def detect_page_tables(
    page: pymupdf.Page,
    options: Optional[ConversionOptions] = None,
) -> List[TableBlock]:
    """
    Detect all tables on a page and convert them to TableBlock instances.
    Uses line-based detection with placement refinement as the primary engine.
    """
    tables: List[pymupdf.table.Table] = []

    try:
        # Primary: find tables with lines and placement refinement
        tab_finder = page.find_tables(strategy="lines", refine=True)
        tables = tab_finder.tables

        if not tables:
            # Fallback without refine
            tab_finder = page.find_tables(strategy="lines")
            tables = tab_finder.tables

        if not tables and options and options.detect_tables:
            # Text-based strategy with strict validation to prevent false positives on normal paragraphs
            tab_finder_text = page.find_tables(strategy="text")
            candidate_tables = tab_finder_text.tables
            valid_text_tables = []
            for ct in candidate_tables:
                if ct.row_count >= 2 and ct.col_count >= 2:
                    matrix = ct.extract()
                    if matrix:
                        # Check word length to ensure it's not prose
                        total_words = 0
                        cell_count = 0
                        for row in matrix:
                            for val in row:
                                if val and val.strip():
                                    words = val.strip().split()
                                    total_words += len(words)
                                    cell_count += 1
                        if cell_count >= 4 and (total_words / cell_count) <= 6.0:
                            valid_text_tables.append(ct)
            tables = valid_text_tables
    except Exception:
        return []

    detected_blocks: List[TableBlock] = []

    for t in tables:
        raw_bbox = t.bbox
        table_rect = Rect(raw_bbox[0], raw_bbox[1], raw_bbox[2], raw_bbox[3])

        matrix = t.extract()
        if not matrix or not matrix[0]:
            continue

        row_count = t.row_count
        col_count = t.col_count
        if row_count <= 0 or col_count <= 0:
            continue

        # 1. Compute exact column widths
        col_widths: List[float] = []
        if hasattr(t, "cells") and t.cells:
            x_coords = set()
            for c_box in t.cells:
                if c_box:
                    x_coords.add(round(c_box[0], 2))
                    x_coords.add(round(c_box[2], 2))
            sorted_x = sorted(list(x_coords))
            if len(sorted_x) - 1 == col_count:
                col_widths = [sorted_x[i + 1] - sorted_x[i] for i in range(len(sorted_x) - 1)]

        if not col_widths or len(col_widths) != col_count:
            col_widths = [table_rect.width / max(1, col_count)] * col_count

        # 2. Compute row heights
        row_heights: List[float] = []
        if hasattr(t, "rows") and t.rows:
            for r in t.rows:
                row_heights.append(max(10.0, r.bbox[3] - r.bbox[1]))
        if not row_heights or len(row_heights) != row_count:
            row_heights = [table_rect.height / max(1, row_count)] * row_count

        # 3. Extract cells with span and tag resolution
        cells: List[TableCell] = []
        if hasattr(t, "placements") and t.placements:
            occupied = [[False] * col_count for _ in range(row_count)]
            header_rows = getattr(t, "header_rows", 1) if getattr(t, "header_rows", None) else 0

            for r_idx, row_places in enumerate(t.placements):
                if r_idx >= row_count:
                    break
                c_idx = 0
                for sc in row_places:
                    while c_idx < col_count and occupied[r_idx][c_idx]:
                        c_idx += 1
                    if c_idx >= col_count:
                        break

                    c_box = getattr(sc, "bbox", None)
                    if c_box:
                        cell_bbox = Rect(c_box[0], c_box[1], c_box[2], c_box[3])
                    else:
                        cell_bbox = Rect(
                            table_rect.x0 + sum(col_widths[:c_idx]),
                            table_rect.y0 + sum(row_heights[:r_idx]),
                            table_rect.x0 + sum(col_widths[:c_idx + getattr(sc, "colspan", 1)]),
                            table_rect.y0 + sum(row_heights[:r_idx + getattr(sc, "rowspan", 1)]),
                        )

                    text = (getattr(sc, "text", "") or "").strip()
                    colspan = getattr(sc, "colspan", 1)
                    rowspan = getattr(sc, "rowspan", 1)
                    tag = getattr(sc, "tag", "td")
                    is_header = (tag == "th") or (r_idx < header_rows)

                    cell = TableCell(
                        row_idx=r_idx,
                        col_idx=c_idx,
                        bbox=cell_bbox,
                        text=text,
                        row_span=rowspan,
                        col_span=colspan,
                        is_header=is_header,
                    )
                    cells.append(cell)

                    for dr in range(rowspan):
                        for dc in range(colspan):
                            if r_idx + dr < row_count and c_idx + dc < col_count:
                                occupied[r_idx + dr][c_idx + dc] = True
                    c_idx += colspan

        # Fallback to t.rows or matrix if placements didn't populate cells
        if not cells:
            if hasattr(t, "rows") and t.rows:
                for r_idx, row in enumerate(t.rows):
                    for c_idx, cell_box in enumerate(row.cells):
                        if cell_box is None:
                            continue
                        cell_rect = Rect(cell_box[0], cell_box[1], cell_box[2], cell_box[3])
                        val = matrix[r_idx][c_idx] if (r_idx < len(matrix) and c_idx < len(matrix[r_idx])) else ""
                        cells.append(
                            TableCell(
                                row_idx=r_idx,
                                col_idx=c_idx,
                                bbox=cell_rect,
                                text=(val or "").strip(),
                                is_header=(r_idx == 0),
                            )
                        )
            else:
                for r_idx, row in enumerate(matrix):
                    for c_idx, val in enumerate(row):
                        cell_rect = Rect(
                            table_rect.x0 + sum(col_widths[:c_idx]),
                            table_rect.y0 + sum(row_heights[:r_idx]),
                            table_rect.x0 + sum(col_widths[:c_idx + 1]),
                            table_rect.y0 + sum(row_heights[:r_idx + 1]),
                        )
                        cells.append(
                            TableCell(
                                row_idx=r_idx,
                                col_idx=c_idx,
                                bbox=cell_rect,
                                text=(val or "").strip(),
                                is_header=(r_idx == 0),
                            )
                        )

        detected_blocks.append(
            TableBlock(
                bbox=table_rect,
                rows=row_count,
                cols=col_count,
                cells=cells,
                col_widths=col_widths,
                row_heights=row_heights,
            )
        )

    return detected_blocks


def reconstruct_table_shading_and_borders(
    tables: List[TableBlock],
    drawings: List[VectorShapeBlock],
) -> List[VectorShapeBlock]:
    """
    Match vector graphics against table cells to detect background shading and custom border styles.
    Returns unabsorbed drawings that do not belong to tables.
    """
    if not tables or not drawings:
        return drawings

    absorbed_ids: Set[int] = set()
    tol = 3.0

    for table in tables:
        for cell in table.cells:
            cell_box = cell.bbox
            if cell_box.area <= 0:
                continue

            cell_cx = (cell_box.x0 + cell_box.x1) / 2.0
            cell_cy = (cell_box.y0 + cell_box.y1) / 2.0

            # 1. Background fill detection
            for d in drawings:
                if d.fill_color is not None:
                    # Drawing contains center of cell or substantially encloses cell
                    if (d.bbox.x0 <= cell_cx <= d.bbox.x1 and d.bbox.y0 <= cell_cy <= d.bbox.y1) or d.bbox.contains(cell_box):
                        cell.background_color = d.fill_color
                        absorbed_ids.add(id(d))
                    elif d.bbox.intersects(cell_box):
                        x_ov = max(0.0, min(d.bbox.x1, cell_box.x1) - max(d.bbox.x0, cell_box.x0))
                        y_ov = max(0.0, min(d.bbox.y1, cell_box.y1) - max(d.bbox.y0, cell_box.y0))
                        if (x_ov * y_ov) / cell_box.area > 0.6:
                            cell.background_color = d.fill_color
                            absorbed_ids.add(id(d))

            # 2. Border detection
            for d in drawings:
                is_stroke = (d.stroke_color is not None)
                is_thin_rect = (d.fill_color is not None and (d.bbox.height <= 2.5 or d.bbox.width <= 2.5))
                if not (is_stroke or is_thin_rect):
                    continue

                color = d.stroke_color if is_stroke else d.fill_color
                width = d.stroke_width if is_stroke else min(d.bbox.width, d.bbox.height)

                # Top border
                if abs(d.bbox.y0 - cell_box.y0) <= tol or abs(d.bbox.y1 - cell_box.y0) <= tol or (d.bbox.y0 - tol <= cell_box.y0 <= d.bbox.y1 + tol and d.bbox.height <= 3.0):
                    x_overlap = max(0.0, min(d.bbox.x1, cell_box.x1) - max(d.bbox.x0, cell_box.x0))
                    if (x_overlap / cell_box.width) >= 0.6:
                        cell.border_top = True
                        cell.border_top_width = width
                        cell.border_top_color = color
                        absorbed_ids.add(id(d))

                # Bottom border
                if abs(d.bbox.y0 - cell_box.y1) <= tol or abs(d.bbox.y1 - cell_box.y1) <= tol or (d.bbox.y0 - tol <= cell_box.y1 <= d.bbox.y1 + tol and d.bbox.height <= 3.0):
                    x_overlap = max(0.0, min(d.bbox.x1, cell_box.x1) - max(d.bbox.x0, cell_box.x0))
                    if (x_overlap / cell_box.width) >= 0.6:
                        cell.border_bottom = True
                        cell.border_bottom_width = width
                        cell.border_bottom_color = color
                        absorbed_ids.add(id(d))

                # Left border
                if abs(d.bbox.x0 - cell_box.x0) <= tol or abs(d.bbox.x1 - cell_box.x0) <= tol or (d.bbox.x0 - tol <= cell_box.x0 <= d.bbox.x1 + tol and d.bbox.width <= 3.0):
                    y_overlap = max(0.0, min(d.bbox.y1, cell_box.y1) - max(d.bbox.y0, cell_box.y0))
                    if (y_overlap / cell_box.height) >= 0.6:
                        cell.border_left = True
                        cell.border_left_width = width
                        cell.border_left_color = color
                        absorbed_ids.add(id(d))

                # Right border
                if abs(d.bbox.x0 - cell_box.x1) <= tol or abs(d.bbox.x1 - cell_box.x1) <= tol or (d.bbox.x0 - tol <= cell_box.x1 <= d.bbox.x1 + tol and d.bbox.width <= 3.0):
                    y_overlap = max(0.0, min(d.bbox.y1, cell_box.y1) - max(d.bbox.y0, cell_box.y0))
                    if (y_overlap / cell_box.height) >= 0.6:
                        cell.border_right = True
                        cell.border_right_width = width
                        cell.border_right_color = color
                        absorbed_ids.add(id(d))

        # Check if table had any explicitly styled borders
        any_borders = any(
            (c.border_top_color or c.border_bottom_color or c.border_left_color or c.border_right_color)
            for c in table.cells
        )
        if any_borders:
            for c in table.cells:
                if c.border_top_color is None:
                    c.border_top = False
                if c.border_bottom_color is None:
                    c.border_bottom = False
                if c.border_left_color is None:
                    c.border_left = False
                if c.border_right_color is None:
                    c.border_right = False

    return [d for d in drawings if id(d) not in absorbed_ids]


def is_block_inside_table(block: Block, tables: List[TableBlock]) -> bool:
    """Check if a block's bounding box is enclosed by any detected table."""
    b_rect = block.bbox
    for table in tables:
        t_rect = table.bbox
        if t_rect.contains(b_rect):
            return True
        if b_rect.intersects(t_rect):
            x_overlap = max(0.0, min(b_rect.x1, t_rect.x1) - max(b_rect.x0, t_rect.x0))
            y_overlap = max(0.0, min(b_rect.y1, t_rect.y1) - max(b_rect.y0, t_rect.y0))
            overlap_area = x_overlap * y_overlap
            if b_rect.area > 0 and (overlap_area / b_rect.area) > 0.6:
                return True
    return False


def filter_blocks_in_tables(blocks: List[Block], tables: List[TableBlock]) -> List[Block]:
    """Remove text blocks that fall inside detected tables to prevent duplication."""
    if not tables:
        return blocks
    return [b for b in blocks if not is_block_inside_table(b, tables)]

