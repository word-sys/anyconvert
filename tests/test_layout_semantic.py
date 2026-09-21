"""Tests for semantic feature detectors: paragraphs, headings, lists, tables, and flow."""

import pytest

from anyconvert.common.color import Color
from anyconvert.common.geometry import BoundingBox, Point
from anyconvert.layout.cluster import TextLine, TextWord
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
from anyconvert.layout.table import (
    TableCellLayout,
    TableLayout,
    TableRowLayout,
    detect_borderless_tables,
    detect_tables_from_vectors,
)
from anyconvert.pdf.content.interpreter import VectorElement


# ==============================================================================
# Helper to create simple TextLines
# ==============================================================================

def make_line(
    text: str,
    x0: float,
    y0: float,
    width: float = 200.0,
    height: float = 12.0,
    font_size: float = 11.0,
    is_bold: bool = False,
    is_italic: bool = False,
) -> TextLine:
    words = []
    x = x0
    tokens = text.split()
    for tok in tokens:
        w_len = len(tok) * 6.0
        words.append(
            TextWord(
                text=tok,
                bbox=BoundingBox(x, y0, x + w_len, y0 + height),
                baseline_y=y0 + height * 0.8,
                font_name="Helvetica",
                font_size=font_size,
                color=Color.black(),
                is_bold=is_bold,
                is_italic=is_italic,
            )
        )
        x += w_len + 4.0

    return TextLine(
        words=words,
        bbox=BoundingBox(x0, y0, x0 + width, y0 + height),
        baseline_y=y0 + height * 0.8,
        text=text,
        font_name="Helvetica",
        font_size=font_size,
        color=Color.black(),
        is_bold=is_bold,
        is_italic=is_italic,
    )


# ==============================================================================
# 1. Paragraph Grouping and Alignment Tests
# ==============================================================================

def test_paragraph_alignment_detection() -> None:
    """Test left, right, center, and justified paragraph alignments."""
    c_x0 = 50.0
    c_x1 = 450.0

    # Left aligned lines
    left_lines = [
        make_line("Line 1 starts left", 50.0, 100.0, width=300.0),
        make_line("Line 2 starts left too", 50.0, 115.0, width=250.0),
    ]
    assert detect_alignment(left_lines, c_x0, c_x1) == Alignment.LEFT

    # Right aligned lines
    right_lines = [
        make_line("Right aligned 1", 250.0, 100.0, width=200.0),  # x1 = 450
        make_line("Right 2", 300.0, 115.0, width=150.0),          # x1 = 450
    ]
    assert detect_alignment(right_lines, c_x0, c_x1) == Alignment.RIGHT

    # Centered lines (center at 250.0)
    center_lines = [
        make_line("Centered Line 1", 150.0, 100.0, width=200.0),  # center = 250
        make_line("Centered Line 2", 175.0, 115.0, width=150.0),  # center = 250
    ]
    assert detect_alignment(center_lines, c_x0, c_x1) == Alignment.CENTER

    # Justified lines (both left and right align across lines)
    justified_lines = [
        make_line("Justified line one text", 50.0, 100.0, width=400.0),  # x1 = 450
        make_line("Justified line two text", 50.0, 115.0, width=400.0),  # x1 = 450
        make_line("Last line short", 50.0, 130.0, width=150.0),
    ]
    assert detect_alignment(justified_lines, c_x0, c_x1) == Alignment.JUSTIFIED


def test_cluster_lines_to_paragraphs_spacing_and_indent() -> None:
    """Test clustering lines into distinct paragraphs based on line gaps and indents."""
    # Para 1: 2 lines with normal 3pt gap
    # Para 2: follows after 20pt gap, with a 15pt first-line indent
    lines = [
        make_line("First paragraph line one.", 50.0, 100.0, width=300.0, height=12.0),
        make_line("First paragraph line two.", 50.0, 115.0, width=280.0, height=12.0),
        # Gap of 20pt (147 - 127 = 20)
        make_line("Second paragraph line one indented.", 65.0, 147.0, width=285.0, height=12.0),
        make_line("Second paragraph line two.", 50.0, 162.0, width=280.0, height=12.0),
    ]

    container = BoundingBox(50.0, 90.0, 450.0, 300.0)
    paragraphs = cluster_lines_to_paragraphs(lines, container_bbox=container)

    assert len(paragraphs) == 2
    assert paragraphs[0].lines[0].text == "First paragraph line one."
    assert paragraphs[0].lines[1].text == "First paragraph line two."
    assert paragraphs[1].lines[0].text == "Second paragraph line one indented."
    assert paragraphs[1].indent_first_line == pytest.approx(15.0)
    assert paragraphs[1].space_before == pytest.approx(20.0)


