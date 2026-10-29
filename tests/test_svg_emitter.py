from __future__ import annotations

import io
import pathlib
import xml.etree.ElementTree as ET
import pytest

from anyconvert.api import convert
from anyconvert.cli import create_parser
from anyconvert.common.color import Color
from anyconvert.common.geometry import BoundingBox
from anyconvert.emitters.base import ConversionMode
from anyconvert.emitters.svg import SvgEmitter
from anyconvert.exceptions import SerializationError
from anyconvert.ir.model import (
    Border,
    DocumentIR,
    DocumentPage,
    ImageBlock,
    Paragraph,
    Table,
    TableCell,
    TableRow,
    TextRun,
    VectorBlock,
)
from anyconvert.utils.png import encode_gray_png


def test_svg_emitter_single_page() -> None:
    """Test generating standalone SVG from a single DocumentPage with vector and text."""
    para = Paragraph(
        runs=[
            TextRun("Chapter 1: Vectors", "Helvetica-Bold", 18.0, Color(0, 50, 150), is_bold=True),
            TextRun(" - Overview", "Helvetica", 14.0, Color(50, 50, 50), is_italic=True),
        ],
        bbox=BoundingBox(50.0, 50.0, 400.0, 80.0),
    )
    # Vector polygon
    vec = VectorBlock(
        svg_path="M 50 100 L 200 100 L 200 250 L 50 250 Z",
        bbox=BoundingBox(50.0, 100.0, 200.0, 250.0),
        fill_color=Color(255, 200, 0, 1.0),
        stroke_color=Color(0, 0, 0, 1.0),
        stroke_width=2.5,
        line_cap=1,     # round
        line_join=2,    # bevel
    )

    page = DocumentPage(
        page_number=1,
        width=612.0,
        height=792.0,
        blocks=[para, vec],
    )
    doc_ir = DocumentIR(pages=[page])

    emitter = SvgEmitter()
    svg_bytes = emitter.emit(doc_ir)
    assert len(svg_bytes) > 0
    svg_str = svg_bytes.decode("utf-8")

    assert '<svg' in svg_str
    assert 'viewBox="0 0 612.0 792.0"' in svg_str
    assert '<path' in svg_str
    assert 'd="M 50 100 L 200 100 L 200 250 L 50 250 Z"' in svg_str
    assert 'fill="#ffc800"' in svg_str
    assert 'stroke="#000000"' in svg_str
    assert 'stroke-width="2.50"' in svg_str
    assert 'stroke-linecap="round"' in svg_str
    assert 'stroke-linejoin="bevel"' in svg_str
    assert '<text' in svg_str
    assert 'Chapter 1: Vectors' in svg_str
    assert 'font-weight="bold"' in svg_str
    assert 'font-style="italic"' in svg_str

    # Verify well-formed XML
    root = ET.fromstring(svg_str)
    assert root.tag.endswith("svg")


def test_svg_emitter_vector_styles() -> None:
    """Test vector styles: dashed stroke, transparency, noFill, and line caps."""
    vec = VectorBlock(
        svg_path="M 10 10 L 100 100 Z",
        bbox=BoundingBox(10.0, 10.0, 100.0, 100.0),
        fill_color=Color(10, 20, 30, 1.0),
        fill_alpha=0.5,
        stroke_color=Color(200, 100, 0, 1.0),
        stroke_width=3.0,
        stroke_alpha=0.8,
        line_cap=2,     # square
        line_join=0,    # miter
        miter_limit=8.0,
        dash_array=[5.0, 2.5],
        dash_phase=1.0,
    )
    page = DocumentPage(page_number=1, width=200.0, height=200.0, blocks=[vec])
    emitter = SvgEmitter()
    svg_str = emitter.render_page(page)

    assert 'fill="#0a141e"' in svg_str
    assert 'fill-opacity="0.50"' in svg_str
    assert 'stroke="#c86400"' in svg_str
    assert 'stroke-opacity="0.80"' in svg_str
    assert 'stroke-linecap="square"' in svg_str
    assert 'stroke-miterlimit="8.0"' in svg_str
    assert 'stroke-dasharray="5.00 2.50"' in svg_str
    assert 'stroke-dashoffset="1.00"' in svg_str


def test_svg_emitter_embedded_image_and_table() -> None:
    """Test embedding raster images as base64 data URIs and rendering tables in SVG."""
    png_bytes = encode_gray_png(2, 2, b"\x00\xFF\xFF\x00")
    img = ImageBlock(
        image_bytes=png_bytes,
        bbox=BoundingBox(50.0, 50.0, 150.0, 150.0),
        format="png",
    )

    cell1 = TableCell(
        content=[Paragraph(runs=[TextRun("Cell 1", "Helvetica", 10.0, Color.black())])],
        width=100.0,
        height=30.0,
        background_color=Color(240, 240, 240),
        borders={"top": Border(style="solid", width=1.0, color=Color.black())},
    )
    cell2 = TableCell(
        content=[Paragraph(runs=[TextRun("Cell 2", "Helvetica", 10.0, Color.black())])],
        width=100.0,
        height=30.0,
    )
    table = Table(
        rows=[TableRow(cells=[cell1, cell2], height=30.0)],
        col_widths=[100.0, 100.0],
        bbox=BoundingBox(50.0, 200.0, 250.0, 230.0),
    )

    page = DocumentPage(page_number=1, width=500.0, height=500.0, blocks=[img, table])
    emitter = SvgEmitter()
    svg_str = emitter.render_page(page)

    # Check image base64 data URI
    assert '<image' in svg_str
    assert 'href="data:image/png;base64,' in svg_str
    # Check table rect and borders
    assert '<rect' in svg_str
    assert 'fill="#f0f0f0"' in svg_str
    assert '<line' in svg_str
    assert 'Cell 1' in svg_str
    assert 'Cell 2' in svg_str


def test_svg_emitter_multi_page() -> None:
    """Test multi-page document emission stacking pages vertically."""
    p1 = DocumentPage(
        page_number=1,
        width=400.0,
        height=300.0,
        blocks=[Paragraph(runs=[TextRun("Page One", "Arial", 16.0, Color.black())], bbox=BoundingBox(20.0, 20.0, 200.0, 50.0))],
    )
    p2 = DocumentPage(
        page_number=2,
        width=400.0,
        height=300.0,
        blocks=[Paragraph(runs=[TextRun("Page Two", "Arial", 16.0, Color.black())], bbox=BoundingBox(20.0, 20.0, 200.0, 50.0))],
    )
    doc_ir = DocumentIR(pages=[p1, p2])

    emitter = SvgEmitter()
    svg_bytes = emitter.emit(doc_ir)
    svg_str = svg_bytes.decode("utf-8")

    assert '<g id="page_1"' in svg_str
    assert '<g id="page_2"' in svg_str
    assert 'Page One' in svg_str
    assert 'Page Two' in svg_str

    root = ET.fromstring(svg_str)
    assert root.tag.endswith("svg")


def test_svg_emitter_empty_doc_raises() -> None:
    """Test that SvgEmitter raises SerializationError when given an empty DocumentIR."""
    doc_ir = DocumentIR(pages=[])
    emitter = SvgEmitter()
    with pytest.raises(SerializationError):
        emitter.emit(doc_ir)


def test_cli_parser_includes_svg() -> None:
    """Test that CLI argument parser accepts svg as target format."""
    parser = create_parser()
    args = parser.parse_args(["input.pdf", "-f", "svg", "-o", "output.svg"])
    assert args.format == "svg"
    assert args.output == "output.svg"
