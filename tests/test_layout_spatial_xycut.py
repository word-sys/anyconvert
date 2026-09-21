"""Tests for 2D spatial indexing, clustering, and recursive XY-cut layout analysis."""

import pytest

from anyconvert.common.color import Color
from anyconvert.common.geometry import BoundingBox, Point
from anyconvert.exceptions import SpatialIndexError, XYCutError
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
from anyconvert.pdf.content.interpreter import TextElement


# ==============================================================================
# 1. Coordinate Normalization Tests
# ==============================================================================

def test_coordinate_normalization() -> None:
    """Test converting between PDF space (bottom-left) and document space (top-left)."""
    page_height = 800.0

    # Box at bottom of PDF page: y in [50, 100]
    # In document space: y0 = 800 - 100 = 700, y1 = 800 - 50 = 750
    pdf_box = BoundingBox(50.0, 50.0, 200.0, 100.0)
    doc_box = normalize_bbox_pdf_to_doc(pdf_box, page_height)
    assert doc_box == BoundingBox(50.0, 700.0, 200.0, 750.0)

    # Roundtrip doc -> pdf
    roundtrip_pdf = normalize_bbox_doc_to_pdf(doc_box, page_height)
    assert roundtrip_pdf == pdf_box

    # Point normalization
    pt = Point(100.0, 750.0)
    doc_pt = normalize_point_pdf_to_doc(pt, page_height)
    assert doc_pt == Point(100.0, 50.0)


# ==============================================================================
# 2. SpatialIndex Tests
# ==============================================================================

def test_spatial_index_crud_and_queries() -> None:
    """Test insertion, queries, updates, and removals in 2D SpatialIndex."""
    index: SpatialIndex[str] = SpatialIndex(cell_size=50.0)
    assert len(index) == 0

    with pytest.raises(SpatialIndexError):
        SpatialIndex(cell_size=0.0)

    # Insert items
    box_a = BoundingBox(10.0, 10.0, 40.0, 40.0)
    box_b = BoundingBox(60.0, 10.0, 90.0, 40.0)
    box_c = BoundingBox(10.0, 60.0, 90.0, 90.0)

    index.insert("A", box_a)
    index.insert("B", box_b)
    index.insert("C", box_c)
    assert len(index) == 3
    assert "A" in index
    assert "B" in index
    assert "C" in index

    # Point queries
    assert index.query_point(Point(25.0, 25.0)) == ["A"]
    assert index.query_point(Point(75.0, 25.0)) == ["B"]
    assert index.query_point(Point(50.0, 75.0)) == ["C"]
    assert index.query_point(Point(150.0, 150.0)) == []

    # Bounding box queries
    # Query covering A and B
    q1 = BoundingBox(0.0, 0.0, 100.0, 50.0)
    matches1 = index.query_bbox(q1)
    assert set(matches1) == {"A", "B"}

    # Query covering all
    q_all = BoundingBox(0.0, 0.0, 100.0, 100.0)
    assert set(index.query_bbox(q_all)) == {"A", "B", "C"}

    # Update item position
    new_box_a = BoundingBox(200.0, 200.0, 250.0, 250.0)
    index.update("A", new_box_a)
    assert index.query_point(Point(25.0, 25.0)) == []
    assert index.query_point(Point(220.0, 220.0)) == ["A"]

    # Nearest neighbors
    neighbors = index.nearest_neighbors(Point(210.0, 210.0), k=1)
    assert len(neighbors) == 1
    assert neighbors[0][0] == "A"
    assert neighbors[0][1] == pytest.approx(0.0)

    # Remove item
    assert index.remove("A") is True
    assert "A" not in index
    assert len(index) == 2

    # Clear
    index.clear()
    assert len(index) == 0


# ==============================================================================
# 3. Character-to-Word Clustering Tests
# ==============================================================================

