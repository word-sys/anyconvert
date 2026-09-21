"""Recursive XY-Cut algorithm and Reading Order DAG construction.

Implements hierarchical spatial projection profile cuts (Ha, Haralick & Phillips)
to segment document pages into columns, blocks, and natural reading sequences.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from anyconvert.common.geometry import BoundingBox
from anyconvert.exceptions import XYCutError
from anyconvert.layout.cluster import TextLine


class CutType(Enum):
    """Classification of an XY-cut decomposition node."""

    LEAF = auto()          # Indivisible content block
    HORIZONTAL = auto()    # Vertically stacked child regions (separated by horizontal cuts)
    VERTICAL = auto()      # Horizontally arranged columns (separated by vertical gutters)


@dataclass(slots=True)
class LayoutBlock:
    """Represents a coherent spatial block of document elements."""

    bbox: BoundingBox
    lines: List[TextLine] = field(default_factory=list)
    elements: List[Any] = field(default_factory=list)
    reading_index: int = 0

    @property
    def text(self) -> str:
        """Return aggregated text of lines in the block."""
        return "\n".join(line.text for line in self.lines if line.text)

    @property
    def width(self) -> float:
        """Horizontal width of block."""
        return self.bbox.width

    @property
    def height(self) -> float:
        """Vertical height of block."""
        return self.bbox.height


@dataclass(slots=True)
class XYCutNode:
    """Node in the hierarchical recursive XY-cut tree."""

    cut_type: CutType
    bbox: BoundingBox
    children: List[XYCutNode] = field(default_factory=list)
    block: Optional[LayoutBlock] = None
    depth: int = 0

    @property
    def is_leaf(self) -> bool:
        """Return True if this node is a leaf block."""
        return self.cut_type == CutType.LEAF


def _default_get_bbox(item: Any) -> BoundingBox:
    """Extract bounding box from standard layout objects."""
    if hasattr(item, "bbox") and isinstance(item.bbox, BoundingBox):
        return item.bbox
    raise XYCutError(f"Cannot extract bounding box from object of type {type(item).__name__}")


def _merge_intervals(intervals: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """Merge 1D overlapping or contiguous intervals sorted by start coordinate."""
    if not intervals:
        return []
    sorted_ints = sorted(intervals, key=lambda iv: iv[0])
    merged: List[Tuple[float, float]] = [sorted_ints[0]]

    for start, end in sorted_ints[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))

    return merged


def recursive_xy_cut(
    elements: Sequence[Any],
    get_bbox: Optional[Callable[[Any], BoundingBox]] = None,
    min_x_gap: float = 15.0,
    min_y_gap: float = 10.0,
    max_depth: int = 25,
    depth: int = 0,
) -> XYCutNode:
    """Recursively partition layout elements using alternating horizontal and vertical projection cuts.

    Args:
        elements: Sequence of elements (e.g. TextLine, VectorElement, ImageElement).
        get_bbox: Optional function to retrieve BoundingBox from an element.
        min_x_gap: Minimum horizontal whitespace gutter width to trigger a vertical cut (pt).
        min_y_gap: Minimum vertical whitespace height to trigger a horizontal cut (pt).
        max_depth: Maximum recursion depth to prevent infinite loops.
        depth: Current recursion depth.

    Returns:
        Root XYCutNode representing the hierarchical decomposition tree.
    """
    bbox_fn = get_bbox if get_bbox is not None else _default_get_bbox

    if not elements:
        empty_box = BoundingBox(0.0, 0.0, 0.0, 0.0)
        return XYCutNode(
            cut_type=CutType.LEAF,
            bbox=empty_box,
            block=LayoutBlock(bbox=empty_box),
            depth=depth,
        )

    # Compute overall bounding box
    item_bboxes: List[Tuple[Any, BoundingBox]] = [(e, bbox_fn(e).normalized()) for e in elements]
    overall_bbox = item_bboxes[0][1]
    for _, b in item_bboxes[1:]:
        overall_bbox = overall_bbox.union(b)

    # Base case: single element or max depth reached
    if len(elements) == 1 or depth >= max_depth:
        lines: List[TextLine] = [e for e in elements if isinstance(e, TextLine)]
        block = LayoutBlock(bbox=overall_bbox, lines=lines, elements=list(elements))
        return XYCutNode(
            cut_type=CutType.LEAF,
            bbox=overall_bbox,
            block=block,
            depth=depth,
        )

    # 1. Attempt Horizontal Cut (projecting along Y-axis, finding vertical gaps)
    # Collect Y intervals [y0, y1]
    y_intervals = [(b.y0, b.y1) for _, b in item_bboxes]
    merged_y = _merge_intervals(y_intervals)

    # Check for gaps between merged intervals
    y_cut_points: List[float] = []
    for i in range(len(merged_y) - 1):
        gap_size = merged_y[i + 1][0] - merged_y[i][1]
        if gap_size >= min_y_gap:
            # Cut midpoint
            y_cut_points.append((merged_y[i][1] + merged_y[i + 1][0]) / 2.0)

    if y_cut_points:
        # Partition elements into horizontal bands ordered top-to-bottom
        bands: List[List[Any]] = [[] for _ in range(len(y_cut_points) + 1)]
        for elem, b in item_bboxes:
            assigned = False
            elem_center_y = b.center.y
            for cut_idx, cut_y in enumerate(y_cut_points):
                if elem_center_y < cut_y:
                    bands[cut_idx].append(elem)
                    assigned = True
                    break
            if not assigned:
                bands[-1].append(elem)

        # Filter non-empty bands
        active_bands = [band for band in bands if band]
        if len(active_bands) > 1:
            child_nodes = [
                recursive_xy_cut(
                    band,
                    get_bbox=bbox_fn,
                    min_x_gap=min_x_gap,
                    min_y_gap=min_y_gap,
                    max_depth=max_depth,
                    depth=depth + 1,
                )
                for band in active_bands
            ]
            return XYCutNode(
                cut_type=CutType.HORIZONTAL,
                bbox=overall_bbox,
                children=child_nodes,
                depth=depth,
            )

    # 2. Attempt Vertical Cut (projecting along X-axis, finding horizontal column gutters)
    x_intervals = [(b.x0, b.x1) for _, b in item_bboxes]
    merged_x = _merge_intervals(x_intervals)

    x_cut_points: List[float] = []
    for i in range(len(merged_x) - 1):
        gap_size = merged_x[i + 1][0] - merged_x[i][1]
        if gap_size >= min_x_gap:
            x_cut_points.append((merged_x[i][1] + merged_x[i + 1][0]) / 2.0)

    if x_cut_points:
        # Partition elements into columns ordered left-to-right
        columns: List[List[Any]] = [[] for _ in range(len(x_cut_points) + 1)]
        for elem, b in item_bboxes:
            assigned = False
            elem_center_x = b.center.x
            for cut_idx, cut_x in enumerate(x_cut_points):
                if elem_center_x < cut_x:
                    columns[cut_idx].append(elem)
                    assigned = True
                    break
            if not assigned:
                columns[-1].append(elem)

        active_columns = [col for col in columns if col]
        if len(active_columns) > 1:
            child_nodes = [
                recursive_xy_cut(
                    col,
                    get_bbox=bbox_fn,
                    min_x_gap=min_x_gap,
                    min_y_gap=min_y_gap,
                    max_depth=max_depth,
                    depth=depth + 1,
                )
                for col in active_columns
            ]
            return XYCutNode(
                cut_type=CutType.VERTICAL,
                bbox=overall_bbox,
                children=child_nodes,
                depth=depth,
            )

    # 3. Neither cut possible -> atomic leaf block
    lines = [e for e in elements if isinstance(e, TextLine)]
    # Sort lines inside the atomic block top-to-bottom
    lines.sort(key=lambda l: (round(l.bbox.y0, 1), l.bbox.x0))
    block = LayoutBlock(bbox=overall_bbox, lines=lines, elements=list(elements))
    return XYCutNode(
        cut_type=CutType.LEAF,
        bbox=overall_bbox,
        block=block,
        depth=depth,
    )


def linearize_reading_order(root: XYCutNode) -> List[LayoutBlock]:
    """Traverse the hierarchical XY-cut tree in pre-order to produce the natural reading order.

    Columns in VERTICAL splits are read sequentially (Column 1 top-to-bottom, then Column 2, etc.),
    correctly resolving multi-column and sidebar documents.

    Args:
        root: Root of the XY-cut decomposition tree.

    Returns:
        Ordered list of LayoutBlock objects with assigned reading indices.
    """
    blocks: List[LayoutBlock] = []

    def traverse(node: XYCutNode) -> None:
        if node.is_leaf:
            if node.block is not None:
                blocks.append(node.block)
            return

        for child in node.children:
            traverse(child)

    traverse(root)

    # Assign reading indices
    for idx, blk in enumerate(blocks):
        blk.reading_index = idx

    return blocks


class ReadingOrderDAG:
    """Directed Acyclic Graph modeling precedence relationships in document reading flow."""

    __slots__ = ("_nodes", "_edges", "_in_degree")

    def __init__(self) -> None:
        self._nodes: List[LayoutBlock] = []
        self._edges: Dict[int, Set[int]] = {}
        self._in_degree: Dict[int, int] = {}

    def add_block(self, block: LayoutBlock) -> None:
        """Add a layout block node to the DAG."""
        bid = id(block)
        if bid not in self._edges:
            self._nodes.append(block)
            self._edges[bid] = set()
            self._in_degree[bid] = 0

    def add_precedence(self, before: LayoutBlock, after: LayoutBlock) -> None:
        """Declare that 'before' must be read prior to 'after'."""
        self.add_block(before)
        self.add_block(after)
        b_id = id(before)
        a_id = id(after)
        if a_id not in self._edges[b_id]:
            self._edges[b_id].add(a_id)
            self._in_degree[a_id] += 1

    def topological_sort(self) -> List[LayoutBlock]:
        """Compute a linear reading order that satisfies all precedence constraints.

        Returns:
            Topologically sorted list of LayoutBlock objects.

        Raises:
            XYCutError: If cyclic dependency is detected.
        """
        in_degree = dict(self._in_degree)
        id_to_block = {id(b): b for b in self._nodes}

        # Queue of blocks with 0 incoming dependencies
        # Tie-break priority: top-to-bottom, left-to-right
        ready: List[LayoutBlock] = [
            id_to_block[bid] for bid, deg in in_degree.items() if deg == 0
        ]
        ready.sort(key=lambda b: (round(b.bbox.y0, 1), b.bbox.x0))

        ordered: List[LayoutBlock] = []

        while ready:
            curr = ready.pop(0)
            ordered.append(curr)
            curr_id = id(curr)

            for neighbor_id in self._edges[curr_id]:
                in_degree[neighbor_id] -= 1
                if in_degree[neighbor_id] == 0:
                    ready.append(id_to_block[neighbor_id])

            ready.sort(key=lambda b: (round(b.bbox.y0, 1), b.bbox.x0))

        if len(ordered) != len(self._nodes):
            raise XYCutError("Cycle detected in reading order graph")

        for idx, blk in enumerate(ordered):
            blk.reading_index = idx

        return ordered

    @classmethod
    def from_xy_cut_tree(cls, root: XYCutNode) -> ReadingOrderDAG:
        """Construct a ReadingOrderDAG from a hierarchical XYCutNode tree."""
        dag = cls()
        blocks = linearize_reading_order(root)
        for i in range(len(blocks) - 1):
            dag.add_precedence(blocks[i], blocks[i + 1])
        return dag


__all__ = [
    "CutType",
    "LayoutBlock",
    "XYCutNode",
    "recursive_xy_cut",
    "linearize_reading_order",
    "ReadingOrderDAG",
]
