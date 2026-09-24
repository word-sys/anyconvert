"""Table detection, vector stroke intersection, and cell topology reconstruction.

Implements grid matrix reconstruction from vector rulings, borderless table detection
via whitespace gutters, and computation of cell spans (rowspan and colspan).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from anyconvert.common.color import Color
from anyconvert.common.geometry import BoundingBox, Point
from anyconvert.layout.cluster import TextLine, TextWord
from anyconvert.layout.spatial import normalize_bbox_pdf_to_doc
from anyconvert.pdf.content.interpreter import VectorElement


@dataclass(slots=True)
class TableCellLayout:
    """Represents an atomic cell in a reconstructed table grid."""

    row: int
    col: int
    row_span: int = 1
    col_span: int = 1
    bbox: BoundingBox = field(default_factory=lambda: BoundingBox(0, 0, 0, 0))
    lines: List[TextLine] = field(default_factory=list)
    background_color: Optional[Color] = None
    borders: Dict[str, bool] = field(default_factory=dict)

    @property
    def text(self) -> str:
        """Joined text of all lines in cell."""
        return "\n".join(l.text for l in self.lines if l.text)


@dataclass(slots=True)
class TableRowLayout:
    """Represents a row in a reconstructed table."""

    cells: List[TableCellLayout] = field(default_factory=list)
    row_index: int = 0
    bbox: BoundingBox = field(default_factory=lambda: BoundingBox(0, 0, 0, 0))
    is_header: bool = False


@dataclass(slots=True)
class TableLayout:
    """Represents a complete detected table with rows, columns, and cell topology."""

    rows: List[TableRowLayout] = field(default_factory=list)
    num_rows: int = 0
    num_cols: int = 0
    col_widths: List[float] = field(default_factory=list)
    bbox: BoundingBox = field(default_factory=lambda: BoundingBox(0, 0, 0, 0))
    has_borders: bool = True

    @property
    def total_cells(self) -> int:
        """Return total number of cells across all rows."""
        return sum(len(r.cells) for r in self.rows)


def _cluster_coords(coords: List[float], tolerance: float = 4.0) -> List[float]:
    """Group close 1D coordinates within tolerance into unified grid lines."""
    if not coords:
        return []
    sorted_c = sorted(coords)
    clusters: List[List[float]] = [[sorted_c[0]]]

    for c in sorted_c[1:]:
        if c - clusters[-1][-1] <= tolerance:
            clusters[-1].append(c)
        else:
            clusters.append([c])

    return [sum(cl) / len(cl) for cl in clusters]


def _extract_ruling_lines(
    vectors: Sequence[VectorElement],
    page_height: Optional[float] = None,
    min_length: float = 20.0,
    max_thickness: float = 4.0,
) -> Tuple[List[Tuple[float, float, float]], List[Tuple[float, float, float]]]:
    """Extract horizontal and vertical line segments from vector elements.

    Returns:
        Tuple of (horizontal_lines, vertical_lines).
        Horizontal: list of (y, x0, x1)
        Vertical: list of (x, y0, y1)
    """
    h_lines: List[Tuple[float, float, float]] = []
    v_lines: List[Tuple[float, float, float]] = []

    for v in vectors:
        if v.bbox is None:
            continue
        bbox = (
            normalize_bbox_pdf_to_doc(v.bbox, page_height)
            if page_height is not None
            else v.bbox.normalized()
        )

        w = bbox.width
        h = bbox.height

        # Horizontal ruling
        if w >= min_length and h <= max_thickness:
            y = (bbox.y0 + bbox.y1) / 2.0
            h_lines.append((y, bbox.x0, bbox.x1))

        # Vertical ruling
        elif h >= min_length and w <= max_thickness:
            x = (bbox.x0 + bbox.x1) / 2.0
            v_lines.append((x, bbox.y0, bbox.y1))

    return h_lines, v_lines


def detect_tables_from_vectors(
    vectors: Sequence[VectorElement],
    lines: Sequence[TextLine],
    page_height: Optional[float] = None,
    tolerance: float = 5.0,
) -> List[TableLayout]:
    """Detect grid tables from vector rulings and reconstruct cell topology (with spans).

    Args:
        vectors: Vector stroke and fill elements.
        lines: TextLine elements on the page.
        page_height: Page height for PDF coordinate normalization.
        tolerance: Coordinate alignment tolerance in points.

    Returns:
        List of detected TableLayout objects.
    """
    h_lines, v_lines = _extract_ruling_lines(vectors, page_height=page_height)

    # Need at least 2 horizontal lines and 2 vertical lines to form a grid cell
    if len(h_lines) < 2 or len(v_lines) < 2:
        return []

    # Extract unique grid X and Y coordinates
    all_y = [y for y, _, _ in h_lines]
    all_x = [x for x, _, _ in v_lines]

    grid_y = _cluster_coords(all_y, tolerance=tolerance)
    grid_x = _cluster_coords(all_x, tolerance=tolerance)

    if len(grid_y) < 2 or len(grid_x) < 2:
        return []

    num_rows = len(grid_y) - 1
    num_cols = len(grid_x) - 1

    # Check for presence of ruling lines at each boundary
    def has_h_segment(y_target: float, x_start: float, x_end: float) -> bool:
        for y, x0, x1 in h_lines:
            if abs(y - y_target) <= tolerance:
                if x0 <= x_start + tolerance and x1 >= x_end - tolerance:
                    return True
        return False

    def has_v_segment(x_target: float, y_start: float, y_end: float) -> bool:
        for x, y0, y1 in v_lines:
            if abs(x - x_target) <= tolerance:
                if y0 <= y_start + tolerance and y1 >= y_end - tolerance:
                    return True
        return False

    # Count physical intersections between horizontal and vertical rulings
    intersections = 0
    for hy, hx0, hx1 in h_lines:
        for vx, vy0, vy1 in v_lines:
            if (hx0 - tolerance <= vx <= hx1 + tolerance) and (vy0 - tolerance <= hy <= vy1 + tolerance):
                intersections += 1

    # A minimal 1-cell grid table requires at least 4 corner intersections (2 horizontal x 2 vertical lines)
    if intersections < 4:
        return []

    # Check that at least an outer border exists
    top_y = grid_y[0]
    bottom_y = grid_y[-1]
    left_x = grid_x[0]
    right_x = grid_x[-1]

    has_top = has_h_segment(top_y, left_x, right_x)
    has_bottom = has_h_segment(bottom_y, left_x, right_x)
    has_left = has_v_segment(left_x, top_y, bottom_y)
    has_right = has_v_segment(right_x, top_y, bottom_y)

    borders_count = sum(bool(b) for b in (has_top, has_bottom, has_left, has_right))
    if borders_count < 2 or not ((has_top and has_bottom) or (has_left and has_right) or borders_count >= 3):
        # Weak ruling evidence, not a bordered table
        return []

    # Build cell matrix with colspan and rowspan tracking
    visited: Set[Tuple[int, int]] = set()
    table_rows: List[TableRowLayout] = []

    for r in range(num_rows):
        row_cells: List[TableCellLayout] = []
        r_y0 = grid_y[r]
        r_y1 = grid_y[r + 1]

        for c in range(num_cols):
            if (r, c) in visited:
                continue

            c_x0 = grid_x[c]
            c_x1 = grid_x[c + 1]

            # Calculate colspan: does right border exist?
            colspan = 1
            curr_c = c
            while curr_c + 1 < num_cols:
                boundary_x = grid_x[curr_c + 1]
                if not has_v_segment(boundary_x, r_y0, r_y1):
                    colspan += 1
                    curr_c += 1
                else:
                    break

            # Calculate rowspan: does bottom border exist across the columns?
            rowspan = 1
            curr_r = r
            while curr_r + 1 < num_rows:
                boundary_y = grid_y[curr_r + 1]
                has_bottom_border = True
                for span_c in range(c, c + colspan):
                    if has_h_segment(boundary_y, grid_x[span_c], grid_x[span_c + 1]):
                        has_bottom_border = True
                    else:
                        has_bottom_border = False
                        break
                if not has_bottom_border:
                    rowspan += 1
                    curr_r += 1
                else:
                    break

            # Mark all spanned cells as visited
            for sr in range(r, r + rowspan):
                for sc in range(c, c + colspan):
                    visited.add((sr, sc))

            cell_bbox = BoundingBox(grid_x[c], grid_y[r], grid_x[c + colspan], grid_y[r + rowspan])

            # Assign text lines that fall inside this cell
            cell_lines: List[TextLine] = []
            for tl in lines:
                if cell_bbox.intersects(tl.bbox):
                    # Check center point falls within cell
                    c_pt = tl.bbox.center
                    if cell_bbox.contains_point(c_pt):
                        cell_lines.append(tl)

            cell = TableCellLayout(
                row=r,
                col=c,
                row_span=rowspan,
                col_span=colspan,
                bbox=cell_bbox,
                lines=cell_lines,
            )
            row_cells.append(cell)

        if row_cells:
            row_bbox = BoundingBox(grid_x[0], r_y0, grid_x[-1], r_y1)
            is_header = r == 0  # First row is treated as header by default
            table_rows.append(TableRowLayout(cells=row_cells, row_index=r, bbox=row_bbox, is_header=is_header))

    if not table_rows:
        return []

    # Calculate column widths
    col_widths = [grid_x[i + 1] - grid_x[i] for i in range(num_cols)]
    table_bbox = BoundingBox(grid_x[0], grid_y[0], grid_x[-1], grid_y[-1])

    return [
        TableLayout(
            rows=table_rows,
            num_rows=num_rows,
            num_cols=num_cols,
            col_widths=col_widths,
            bbox=table_bbox,
            has_borders=True,
        )
    ]


def detect_borderless_tables(
    lines: Sequence[TextLine],
    min_columns: int = 2,
    min_rows: int = 3,
    gutter_min: float = 14.0,
) -> List[TableLayout]:
    """Detect borderless tabular data using multi-column word alignments and whitespace gutters.

    Args:
        lines: Sequence of TextLine elements.
        min_columns: Minimum number of aligned columns to qualify as a table.
        min_rows: Minimum consecutive aligned rows to qualify as a table.
        gutter_min: Minimum horizontal whitespace gap between columns.

    Returns:
        List of detected borderless TableLayout instances.
    """
    if len(lines) < min_rows:
        return []

    # Analyze lines that contain multiple words
    candidate_lines: List[Tuple[TextLine, List[TextWord]]] = []
    for l in lines:
        if len(l.words) >= min_columns:
            candidate_lines.append((l, l.words))

    if len(candidate_lines) < min_rows:
        return []

    # Check for consistent column start positions across consecutive candidate lines
    # Collect all word x0 coordinates
    x0_coords: List[float] = []
    for _, words in candidate_lines:
        for w in words:
            x0_coords.append(w.bbox.x0)

    clustered_x = _cluster_coords(x0_coords, tolerance=8.0)
    # Filter columns separated by at least gutter_min
    valid_cols: List[float] = [clustered_x[0]]
    for x in clustered_x[1:]:
        if x - valid_cols[-1] >= gutter_min:
            valid_cols.append(x)

    if len(valid_cols) < min_columns:
        return []

    num_cols = len(valid_cols)
    table_rows: List[TableRowLayout] = []

    for r_idx, (t_line, words) in enumerate(candidate_lines):
        row_cells: List[TableCellLayout] = []
        # Assign words to the nearest matching column
        col_buckets: List[List[TextWord]] = [[] for _ in range(num_cols)]

        for w in words:
            # Find closest column
            best_col = min(range(num_cols), key=lambda c: abs(w.bbox.x0 - valid_cols[c]))
            col_buckets[best_col].append(w)

        for c_idx, bucket in enumerate(col_buckets):
            if bucket:
                x0 = bucket[0].bbox.x0
                x1 = bucket[-1].bbox.x1
                y0 = t_line.bbox.y0
                y1 = t_line.bbox.y1
                cell_box = BoundingBox(x0, y0, x1, y1)
                text = " ".join(w.text for w in bucket)
                cell_line = TextLine(
                    words=bucket,
                    bbox=cell_box,
                    baseline_y=t_line.baseline_y,
                    text=text,
                    font_name=bucket[0].font_name,
                    font_size=bucket[0].font_size,
                    color=bucket[0].color,
                )
                cell = TableCellLayout(
                    row=r_idx,
                    col=c_idx,
                    bbox=cell_box,
                    lines=[cell_line],
                )
            else:
                c_x0 = valid_cols[c_idx]
                c_x1 = valid_cols[c_idx + 1] if c_idx + 1 < num_cols else c_x0 + 40.0
                cell = TableCellLayout(
                    row=r_idx,
                    col=c_idx,
                    bbox=BoundingBox(c_x0, t_line.bbox.y0, c_x1, t_line.bbox.y1),
                    lines=[],
                )
            row_cells.append(cell)

        table_rows.append(
            TableRowLayout(
                cells=row_cells,
                row_index=r_idx,
                bbox=t_line.bbox,
                is_header=(r_idx == 0),
            )
        )

    if len(table_rows) < min_rows:
        return []

    # Compute overall table bounding box
    t_box = table_rows[0].bbox
    for r in table_rows[1:]:
        t_box = t_box.union(r.bbox)

    col_widths = [
        valid_cols[i + 1] - valid_cols[i] if i + 1 < num_cols else 50.0
        for i in range(num_cols)
    ]

    return [
        TableLayout(
            rows=table_rows,
            num_rows=len(table_rows),
            num_cols=num_cols,
            col_widths=col_widths,
            bbox=t_box,
            has_borders=False,
        )
    ]


__all__ = [
    "TableCellLayout",
    "TableRowLayout",
    "TableLayout",
    "detect_tables_from_vectors",
    "detect_borderless_tables",
]
