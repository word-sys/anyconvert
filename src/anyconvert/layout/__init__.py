"""Document spatial geometry, clustering, and recursive XY-cut layout analysis."""

from __future__ import annotations

from anyconvert.layout.cluster import (
    TextLine,
    TextWord,
    cluster_characters_to_words,
    cluster_words_to_lines,
)
from anyconvert.layout.spatial import (
    SpatialIndex,
    normalize_bbox_doc_to_pdf,
    normalize_bbox_pdf_to_doc,
    normalize_point_pdf_to_doc,
)
from anyconvert.layout.xycut import (
    CutType,
    LayoutBlock,
    ReadingOrderDAG,
    XYCutNode,
    linearize_reading_order,
    recursive_xy_cut,
)

__all__ = [
    "SpatialIndex",
    "normalize_bbox_pdf_to_doc",
    "normalize_point_pdf_to_doc",
    "normalize_bbox_doc_to_pdf",
    "TextWord",
    "TextLine",
    "cluster_characters_to_words",
    "cluster_words_to_lines",
    "CutType",
    "LayoutBlock",
    "XYCutNode",
    "recursive_xy_cut",
    "linearize_reading_order",
    "ReadingOrderDAG",
]
