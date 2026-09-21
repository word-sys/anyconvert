"""2D Spatial grid index and coordinate space normalization.

Implements coordinate transformation between PDF presentation space (bottom-left origin)
and document presentation space (top-left origin), along with an efficient 2D spatial
grid bucket index for collision detection, bounding box queries, and nearest-neighbor search.
"""

from __future__ import annotations

import math
from typing import (
    Any,
    Dict,
    Generic,
    List,
    Optional,
    Set,
    Tuple,
    TypeVar,
)

from anyconvert.common.geometry import BoundingBox, Point
from anyconvert.exceptions import SpatialIndexError

T = TypeVar("T")


def normalize_bbox_pdf_to_doc(bbox: BoundingBox, page_height: float) -> BoundingBox:
    """Convert a bounding box from PDF coordinates (bottom-left) to document space (top-left).

    PDF coordinates: origin at bottom-left, Y ascending upwards.
    Document presentation space: origin at top-left, Y descending downwards.
    Formula:
        Y_doc = page_height - Y_pdf

    Args:
        bbox: Bounding box in PDF coordinates.
        page_height: Total vertical height of the page.

    Returns:
        BoundingBox in document coordinates with x0 <= x1 and y0 <= y1.
    """
    y0_doc = page_height - bbox.y1
    y1_doc = page_height - bbox.y0
    return BoundingBox(
        x0=min(bbox.x0, bbox.x1),
        y0=min(y0_doc, y1_doc),
        x1=max(bbox.x0, bbox.x1),
        y1=max(y0_doc, y1_doc),
    )


def normalize_point_pdf_to_doc(point: Point, page_height: float) -> Point:
    """Convert a 2D point from PDF coordinates to document presentation space.

    Args:
        point: Point in PDF coordinates.
        page_height: Total vertical height of the page.

    Returns:
        Point in document presentation coordinates.
    """
    return Point(x=point.x, y=page_height - point.y)


def normalize_bbox_doc_to_pdf(bbox: BoundingBox, page_height: float) -> BoundingBox:
    """Convert a bounding box from document space back to PDF coordinates.

    Args:
        bbox: Bounding box in document coordinates.
        page_height: Total vertical height of the page.

    Returns:
        BoundingBox in PDF coordinates.
    """
    y0_pdf = page_height - bbox.y1
    y1_pdf = page_height - bbox.y0
    return BoundingBox(
        x0=min(bbox.x0, bbox.x1),
        y0=min(y0_pdf, y1_pdf),
        x1=max(bbox.x0, bbox.x1),
        y1=max(y0_pdf, y1_pdf),
    )


