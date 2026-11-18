"""Tests for pure-Python Plaintext emitters (Flow and Canvas modes)."""

import pathlib
import pytest

from anyconvert.common.color import Color
from anyconvert.common.geometry import BoundingBox
from anyconvert.emitters.base import ConversionMode
from anyconvert.emitters.txt import (
    TxtCanvasEmitter,
    TxtEmitter,
    TxtFlowEmitter,
)
from anyconvert.exceptions import SerializationError
from anyconvert.ir.model import (
    Alignment,
    DocumentIR,
    DocumentPage,
    HeadingLevel,
    ImageBlock,
    PageHeaderFooter,
    Paragraph,
    Table,
    TableCell,
    TableRow,
    TextRun,
    VectorBlock,
)


# ==============================================================================
# TxtFlowEmitter Tests
# ==============================================================================

def test_txt_flow_emitter_headings_and_runs() -> None:
    """Test TxtFlowEmitter markdown headings, inline styling, and lists."""
    h1 = Paragraph(
        runs=[TextRun("Document Title", "Helvetica", 24.0, Color.black())],
        heading_level=HeadingLevel.H1,
    )
    h2 = Paragraph(
        runs=[TextRun("Section 1", "Helvetica", 18.0, Color.black())],
        heading_level=HeadingLevel.H2,
    )

    body = Paragraph(
        runs=[
            TextRun("Normal text with ", "Helvetica", 11.0, Color.black()),
            TextRun("bold", "Helvetica", 11.0, Color.black(), is_bold=True),
            TextRun(" and ", "Helvetica", 11.0, Color.black()),
            TextRun("italic", "Helvetica", 11.0, Color.black(), is_italic=True),
            TextRun(" and ", "Helvetica", 11.0, Color.black()),
            TextRun("both", "Helvetica", 11.0, Color.black(), is_bold=True, is_italic=True),
            TextRun(" and ", "Helvetica", 11.0, Color.black()),
            TextRun("deleted", "Helvetica", 11.0, Color.black(), is_strikethrough=True),
            TextRun(".", "Helvetica", 11.0, Color.black()),
        ]
    )

    bullet1 = Paragraph(
        runs=[TextRun("First bullet", "Helvetica", 11.0, Color.black())],
        list_marker="•",
        list_level=0,
    )
    bullet2 = Paragraph(
        runs=[TextRun("Nested bullet", "Helvetica", 11.0, Color.black())],
        list_marker="•",
        list_level=1,
    )
    ordered = Paragraph(
        runs=[TextRun("Numbered step", "Helvetica", 11.0, Color.black())],
        list_marker="1.",
        list_level=0,
    )

    page = DocumentPage(
        page_number=1,
        width=612.0,
        height=792.0,
        blocks=[h1, h2, body, bullet1, bullet2, ordered],
    )
    doc_ir = DocumentIR(pages=[page])

    emitter = TxtFlowEmitter()
    txt_bytes = emitter.emit(doc_ir)
    text = txt_bytes.decode("utf-8")

    assert "# Document Title" in text
    assert "## Section 1" in text
    assert "**bold**" in text
    assert "*italic*" in text
    assert "***both***" in text
    assert "~~deleted~~" in text
    assert "- First bullet" in text
    assert "  - Nested bullet" in text
    assert "1. Numbered step" in text


def test_txt_flow_emitter_tables_and_images() -> None:
    """Test TxtFlowEmitter markdown table formatting and image tokens."""
    c1 = TableCell(content=[Paragraph(runs=[TextRun("Language", "Helvetica", 10.0, Color.black())])], width=100.0)
    c2 = TableCell(content=[Paragraph(runs=[TextRun("Status", "Helvetica", 10.0, Color.black())])], width=100.0)
    c3 = TableCell(content=[Paragraph(runs=[TextRun("Python", "Helvetica", 10.0, Color.black())])], width=100.0)
    c4 = TableCell(content=[Paragraph(runs=[TextRun("Passed", "Helvetica", 10.0, Color.black())])], width=100.0)

    row1 = TableRow(cells=[c1, c2], height=20.0, is_header=True)
    row2 = TableRow(cells=[c3, c4], height=20.0, is_header=False)
    table = Table(rows=[row1, row2], col_widths=[100.0, 100.0], alignment=Alignment.CENTER)

    img = ImageBlock(png_bytes=b"FAKE_PNG", bbox=BoundingBox(0, 0, 50, 50), alt_text="Test Logo")

    header = PageHeaderFooter(content=[Paragraph(runs=[TextRun("Doc Header", "Helvetica", 9.0, Color.black())])])
    footer = PageHeaderFooter(content=[Paragraph(runs=[TextRun("Doc Footer", "Helvetica", 9.0, Color.black())])], is_footer=True)

    page1 = DocumentPage(page_number=1, width=612.0, height=792.0, blocks=[table, img], header=header, footer=footer)
    page2 = DocumentPage(page_number=2, width=612.0, height=792.0, blocks=[Paragraph(runs=[TextRun("Page 2", "H", 12.0, Color.black())])])

    doc_ir = DocumentIR(pages=[page1, page2])

    emitter = TxtFlowEmitter()
    text = emitter.emit(doc_ir).decode("utf-8")

    assert "| Language | Status |" in text
    assert "| :------: | :----: |" in text
    assert "| Python   | Passed |" in text
    assert "![Test Logo](image_1.png)" in text
    assert "> Doc Header" in text
    assert "> Doc Footer" in text
    assert "---" in text  # Multi-page break
    assert "Page 2" in text