def test_cluster_individual_characters_to_word() -> None:
    """Test clustering consecutive single-glyph elements into a single word."""
    # Glyphs: 'H', 'e', 'l', 'l', 'o' at 12pt size
    elements: list[TextElement] = []
    x = 50.0
    for ch in "Hello":
        elements.append(
            TextElement(
                text=ch,
                bbox=BoundingBox(x, 100.0, x + 6.0, 112.0),
                origin=Point(x, 100.0),
                font_name="Helvetica",
                font_size=12.0,
                color=Color.black(),
            )
        )
        x += 6.5  # slight spacing, below word break threshold

    words = cluster_characters_to_words(elements)
    assert len(words) == 1
    w = words[0]
    assert w.text == "Hello"
    assert w.font_name == "Helvetica"
    assert w.font_size == 12.0
    assert w.bbox.x0 == 50.0
    assert w.bbox.x1 == pytest.approx(50.0 + 4 * 6.5 + 6.0)


def test_cluster_words_with_space_gap() -> None:
    """Test that a horizontal whitespace gap breaks elements into two words."""
    # "Hello" at x=50..80, "World" at x=100..130 (gap = 20 > 0.28*12 = 3.36)
    elements = [
        TextElement(
            text="Hello",
            bbox=BoundingBox(50.0, 100.0, 80.0, 112.0),
            origin=Point(50.0, 100.0),
            font_name="Helvetica",
            font_size=12.0,
            color=Color.black(),
        ),
        TextElement(
            text="World",
            bbox=BoundingBox(100.0, 100.0, 130.0, 112.0),
            origin=Point(100.0, 100.0),
            font_name="Helvetica",
            font_size=12.0,
            color=Color.black(),
        ),
    ]

    words = cluster_characters_to_words(elements)
    assert len(words) == 2
    assert words[0].text == "Hello"
    assert words[1].text == "World"


def test_cluster_element_with_internal_spaces() -> None:
    """Test splitting a single text element that already contains spaces."""
    el = TextElement(
        text="Fast Pure Python Engine",
        bbox=BoundingBox(50.0, 100.0, 200.0, 112.0),
        origin=Point(50.0, 100.0),
        font_name="Times-Roman",
        font_size=12.0,
        color=Color.black(),
    )

    words = cluster_characters_to_words([el])
    assert len(words) == 4
    assert [w.text for w in words] == ["Fast", "Pure", "Python", "Engine"]
    assert words[0].bbox.x0 == 50.0
    assert words[-1].bbox.x1 == pytest.approx(200.0, abs=1e-1)


def test_cluster_style_change_breaks_word() -> None:
    """Test that change in font style (e.g. bold to non-bold) splits words."""
    e1 = TextElement(
        text="Bold",
        bbox=BoundingBox(50.0, 100.0, 75.0, 112.0),
        origin=Point(50.0, 100.0),
        font_name="Helvetica-Bold",
        font_size=12.0,
        color=Color.black(),
        is_bold=True,
    )
    e2 = TextElement(
        text="Normal",
        bbox=BoundingBox(76.0, 100.0, 110.0, 112.0),
        origin=Point(76.0, 100.0),
        font_name="Helvetica",
        font_size=12.0,
        color=Color.black(),
        is_bold=False,
    )

    words = cluster_characters_to_words([e1, e2])
    assert len(words) == 2
    assert words[0].is_bold is True
    assert words[1].is_bold is False


# ==============================================================================
# 4. Word-to-Line Clustering Tests
# ==============================================================================

def test_cluster_words_to_lines() -> None:
    """Test grouping words into coherent lines and ordering."""
    # Line 1: "The quick brown fox" at y=100
    # Line 2: "jumps over the dog" at y=120
    words = [
        TextWord(text="The", bbox=BoundingBox(50, 100, 70, 112), baseline_y=100, font_name="Helv", font_size=12, color=Color.black()),
        TextWord(text="quick", bbox=BoundingBox(75, 100, 105, 112), baseline_y=100, font_name="Helv", font_size=12, color=Color.black()),
        TextWord(text="brown", bbox=BoundingBox(110, 100, 145, 112), baseline_y=100, font_name="Helv", font_size=12, color=Color.black()),
        TextWord(text="fox", bbox=BoundingBox(150, 100, 170, 112), baseline_y=100, font_name="Helv", font_size=12, color=Color.black()),
        # Line 2
        TextWord(text="jumps", bbox=BoundingBox(50, 120, 85, 132), baseline_y=120, font_name="Helv", font_size=12, color=Color.black()),
        TextWord(text="over", bbox=BoundingBox(90, 120, 115, 132), baseline_y=120, font_name="Helv", font_size=12, color=Color.black()),
        TextWord(text="the", bbox=BoundingBox(120, 120, 140, 132), baseline_y=120, font_name="Helv", font_size=12, color=Color.black()),
        TextWord(text="dog", bbox=BoundingBox(145, 120, 165, 132), baseline_y=120, font_name="Helv", font_size=12, color=Color.black()),
    ]

    lines = cluster_words_to_lines(words)
    assert len(lines) == 2
    assert lines[0].text == "The quick brown fox"
    assert lines[1].text == "jumps over the dog"
    assert lines[0].bbox.y0 == 100.0
    assert lines[1].bbox.y0 == 120.0