class SpatialIndex(Generic[T]):
    """2D spatial grid bucket index for fast collision and range queries.

    Divides 2D coordinate space into a uniform grid of cells, mapping items to
    all cells overlapping their bounding box.
    """

    __slots__ = ("_cell_size", "_grid", "_items", "_item_cells")

    def __init__(self, cell_size: float = 64.0) -> None:
        """Initialize spatial index with a grid cell size.

        Args:
            cell_size: Dimension of each square grid cell (must be > 0).
        """
        if cell_size <= 0.0:
            raise SpatialIndexError(f"cell_size must be positive, got {cell_size}")
        self._cell_size = cell_size
        # (cell_x, cell_y) -> list of item_ids
        self._grid: Dict[Tuple[int, int], List[int]] = {}
        # item_id -> (item, BoundingBox)
        self._items: Dict[int, Tuple[T, BoundingBox]] = {}
        # item_id -> set of (cell_x, cell_y)
        self._item_cells: Dict[int, Set[Tuple[int, int]]] = {}

    @property
    def cell_size(self) -> float:
        """Return the grid cell dimension."""
        return self._cell_size

    def _get_cells_for_bbox(self, bbox: BoundingBox) -> Set[Tuple[int, int]]:
        """Compute all grid cell indices intersected by a bounding box."""
        cs = self._cell_size
        min_cx = int(math.floor(bbox.x0 / cs))
        max_cx = int(math.floor(bbox.x1 / cs))
        min_cy = int(math.floor(bbox.y0 / cs))
        max_cy = int(math.floor(bbox.y1 / cs))

        cells: Set[Tuple[int, int]] = set()
        for cx in range(min_cx, max_cx + 1):
            for cy in range(min_cy, max_cy + 1):
                cells.add((cx, cy))
        return cells

    def insert(self, item: T, bbox: BoundingBox) -> None:
        """Insert an item with its associated bounding box into the index.

        Args:
            item: Object to index.
            bbox: Bounding box of the item.
        """
        item_id = id(item)
        if item_id in self._items:
            self.remove(item)

        norm_bbox = bbox.normalized()
        self._items[item_id] = (item, norm_bbox)
        cells = self._get_cells_for_bbox(norm_bbox)
        self._item_cells[item_id] = cells

        for cell in cells:
            if cell not in self._grid:
                self._grid[cell] = []
            self._grid[cell].append(item_id)

    def remove(self, item: T) -> bool:
        """Remove an item from the index.

        Args:
            item: Item to remove.

        Returns:
            bool: True if item was found and removed, False otherwise.
        """
        item_id = id(item)
        if item_id not in self._items:
            return False

        cells = self._item_cells.pop(item_id, set())
        for cell in cells:
            cell_items = self._grid.get(cell)
            if cell_items is not None:
                try:
                    cell_items.remove(item_id)
                    if not cell_items:
                        del self._grid[cell]
                except ValueError:
                    pass

        del self._items[item_id]
        return True

    def update(self, item: T, new_bbox: BoundingBox) -> None:
        """Update the bounding box of an existing indexed item.

        Args:
            item: Item to update.
            new_bbox: New bounding box.
        """
        self.remove(item)
        self.insert(item, new_bbox)

    def query_bbox(self, bbox: BoundingBox) -> List[T]:
        """Find all items whose bounding boxes intersect the query box.

        Args:
            bbox: Query bounding box.

        Returns:
            List of matching items.
        """
        norm_bbox = bbox.normalized()
        cells = self._get_cells_for_bbox(norm_bbox)
        candidate_ids: Set[int] = set()

        for cell in cells:
            cell_items = self._grid.get(cell)
            if cell_items:
                candidate_ids.update(cell_items)

        results: List[T] = []
        for item_id in candidate_ids:
            item_entry = self._items.get(item_id)
            if item_entry is not None:
                item, item_bbox = item_entry
                if item_bbox.intersects(norm_bbox):
                    results.append(item)

        return results

    def query_point(self, point: Point) -> List[T]:
        """Find all items whose bounding box contains the given point.

        Args:
            point: Query point.

        Returns:
            List of items containing the point.
        """
        cx = int(math.floor(point.x / self._cell_size))
        cy = int(math.floor(point.y / self._cell_size))
        cell_items = self._grid.get((cx, cy))
        if not cell_items:
            return []

        results: List[T] = []
        for item_id in cell_items:
            item_entry = self._items.get(item_id)
            if item_entry is not None:
                item, item_bbox = item_entry
                if item_bbox.contains_point(point):
                    results.append(item)
        return results

    def nearest_neighbors(
        self,
        point: Point,
        k: int = 1,
        max_dist: Optional[float] = None,
    ) -> List[Tuple[T, float]]:
        """Find the k nearest items to a query point sorted by Euclidean distance.

        Args:
            point: Target point.
            k: Maximum number of neighbors to return (>= 1).
            max_dist: Optional maximum search radius.

        Returns:
            List of (item, distance) tuples sorted ascending by distance.
        """
        if k < 1:
            return []

        # Distance calculation to box boundary
        distances: List[Tuple[T, float]] = []
        for item, item_bbox in self._items.values():
            d = item_bbox.distance_to_point(point)
            if max_dist is None or d <= max_dist:
                distances.append((item, d))

        distances.sort(key=lambda pair: pair[1])
        return distances[:k]

    def get_bbox(self, item: T) -> Optional[BoundingBox]:
        """Retrieve the bounding box for an indexed item."""
        entry = self._items.get(id(item))
        if entry is None:
            return None
        return entry[1]

    def all_items(self) -> List[T]:
        """Return all indexed items."""
        return [entry[0] for entry in self._items.values()]

    def clear(self) -> None:
        """Clear all contents from the index."""
        self._grid.clear()
        self._items.clear()
        self._item_cells.clear()

    def __len__(self) -> int:
        """Return the number of items in the index."""
        return len(self._items)

    def __contains__(self, item: T) -> bool:
        """Check if an item is present in the index."""
        return id(item) in self._items


__all__ = [
    "normalize_bbox_pdf_to_doc",
    "normalize_point_pdf_to_doc",
    "normalize_bbox_doc_to_pdf",
    "SpatialIndex",
]