def test_txt_flow_emitter_empty_doc_raises() -> None:
    """Test that TxtFlowEmitter raises SerializationError when given empty pages."""
    doc_ir = DocumentIR(pages=[])
    emitter = TxtFlowEmitter()
    with pytest.raises(SerializationError):
        emitter.emit(doc_ir)


# ==============================================================================
# TxtCanvasEmitter Tests
# ==============================================================================

def test_txt_canvas_emitter_grid_placement() -> None:
    """Test TxtCanvasEmitter 2D character matrix spatial positioning."""
    # char_width = 6 pt, line_height = 12 pt
    # x = 60 pt -> col 10
    # y = 24 pt -> row 2
    para = Paragraph(
        runs=[TextRun("Spatial Title", "Helvetica", 12.0, Color.black())],
        bbox=BoundingBox(60.0, 24.0, 200.0, 36.0),
    )

    # Table outline
    c1 = TableCell(content=[Paragraph(runs=[TextRun("Cell1", "H", 10.0, Color.black())])], width=60.0)
    c2 = TableCell(content=[Paragraph(runs=[TextRun("Cell2", "H", 10.0, Color.black())])], width=60.0)
    row = TableRow(cells=[c1, c2], height=24.0)
    tbl = Table(rows=[row], col_widths=[60.0, 60.0], bbox=BoundingBox(60.0, 60.0, 240.0, 108.0))

    img = ImageBlock(png_bytes=b"PNG", bbox=BoundingBox(60.0, 144.0, 180.0, 192.0), alt_text="Plot")

    page = DocumentPage(
        page_number=1,
        width=360.0,
        height=360.0,
        blocks=[para, tbl, img],
    )
    doc_ir = DocumentIR(pages=[page])

    emitter = TxtCanvasEmitter(char_width_pt=6.0, line_height_pt=12.0)
    text = emitter.emit(doc_ir).decode("utf-8")

    assert "Spatial Title" in text
    assert "┌" in text and "┐" in text and "└" in text and "┘" in text
    assert "┬" in text and "┴" in text
    assert "─" in text and "│" in text
    assert "Cell1" in text and "Cell2" in text
    assert "[ Plot ]" in text  # Image placeholder

    # Verify optional ASCII fallback mode
    ascii_emitter = TxtCanvasEmitter(char_width_pt=6.0, line_height_pt=12.0, unicode_boxes=False)
    ascii_text = ascii_emitter.emit(doc_ir).decode("utf-8")
    assert "+" in ascii_text
    assert "-" in ascii_text
    assert "|" in ascii_text
    assert "[ Plot ]" in ascii_text


def test_txt_canvas_unicode_table_dividers_and_colspan() -> None:
    """Test Unicode T-junctions, row dividers, and col_span inside canvas tables."""
    hdr = TableCell(
        content=[Paragraph(runs=[TextRun("Quarterly Metrics", "H", 10.0, Color.black())])],
        col_span=2,
        width=180.0,
    )
    r_hdr = TableRow(cells=[hdr], is_header=True)

    c1 = TableCell(content=[Paragraph(runs=[TextRun("Revenue", "H", 10.0, Color.black())])], width=90.0)
    c2 = TableCell(content=[Paragraph(runs=[TextRun("$4.2B", "H", 10.0, Color.black())])], width=90.0)
    r_data1 = TableRow(cells=[c1, c2])

    c3 = TableCell(content=[Paragraph(runs=[TextRun("Margin", "H", 10.0, Color.black())])], width=90.0)
    c4 = TableCell(content=[Paragraph(runs=[TextRun("28%", "H", 10.0, Color.black())])], width=90.0)
    r_data2 = TableRow(cells=[c3, c4])

    tbl = Table(
        rows=[r_hdr, r_data1, r_data2],
        col_widths=[90.0, 90.0],
        bbox=BoundingBox(12.0, 12.0, 210.0, 108.0),
    )
    page = DocumentPage(page_number=1, width=300.0, height=200.0, blocks=[tbl])
    text = (
        TxtCanvasEmitter(char_width_pt=6.0, line_height_pt=12.0)
        .emit(DocumentIR(pages=[page]))
        .decode("utf-8")
    )

    assert "Quarterly Metrics" in text
    assert "Revenue" in text and "$4.2B" in text
    assert "Margin" in text and "28%" in text
    assert "├" in text and "┤" in text
    assert "┬" in text and "┴" in text
    assert "┼" in text