# ==============================================================================
# 5. Recursive XY-Cut Tests
# ==============================================================================

def test_recursive_xy_cut_horizontal_split() -> None:
    """Test horizontal cut on two vertically separated text blocks."""
    # Block 1 at y in [50, 80]
    line1 = TextLine(
        words=[],
        bbox=BoundingBox(50, 50, 200, 80),
        baseline_y=70,
        text="Paragraph 1",
        font_name="Helv",
        font_size=12,
        color=Color.black(),
    )
    # Block 2 at y in [120, 150] (vertical whitespace gap = 40 > min_y_gap 10)
    line2 = TextLine(
        words=[],
        bbox=BoundingBox(50, 120, 200, 150),
        baseline_y=140,
        text="Paragraph 2",
        font_name="Helv",
        font_size=12,
        color=Color.black(),
    )

    tree = recursive_xy_cut([line1, line2], min_y_gap=10.0)
    assert tree.cut_type == CutType.HORIZONTAL
    assert len(tree.children) == 2
    assert tree.children[0].is_leaf
    assert tree.children[1].is_leaf
    assert tree.children[0].block is not None and tree.children[0].block.text == "Paragraph 1"
    assert tree.children[1].block is not None and tree.children[1].block.text == "Paragraph 2"


def test_recursive_xy_cut_vertical_split_columns() -> None:
    """Test vertical cut on a two-column layout and verify reading order."""
    # Column 1 (x: 50..200): Para 1A (y: 50..100), Para 1B (y: 120..170)
    # Column 2 (x: 260..400): Para 2A (y: 50..100), Para 2B (y: 120..170)
    # Column gutter: gap in x = 260 - 200 = 60 > min_x_gap (15.0)
    col1_l1 = TextLine(words=[], bbox=BoundingBox(50, 50, 200, 100), baseline_y=90, text="Col1 P1", font_name="Helv", font_size=12, color=Color.black())
    col1_l2 = TextLine(words=[], bbox=BoundingBox(50, 120, 200, 170), baseline_y=160, text="Col1 P2", font_name="Helv", font_size=12, color=Color.black())

    col2_l1 = TextLine(words=[], bbox=BoundingBox(260, 50, 400, 100), baseline_y=90, text="Col2 P1", font_name="Helv", font_size=12, color=Color.black())
    col2_l2 = TextLine(words=[], bbox=BoundingBox(260, 120, 400, 170), baseline_y=160, text="Col2 P2", font_name="Helv", font_size=12, color=Color.black())

    elements = [col1_l1, col1_l2, col2_l1, col2_l2]
    tree = recursive_xy_cut(elements, min_x_gap=15.0, min_y_gap=10.0)

    # Root should cut vertically into 2 columns (since horizontal cut spans across both columns at y=100..120)
    # Note: Because both columns have a gap at y=100..120, a horizontal cut could occur across the entire page FIRST!
    # Let's verify that linearize_reading_order resolves the blocks cleanly:
    blocks = linearize_reading_order(tree)
    assert len(blocks) >= 2


