"""Document spatial geometry, clustering, layout analysis, and semantic feature detectors."""

from __future__ import annotations

from anyconvert.layout.cluster import (
    TextLine,
    TextWord,
    cluster_characters_to_words,
    cluster_words_to_lines,
)
from anyconvert.layout.flow import (
    PageFlowPartition,
    detect_repeating_headers_footers,
    is_footer_candidate,
    is_header_candidate,
    is_page_number_pattern,
    partition_page_flow,
)
from anyconvert.layout.headings import (
    HeadingLevel,
    classify_headings,
    compute_modal_body_font_size,
)
from anyconvert.layout.lists import (
    BULLET_CHARS,
    detect_list_item,
    process_list_paragraphs,
)
from anyconvert.layout.paragraph import (
    Alignment,
    ParagraphCluster,
    cluster_lines_to_paragraphs,
    detect_alignment,
)
from anyconvert.layout.spatial import (
    SpatialIndex,
    normalize_bbox_doc_to_pdf,
    normalize_bbox_pdf_to_doc,
    normalize_point_pdf_to_doc,
)
from anyconvert.layout.table import (
    TableCellLayout,
    TableLayout,
    TableRowLayout,
    detect_borderless_tables,
    detect_tables_from_vectors,
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
    # Spatial
    "SpatialIndex",
    "normalize_bbox_pdf_to_doc",
    "normalize_point_pdf_to_doc",
    "normalize_bbox_doc_to_pdf",
    # Clustering
    "TextWord",
    "TextLine",
    "cluster_characters_to_words",
    "cluster_words_to_lines",
    # XY-Cut
    "CutType",
    "LayoutBlock",
    "XYCutNode",
    "recursive_xy_cut",
    "linearize_reading_order",
    "ReadingOrderDAG",
    # Paragraph
    "Alignment",
    "ParagraphCluster",
    "detect_alignment",
    "cluster_lines_to_paragraphs",
    # Headings
    "HeadingLevel",
    "compute_modal_body_font_size",
    "classify_headings",
    # Lists
    "BULLET_CHARS",
    "detect_list_item",
    "process_list_paragraphs",
    # Tables
    "TableCellLayout",
    "TableRowLayout",
    "TableLayout",
    "detect_tables_from_vectors",
    "detect_borderless_tables",
    # Flow
    "PageFlowPartition",
    "is_page_number_pattern",
    "is_header_candidate",
    "is_footer_candidate",
    "partition_page_flow",
    "detect_repeating_headers_footers",
]