# ==============================================================================
# 2. Heading Classification Tests
# ==============================================================================

def test_heading_classification() -> None:
    """Test statistical heading detection (H1-H5) vs body text."""
    # Modal body text is 11pt
    body_p1 = ParagraphCluster(
        lines=[
            make_line("This is standard body paragraph text spanning multiple lines.", 50, 200, font_size=11.0),
            make_line("It continues discussing the document details in depth.", 50, 215, font_size=11.0),
        ],
        bbox=BoundingBox(50, 200, 400, 227),
    )
    body_p2 = ParagraphCluster(
        lines=[
            make_line("Another body paragraph with typical character counts.", 50, 240, font_size=11.0),
            make_line("Maintains the 11pt dominant font size across the page.", 50, 255, font_size=11.0),
        ],
        bbox=BoundingBox(50, 240, 400, 267),
    )

    # H1: 24pt title (24 / 11 = 2.18 >= 1.6)
    title_p = ParagraphCluster(
        lines=[make_line("Enterprise Conversion Engine", 50, 50, font_size=24.0, is_bold=True)],
        bbox=BoundingBox(50, 50, 400, 80),
    )

    # H2: 16pt subtitle (16 / 11 = 1.45 >= 1.35)
    section_p = ParagraphCluster(
        lines=[make_line("Architecture Overview", 50, 100, font_size=16.0, is_bold=True)],
        bbox=BoundingBox(50, 100, 300, 120),
    )

    # H3: 13.5pt section (13.5 / 11 = 1.22 >= 1.18)
    sub_p = ParagraphCluster(
        lines=[make_line("1.1 Document Processing Pipeline", 50, 140, font_size=13.5, is_bold=True)],
        bbox=BoundingBox(50, 140, 300, 156),
    )

    # H4: 12pt bold line (12 / 11 = 1.09 >= 1.05 and is_bold)
    subsub_p = ParagraphCluster(
        lines=[make_line("Component Specifications", 50, 170, font_size=12.0, is_bold=True)],
        bbox=BoundingBox(50, 170, 250, 184),
    )

    paragraphs = [title_p, section_p, sub_p, subsub_p, body_p1, body_p2]

    modal_size = compute_modal_body_font_size(paragraphs)
    assert modal_size == 11.0

    classify_headings(paragraphs, body_size=modal_size)

    assert title_p.heading_level == HeadingLevel.H1.value
    assert section_p.heading_level == HeadingLevel.H2.value
    assert sub_p.heading_level == HeadingLevel.H3.value
    assert subsub_p.heading_level == HeadingLevel.H4.value
    assert body_p1.heading_level is None
    assert body_p2.heading_level is None


# ==============================================================================
# 3. List and Bullet Detection Tests
# ==============================================================================

def test_detect_list_item_bullets() -> None:
    """Test detecting various bullet characters."""
    for char in ["\u2022", "-", "*", "\u25cf", "\u2713"]:
        text = f"{char} Important bullet point"
        res = detect_list_item(text, indent=50.0, base_indent=50.0)
        assert res is not None
        marker, content, level = res
        assert marker == char
        assert content == "Important bullet point"
        assert level == 0


def test_detect_list_item_numbering() -> None:
    """Test detecting numbered list items across formats."""
    # Arabic
    res1 = detect_list_item("1. First item", indent=50.0, base_indent=50.0)
    assert res1 == ("1.", "First item", 0)

    res2 = detect_list_item("2) Second item", indent=50.0, base_indent=50.0)
    assert res2 == ("2)", "Second item", 0)

    # Alphabetic
    res3 = detect_list_item("(a) Sub-clause A", indent=70.0, base_indent=50.0)
    assert res3 is not None
    assert res3[0] == "(a)"
    assert res3[1] == "Sub-clause A"
    assert res3[2] == 1  # 20pt delta / 18 = level 1

    # Roman
    res4 = detect_list_item("iv. Roman item", indent=90.0, base_indent=50.0)
    assert res4 is not None
    assert res4[0] == "iv."
    assert res4[2] == 2  # 40pt delta / 18 = level 2