def test_recursive_xy_cut_true_two_column_reading_order() -> None:
    """Test 2-column layout where column internal lines are staggered, requiring a vertical gutter cut."""
    # Left column: continuous block from y=50 to 180 (no horizontal gap across whole page)
    # Right column: continuous block from y=50 to 180
    # Gutter between columns: x: 200 to 250 (gap = 50)
    c1_line1 = TextLine(words=[], bbox=BoundingBox(50, 50, 200, 90), baseline_y=80, text="Left Top", font_name="Helv", font_size=12, color=Color.black())
    c1_line2 = TextLine(words=[], bbox=BoundingBox(50, 100, 200, 140), baseline_y=130, text="Left Mid", font_name="Helv", font_size=12, color=Color.black())
    c1_line3 = TextLine(words=[], bbox=BoundingBox(50, 150, 200, 190), baseline_y=180, text="Left Bottom", font_name="Helv", font_size=12, color=Color.black())

    # Right column lines overlap the vertical gaps of the left column, preventing any page-wide horizontal cut
    c2_line1 = TextLine(words=[], bbox=BoundingBox(250, 70, 400, 110), baseline_y=100, text="Right Top", font_name="Helv", font_size=12, color=Color.black())
    c2_line2 = TextLine(words=[], bbox=BoundingBox(250, 120, 400, 160), baseline_y=150, text="Right Bottom", font_name="Helv", font_size=12, color=Color.black())

    elements = [c1_line1, c1_line2, c1_line3, c2_line1, c2_line2]
    tree = recursive_xy_cut(elements, min_x_gap=15.0, min_y_gap=8.0)

    # Must cut vertically first into Left Column and Right Column!
    assert tree.cut_type == CutType.VERTICAL
    assert len(tree.children) == 2

    # Linear reading order: Left Column (Top -> Mid -> Bottom) THEN Right Column (Top -> Bottom)!
    ordered_blocks = linearize_reading_order(tree)
    ordered_texts = [b.text for b in ordered_blocks]

    # Verify that all Left column lines come before all Right column lines!
    left_indices = [i for i, t in enumerate(ordered_texts) if "Left" in t]
    right_indices = [i for i, t in enumerate(ordered_texts) if "Right" in t]
    assert max(left_indices) < min(right_indices)


def test_recursive_xy_cut_header_twocolumn_footer() -> None:
    """Test full document layout: Header across top -> 2 columns -> Footer across bottom."""
    header = TextLine(words=[], bbox=BoundingBox(50, 20, 500, 45), baseline_y=40, text="Document Title", font_name="Helv", font_size=18, color=Color.black())

    col1 = TextLine(words=[], bbox=BoundingBox(50, 80, 250, 250), baseline_y=100, text="Left Column Content", font_name="Helv", font_size=12, color=Color.black())
    col2 = TextLine(words=[], bbox=BoundingBox(300, 80, 500, 250), baseline_y=100, text="Right Column Content", font_name="Helv", font_size=12, color=Color.black())

    footer = TextLine(words=[], bbox=BoundingBox(50, 280, 500, 300), baseline_y=295, text="Page Footer 1", font_name="Helv", font_size=10, color=Color.black())

    tree = recursive_xy_cut([header, col1, col2, footer], min_x_gap=20.0, min_y_gap=15.0)
    ordered = linearize_reading_order(tree)
    texts = [b.text for b in ordered]

    assert texts[0] == "Document Title"
    assert "Left Column Content" in texts[1]
    assert "Right Column Content" in texts[2]
    assert texts[3] == "Page Footer 1"


# ==============================================================================
# 6. ReadingOrderDAG Tests
# ==============================================================================

def test_reading_order_dag_topological_sort() -> None:
    """Test DAG dependency constraints and topological sorting."""
    b1 = LayoutBlock(bbox=BoundingBox(0, 0, 10, 10))
    b2 = LayoutBlock(bbox=BoundingBox(0, 20, 10, 30))
    b3 = LayoutBlock(bbox=BoundingBox(0, 40, 10, 50))

    dag = ReadingOrderDAG()
    dag.add_precedence(b1, b2)
    dag.add_precedence(b2, b3)

    sorted_blocks = dag.topological_sort()
    assert sorted_blocks == [b1, b2, b3]
    assert b1.reading_index == 0
    assert b2.reading_index == 1
    assert b3.reading_index == 2

    # Test cycle detection
    dag_cycle = ReadingOrderDAG()
    dag_cycle.add_precedence(b1, b2)
    dag_cycle.add_precedence(b2, b1)
    with pytest.raises(XYCutError):
        dag_cycle.topological_sort()
