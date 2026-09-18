"""
Table detection engine for anyconvert.
Detects bordered (lattice) and borderless (stream) tables and converts them to IR TableBlocks.
"""

from typing import List, Optional
import pymupdf

from anyconvert.core.models import Block, ParagraphBlock, Rect, TableBlock, TableCell
from anyconvert.core.options import ConversionOptions


def detect_page_tables(
    page: pymupdf.Page,
    options: Optional[ConversionOptions] = None,
) -> List[TableBlock]:
    """Detect all tables on a page and convert them to TableBlock instances."""
    detected_blocks: List[TableBlock] = []

    try:
        tab_finder = page.find_tables()
        tables = tab_finder.tables

        if not tables:
            tab_finder_text = page.find_tables(strategy="text")
            tables = tab_finder_text.tables
    except Exception:
        return []

    for t in tables:
        raw_bbox = t.bbox
        table_rect = Rect(raw_bbox[0], raw_bbox[1], raw_bbox[2], raw_bbox[3])

        matrix = t.extract()
        if not matrix or not matrix[0]:
            continue

        row_count = len(matrix)
        col_count = len(matrix[0])
        cells: List[TableCell] = []

        cell_width = table_rect.width / max(1, col_count)
        cell_height = table_rect.height / max(1, row_count)

        for r_idx, row in enumerate(matrix):
            y0 = table_rect.y0 + (r_idx * cell_height)
            y1 = y0 + cell_height
            for c_idx, val in enumerate(row):
                x0 = table_rect.x0 + (c_idx * cell_width)
                x1 = x0 + cell_width
                cell_rect = Rect(x0, y0, x1, y1)
                text = (val or "").strip()

                cells.append(
                    TableCell(
                        row_idx=r_idx,
                        col_idx=c_idx,
                        bbox=cell_rect,
                        text=text,
                    )
                )

        detected_blocks.append(
            TableBlock(
                bbox=table_rect,
                rows=row_count,
                cols=col_count,
                cells=cells,
            )
        )

    return detected_blocks


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