def test_process_list_paragraphs() -> None:
    """Test assigning list_marker and list_level to paragraphs in-place."""
    p1 = ParagraphCluster(lines=[make_line("• Item 1", 50, 100)], bbox=BoundingBox(50, 100, 200, 112), indent_left=50.0)
    p2 = ParagraphCluster(lines=[make_line("• Item 2 nested", 70, 120)], bbox=BoundingBox(70, 120, 200, 132), indent_left=70.0)
    p3 = ParagraphCluster(lines=[make_line("Regular body text without bullet", 50, 140)], bbox=BoundingBox(50, 140, 250, 152), indent_left=50.0)

    process_list_paragraphs([p1, p2, p3])

    assert p1.list_marker == "•"
    assert p1.list_level == 0
    assert p2.list_marker == "•"
    assert p2.list_level == 1
    assert p3.list_marker is None
    assert p3.list_level == 0


# ==============================================================================
# 4. Table Detection Tests
# ==============================================================================

def test_detect_tables_from_vectors_2x2_grid() -> None:
    """Test detecting a 2x2 grid table from horizontal and vertical vector rulings."""
    # 3 horizontal lines at y = 100, 150, 200 spanning x in [50, 250]
    # 3 vertical lines at x = 50, 150, 250 spanning y in [100, 200]
    h1 = VectorElement(svg_path="", bbox=BoundingBox(50, 99.5, 250, 100.5), stroke_width=1.0)
    h2 = VectorElement(svg_path="", bbox=BoundingBox(50, 149.5, 250, 150.5), stroke_width=1.0)
    h3 = VectorElement(svg_path="", bbox=BoundingBox(50, 199.5, 250, 200.5), stroke_width=1.0)

    v1 = VectorElement(svg_path="", bbox=BoundingBox(49.5, 100, 50.5, 200), stroke_width=1.0)
    v2 = VectorElement(svg_path="", bbox=BoundingBox(149.5, 100, 150.5, 200), stroke_width=1.0)
    v3 = VectorElement(svg_path="", bbox=BoundingBox(249.5, 100, 250.5, 200), stroke_width=1.0)

    # 4 text lines, one in each cell:
    # Cell (0, 0): x in [50, 150], y in [100, 150]
    # Cell (0, 1): x in [150, 250], y in [100, 150]
    # Cell (1, 0): x in [50, 150], y in [150, 200]
    # Cell (1, 1): x in [150, 250], y in [150, 200]
    l00 = make_line("Cell A1", 60, 120, width=60)
    l01 = make_line("Cell B1", 160, 120, width=60)
    l10 = make_line("Cell A2", 60, 170, width=60)
    l11 = make_line("Cell B2", 160, 170, width=60)

    tables = detect_tables_from_vectors(
        vectors=[h1, h2, h3, v1, v2, v3],
        lines=[l00, l01, l10, l11],
    )

    assert len(tables) == 1
    tbl = tables[0]
    assert tbl.num_rows == 2
    assert tbl.num_cols == 2
    assert tbl.has_borders is True

    # Validate cell text mapping
    assert tbl.rows[0].cells[0].text == "Cell A1"
    assert tbl.rows[0].cells[1].text == "Cell B1"
    assert tbl.rows[1].cells[0].text == "Cell A2"
    assert tbl.rows[1].cells[1].text == "Cell B2"


def test_detect_tables_from_vectors_colspan() -> None:
    """Test detecting table cell with colspan where an inner vertical border is omitted."""
    # Top row has no middle vertical border at x=150: spans across both columns (colspan=2)
    # Bottom row has middle vertical border: two cells
    h1 = VectorElement(svg_path="", bbox=BoundingBox(50, 99.5, 250, 100.5))
    h2 = VectorElement(svg_path="", bbox=BoundingBox(50, 149.5, 250, 150.5))
    h3 = VectorElement(svg_path="", bbox=BoundingBox(50, 199.5, 250, 200.5))

    v1 = VectorElement(svg_path="", bbox=BoundingBox(49.5, 100, 50.5, 200))
    v2_bottom_only = VectorElement(svg_path="", bbox=BoundingBox(149.5, 150, 150.5, 200))  # Only in row 1
    v3 = VectorElement(svg_path="", bbox=BoundingBox(249.5, 100, 250.5, 200))

    tables = detect_tables_from_vectors(
        vectors=[h1, h2, h3, v1, v2_bottom_only, v3],
        lines=[],
    )

    assert len(tables) == 1
    tbl = tables[0]
    # Row 0 should have 1 cell with col_span = 2
    assert len(tbl.rows[0].cells) == 1
    assert tbl.rows[0].cells[0].col_span == 2
    # Row 1 should have 2 cells with col_span = 1
    assert len(tbl.rows[1].cells) == 2
    assert tbl.rows[1].cells[0].col_span == 1
    assert tbl.rows[1].cells[1].col_span == 1