def test_txt_canvas_vector_lines_boxes_and_diagonals() -> None:
    """Test VectorBlock horizontal/vertical junctions, SVG rectangles, and diagonal strokes."""
    # Intersecting horizontal and vertical vector lines creating a cross (+)
    h_line = VectorBlock(
        svg_path="M 30 60 L 150 60",
        bbox=BoundingBox(30.0, 60.0, 150.0, 61.0),
    )
    v_line = VectorBlock(
        svg_path="M 90 24 L 90 96",
        bbox=BoundingBox(90.0, 24.0, 91.0, 96.0),
    )
    # Closed SVG rectangle
    rect_vec = VectorBlock(
        svg_path="M 180 24 L 270 24 L 270 72 L 180 72 Z",
        bbox=BoundingBox(180.0, 24.0, 270.0, 72.0),
    )
    # Diagonal slash line
    diag_vec = VectorBlock(
        svg_path="M 30 120 L 78 168",
        bbox=BoundingBox(30.0, 120.0, 78.0, 168.0),
    )
    page = DocumentPage(
        page_number=1,
        width=360.0,
        height=240.0,
        blocks=[h_line, v_line, rect_vec, diag_vec],
    )
    text = TxtCanvasEmitter(char_width_pt=6.0, line_height_pt=12.0).emit(DocumentIR(pages=[page])).decode("utf-8")

    assert "─" in text
    assert "│" in text
    assert "┼" in text  # Intersection of h_line and v_line
    assert "┌" in text and "┐" in text and "└" in text and "┘" in text  # Closed rect_vec
    assert "\\" in text  # Top-down positive slope diagonal line


def test_txt_canvas_emitter_multi_page() -> None:
    """Test TxtCanvasEmitter multi-page separation via form feed."""
    p1 = DocumentPage(page_number=1, width=200, height=200, blocks=[Paragraph(runs=[TextRun("P1", "H", 10, Color.black())])])
    p2 = DocumentPage(page_number=2, width=200, height=200, blocks=[Paragraph(runs=[TextRun("P2", "H", 10, Color.black())])])
    doc_ir = DocumentIR(pages=[p1, p2])

    emitter = TxtCanvasEmitter()
    text = emitter.emit(doc_ir).decode("utf-8")

    assert "\x0c" in text  # Form feed
    assert "P1" in text
    assert "P2" in text


def test_txt_canvas_emitter_empty_doc_raises() -> None:
    """Test that TxtCanvasEmitter raises SerializationError when given empty pages."""
    doc_ir = DocumentIR(pages=[])
    emitter = TxtCanvasEmitter()
    with pytest.raises(SerializationError):
        emitter.emit(doc_ir)


# ==============================================================================
# Unified TxtEmitter Tests
# ==============================================================================

def test_unified_txt_emitter_dispatch_and_save(tmp_path: pathlib.Path) -> None:
    """Test unified TxtEmitter dispatching to Flow and Canvas modes and saving to file."""
    para = Paragraph(
        runs=[TextRun("Unified Test", "Helvetica", 12.0, Color.black(), is_bold=True)],
        bbox=BoundingBox(60, 60, 200, 80),
    )
    page = DocumentPage(page_number=1, width=300, height=300, blocks=[para])
    doc_ir = DocumentIR(pages=[page])

    emitter = TxtEmitter()

    # Flow mode test
    flow_bytes = emitter.emit(doc_ir, mode=ConversionMode.FLOW)
    assert b"**Unified Test**" in flow_bytes

    # Canvas mode test
    canvas_bytes = emitter.emit(doc_ir, mode=ConversionMode.CANVAS)
    assert b"Unified Test" in canvas_bytes
    assert b"**" not in canvas_bytes  # Canvas mode uses plain character positioning

    # Save to file
    out_file = tmp_path / "output.txt"
    emitter.emit_to_file(doc_ir, out_file, mode=ConversionMode.FLOW)
    assert out_file.exists()
    assert "**Unified Test**" in out_file.read_text(encoding="utf-8")