def test_detect_borderless_table() -> None:
    """Test detecting borderless table with aligned multi-column text."""
    # 3 rows with 3 aligned columns:
    # Col 0 at x=50, Col 1 at x=150, Col 2 at x=280
    r1 = make_line("Item Cost Quantity", 50, 100)
    # Ensure words have distinct positions
    r1.words = [
        TextWord("Item", BoundingBox(50, 100, 80, 112), 110, "H", 10, Color.black()),
        TextWord("Cost", BoundingBox(150, 100, 180, 112), 110, "H", 10, Color.black()),
        TextWord("Quantity", BoundingBox(280, 100, 330, 112), 110, "H", 10, Color.black()),
    ]
    r2 = make_line("Apple $1.50 10", 50, 120)
    r2.words = [
        TextWord("Apple", BoundingBox(50, 120, 85, 132), 130, "H", 10, Color.black()),
        TextWord("$1.50", BoundingBox(150, 120, 185, 132), 130, "H", 10, Color.black()),
        TextWord("10", BoundingBox(280, 120, 295, 132), 130, "H", 10, Color.black()),
    ]
    r3 = make_line("Orange $2.00 5", 50, 140)
    r3.words = [
        TextWord("Orange", BoundingBox(50, 140, 90, 152), 150, "H", 10, Color.black()),
        TextWord("$2.00", BoundingBox(150, 140, 185, 152), 150, "H", 10, Color.black()),
        TextWord("5", BoundingBox(280, 140, 290, 152), 150, "H", 10, Color.black()),
    ]

    tables = detect_borderless_tables([r1, r2, r3], min_columns=3, min_rows=3)
    assert len(tables) == 1
    tbl = tables[0]
    assert tbl.num_rows == 3
    assert tbl.num_cols == 3
    assert tbl.has_borders is False
    assert tbl.rows[0].cells[0].text == "Item"
    assert tbl.rows[0].cells[1].text == "Cost"
    assert tbl.rows[0].cells[2].text == "Quantity"
    assert tbl.rows[1].cells[0].text == "Apple"


# ==============================================================================
# 5. Flow and Header/Footer Partitioning Tests
# ==============================================================================

def test_page_number_pattern_matching() -> None:
    """Test standard page number pattern detector."""
    assert is_page_number_pattern("1") is True
    assert is_page_number_pattern("42") is True
    assert is_page_number_pattern("- 5 -") is True
    assert is_page_number_pattern("Page 1") is True
    assert is_page_number_pattern("Page 3 of 10") is True
    assert is_page_number_pattern("2 / 8") is True
    assert is_page_number_pattern("iv") is True
    assert is_page_number_pattern("Enterprise Architecture") is False


def test_partition_page_flow_headers_footers() -> None:
    """Test isolating running headers, footers, and page numbers from body content."""
    page_height = 792.0

    header = make_line("Annual Financial Report 2026", 50, 35)        # y <= 72 (top margin)
    body1 = make_line("The fiscal year ended with strong growth.", 50, 150)
    body2 = make_line("Operating margins expanded significantly.", 50, 200)
    page_num = make_line("Page 1 of 5", 250, 750)                   # y >= 792 - 72 (bottom margin)
    footer = make_line("Confidential - Internal Use Only", 50, 765)  # y >= 720

    partition = partition_page_flow(
        lines=[header, body1, body2, page_num, footer],
        page_height=page_height,
        top_margin=72.0,
        bottom_margin=72.0,
    )

    assert len(partition.headers) == 1
    assert partition.headers[0].text == "Annual Financial Report 2026"

    assert len(partition.footers) == 1
    assert partition.footers[0].text == "Confidential - Internal Use Only"

    assert len(partition.page_numbers) == 1
    assert partition.page_numbers[0].text == "Page 1 of 5"

    assert len(partition.body_lines) == 2
    assert partition.body_lines[0].text == "The fiscal year ended with strong growth."
    assert partition.body_lines[1].text == "Operating margins expanded significantly."


def test_detect_repeating_headers_footers_multi_page() -> None:
    """Test detecting repeating headers across multiple pages."""
    p1_lines = [
        make_line("Running Header Company Inc", 50, 30),
        make_line("Page 1 content body.", 50, 200),
        make_line("Confidential Footer", 50, 750),
    ]
    p2_lines = [
        make_line("Running Header Company Inc", 50, 30),
        make_line("Page 2 content body.", 50, 200),
        make_line("Confidential Footer", 50, 750),
    ]

    rep_headers, rep_footers = detect_repeating_headers_footers(
        pages_lines=[p1_lines, p2_lines],
        page_height=792.0,
    )

    assert "Running Header Company Inc" in rep_headers
    assert "Confidential Footer" in rep_footers
