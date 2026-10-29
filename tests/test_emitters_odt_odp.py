"""Tests for pure-Python OASIS OpenDocument Text (ODT) and Presentation (ODP) emitters."""

import io
import pathlib
import xml.etree.ElementTree as ET
import zipfile
import pytest

from anyconvert.common.color import Color
from anyconvert.common.geometry import BoundingBox
from anyconvert.emitters.base import ConversionMode
from anyconvert.emitters.odp import OdpEmitter, render_vector_path_odp
from anyconvert.emitters.odt import OdtEmitter, render_vector_path_odt
from anyconvert.exceptions import SerializationError
from anyconvert.ir.model import (
    Alignment,
    Border,
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
from anyconvert.packaging.odf import (
    MIMETYPE_ODP,
    MIMETYPE_ODT,
    MIMETYPE_PART_NAME,
    ODFPackage,
)
from anyconvert.utils.png import encode_gray_png


# ==============================================================================
# ODT Emitter Tests
# ==============================================================================

def test_odt_emitter_flow_mode() -> None:
    """Test OdtEmitter in Flow mode with paragraphs, headings, tables, images, and headers."""
    h1_run = TextRun(
        text="OpenDocument Architecture",
        font_name="Helvetica-Bold",
        font_size=24.0,
        color=Color(20, 40, 100),
        is_bold=True,
    )
    h1_para = Paragraph(
        runs=[h1_run],
        alignment=Alignment.LEFT,
        heading_level=HeadingLevel.H1,
        space_before=14.0,
        space_after=7.0,
    )

    body_run1 = TextRun("This document was generated using ", "Helvetica", 11.0, Color.black())
    body_run2 = TextRun("pure Python ODT emitter ", "Helvetica-Bold", 11.0, Color(180, 20, 20), is_bold=True)
    body_run3 = TextRun("without external dependencies.", "Helvetica", 11.0, Color.black())
    body_para = Paragraph(
        runs=[body_run1, body_run2, body_run3],
        alignment=Alignment.JUSTIFIED,
        line_spacing=1.2,
    )

    # Bullet list item
    bullet_run = TextRun("Complies with ISO/IEC 26300 standard", "Helvetica", 11.0, Color.black())
    bullet_para = Paragraph(
        runs=[bullet_run],
        list_marker="•",
        list_level=0,
    )

    # Table with cell spanning
    c1 = TableCell(
        content=[Paragraph(runs=[TextRun("Header ColSpan 2", "Helvetica", 10.0, Color.black(), is_bold=True)])],
        col_span=2,
        width=300.0,
        background_color=Color(220, 220, 220),
    )
    c2 = TableCell(
        content=[Paragraph(runs=[TextRun("Data A", "Helvetica", 10.0, Color.black())])],
        width=150.0,
    )
    c3 = TableCell(
        content=[Paragraph(runs=[TextRun("Data B", "Helvetica", 10.0, Color.black())])],
        width=150.0,
    )
    row1 = TableRow(cells=[c1], height=24.0, is_header=True)
    row2 = TableRow(cells=[c2, c3], height=20.0, is_header=False)
    table = Table(rows=[row1, row2], col_widths=[150.0, 150.0])

    # Image
    png_data = encode_gray_png(4, 4, bytes(range(16)), bit_depth=8)
    image = ImageBlock(
        png_bytes=png_data,
        bbox=BoundingBox(50, 50, 200, 200),
        alt_text="Architecture Flowchart",
    )

    header = PageHeaderFooter(
        content=[Paragraph(runs=[TextRun("AnyConvert Technical Documentation", "Helvetica", 9.0, Color.black())])],
        is_footer=False,
    )
    footer = PageHeaderFooter(
        content=[Paragraph(runs=[TextRun("Confidential - Page 1", "Helvetica", 9.0, Color.black())])],
        is_footer=True,
    )

    page = DocumentPage(
        page_number=1,
        width=612.0,
        height=792.0,
        blocks=[h1_para, body_para, bullet_para, table, image],
        header=header,
        footer=footer,
    )

    doc_ir = DocumentIR(
        pages=[page],
        metadata={"Title": "ODT Specification", "Author": "Antigravity"},
    )

    emitter = OdtEmitter()
    odt_bytes = emitter.emit(doc_ir, mode=ConversionMode.FLOW)
    assert len(odt_bytes) > 0

    # Verify ISO/IEC 26300 container constraints
    with zipfile.ZipFile(io.BytesIO(odt_bytes), "r") as zf:
        assert zf.filelist[0].filename == MIMETYPE_PART_NAME
        assert zf.filelist[0].compress_type == zipfile.ZIP_STORED
        assert len(zf.filelist[0].extra) == 0
        assert zf.filelist[0].header_offset == 0
        assert zf.read(MIMETYPE_PART_NAME) == b"application/vnd.oasis.opendocument.text"

    # Parse ODF package
    pkg = ODFPackage.parse(odt_bytes)
    assert pkg.mimetype == MIMETYPE_ODT
    assert pkg.has_part("content.xml")
    assert pkg.has_part("styles.xml")
    assert pkg.has_part("meta.xml")
    assert pkg.has_part("Pictures/image1.png")

    content_xml = pkg.get_part("content.xml").content.decode("utf-8")
    assert '<text:h text:outline-level="1"' in content_xml
    assert 'OpenDocument Architecture' in content_xml
    assert '<table:table' in content_xml
    assert '<table:covered-table-cell/>' in content_xml
    assert '<draw:frame' in content_xml
    assert '<draw:image' in content_xml
    assert 'Pictures/image1.png' in content_xml

    styles_xml = pkg.get_part("styles.xml").content.decode("utf-8")
    assert '<style:header>' in styles_xml
    assert 'AnyConvert Technical Documentation' in styles_xml
    assert '<style:footer>' in styles_xml
    assert 'Confidential - Page 1' in styles_xml


def test_odt_emitter_canvas_mode(tmp_path: pathlib.Path) -> None:
    """Test OdtEmitter in Canvas mode emitting positioned graphic frames."""
    para = Paragraph(
        runs=[TextRun("Absolute Block", "Helvetica", 12.0, Color.black())],
        bbox=BoundingBox(100.0, 200.0, 350.0, 250.0),
    )
    png_data = encode_gray_png(2, 2, b"\x00\xFF\xFF\x00")
    img = ImageBlock(
        png_bytes=png_data,
        bbox=BoundingBox(400.0, 200.0, 500.0, 300.0),
        alt_text="Canvas Logo",
    )

    page = DocumentPage(
        page_number=1,
        width=612.0,
        height=792.0,
        blocks=[para, img],
    )
    doc_ir = DocumentIR(pages=[page])

    emitter = OdtEmitter()
    out_file = tmp_path / "canvas.odt"
    emitter.emit_to_file(doc_ir, out_file, mode=ConversionMode.CANVAS)
    assert out_file.exists()

    pkg = ODFPackage.parse(out_file)
    content_xml = pkg.get_part("content.xml").content.decode("utf-8")

    assert '<draw:frame' in content_xml
    assert 'svg:x="100.0pt"' in content_xml
    assert 'svg:y="200.0pt"' in content_xml
    assert 'text:anchor-type="page"' in content_xml
    assert 'Canvas Logo' in content_xml


def test_odt_emitter_empty_doc_raises() -> None:
    """Test that OdtEmitter raises SerializationError when given an empty DocumentIR."""
    doc_ir = DocumentIR(pages=[])
    emitter = OdtEmitter()
    with pytest.raises(SerializationError):
        emitter.emit(doc_ir)


# ==============================================================================
# ODP Emitter Tests
# ==============================================================================

def test_odp_emitter_multi_slide(tmp_path: pathlib.Path) -> None:
    """Test OdpEmitter mapping multiple pages to presentation slides with shapes, tables, and images."""
    title_run = TextRun("ODP Presentation", "Helvetica", 28.0, Color(30, 60, 150), is_bold=True)
    title_p = Paragraph(runs=[title_run], bbox=BoundingBox(50, 40, 670, 90), alignment=Alignment.CENTER)

    body_run = TextRun("Slide 1 content text", "Helvetica", 14.0, Color.black())
    body_p = Paragraph(runs=[body_run], bbox=BoundingBox(50, 110, 670, 150))

    png_data = encode_gray_png(2, 2, b"\x00\x00\xFF\xFF")
    img_block = ImageBlock(png_bytes=png_data, bbox=BoundingBox(200, 180, 520, 400), alt_text="ODP Chart")

    page1 = DocumentPage(
        page_number=1,
        width=720.0,
        height=540.0,
        blocks=[title_p, body_p, img_block],
    )

    # Slide 2 with table
    c1 = TableCell(content=[Paragraph(runs=[TextRun("Item", "Helvetica", 12.0, Color.black(), is_bold=True)])], width=120.0)
    c2 = TableCell(content=[Paragraph(runs=[TextRun("Status", "Helvetica", 12.0, Color.black(), is_bold=True)])], width=120.0)
    c3 = TableCell(content=[Paragraph(runs=[TextRun("ODT", "Helvetica", 12.0, Color.black())])], width=120.0)
    c4 = TableCell(content=[Paragraph(runs=[TextRun("Ready", "Helvetica", 12.0, Color.black())])], width=120.0)

    row1 = TableRow(cells=[c1, c2], height=28.0, is_header=True)
    row2 = TableRow(cells=[c3, c4], height=24.0, is_header=False)
    table = Table(rows=[row1, row2], col_widths=[120.0, 120.0], bbox=BoundingBox(100, 100, 340, 160))

    page2 = DocumentPage(
        page_number=2,
        width=720.0,
        height=540.0,
        blocks=[table],
    )

    doc_ir = DocumentIR(
        pages=[page1, page2],
        metadata={"Title": "ODP Presentation Test", "Author": "Antigravity"},
    )

    emitter = OdpEmitter()
    out_file = tmp_path / "presentation.odp"
    emitter.emit_to_file(doc_ir, out_file)
    assert out_file.exists()

    # Verify ISO/IEC 26300 container constraints
    with zipfile.ZipFile(out_file, "r") as zf:
        assert zf.filelist[0].filename == MIMETYPE_PART_NAME
        assert zf.filelist[0].compress_type == zipfile.ZIP_STORED
        assert len(zf.filelist[0].extra) == 0
        assert zf.filelist[0].header_offset == 0
        assert zf.read(MIMETYPE_PART_NAME) == b"application/vnd.oasis.opendocument.presentation"

    pkg = ODFPackage.parse(out_file)
    assert pkg.mimetype == MIMETYPE_ODP
    assert pkg.has_part("content.xml")
    assert pkg.has_part("styles.xml")
    assert pkg.has_part("meta.xml")
    assert pkg.has_part("Pictures/image1.png")

    content_xml = pkg.get_part("content.xml").content.decode("utf-8")
    assert '<office:presentation>' in content_xml
    assert '<draw:page draw:name="page1"' in content_xml
    assert '<draw:page draw:name="page2"' in content_xml
    assert 'ODP Presentation' in content_xml
    assert 'ODP Chart' in content_xml
    assert '<table:table' in content_xml
    assert 'ODT' in content_xml
    assert 'Ready' in content_xml

    styles_xml = pkg.get_part("styles.xml").content.decode("utf-8")
    assert 'fo:page-width="720.0pt"' in styles_xml
    assert 'fo:page-height="540.0pt"' in styles_xml


def test_odp_emitter_empty_doc_raises() -> None:
    """Test that OdpEmitter raises SerializationError when given an empty DocumentIR."""
    doc_ir = DocumentIR(pages=[])
    emitter = OdpEmitter()
    with pytest.raises(SerializationError):
        emitter.emit(doc_ir)


def test_odt_canvas_line_breaks_and_indents() -> None:
    """Verify ODT emitter handles multi-line runs with text:line-break and zeroes frame indents."""
    para = Paragraph(
        runs=[TextRun("Line A\nLine B", "Helvetica", 12.0, Color.black())],
        bbox=BoundingBox(50.0, 50.0, 200.0, 100.0),
        indent_right=30.0,
    )
    doc_ir = DocumentIR(pages=[DocumentPage(1, 612.0, 792.0, blocks=[para])])
    emitter = OdtEmitter()
    odt_bytes = emitter.emit(doc_ir, mode=ConversionMode.CANVAS)
    pkg = ODFPackage.parse(odt_bytes)
    content_xml = pkg.get_part("content.xml").content.decode("utf-8")

    assert "<text:line-break/>" in content_xml
    assert "Line A" in content_xml
    assert "Line B" in content_xml


# ==============================================================================
# ODF Vector Path Tests
# ==============================================================================

def test_odt_render_vector_path_basic() -> None:
    """Test generating ODT <draw:path> with stroke, fill, and page anchor."""
    vec = VectorBlock(
        svg_path="M 10 20 L 110 20 L 110 120 Z",
        bbox=BoundingBox(10.0, 20.0, 110.0, 120.0),
        fill_color=Color(255, 0, 0, 1.0),
        stroke_color=Color(0, 0, 0, 1.0),
        stroke_width=2.0,
    )
    auto_styles: list[str] = []
    xml = render_vector_path_odt(vec, auto_styles, page_num=1)

    assert len(auto_styles) == 1
    style = auto_styles[0]
    assert '<style:style style:name="V1" style:family="graphic">' in style
    assert 'draw:stroke="solid"' in style
    assert 'svg:stroke-color="#000000"' in style
    assert 'svg:stroke-width="2.00pt"' in style
    assert 'draw:fill="solid"' in style
    assert 'draw:fill-color="#ff0000"' in style

    assert '<draw:path draw:style-name="V1"' in xml
    assert 'svg:d="M 10 20 L 110 20 L 110 120 Z"' in xml
    assert 'svg:x="10.0pt" svg:y="20.0pt" svg:width="100.0pt" svg:height="100.0pt"' in xml
    assert 'svg:viewBox="10.0 20.0 100.0 100.0"' in xml
    assert 'text:anchor-type="page" text:anchor-page-num="1"' in xml


def test_odt_render_vector_path_stroke_attributes() -> None:
    """Test line caps, joins, dashes, and opacity in ODT graphic styles."""
    vec = VectorBlock(
        svg_path="M 0 0 L 50 50 Z",
        bbox=BoundingBox(0.0, 0.0, 50.0, 50.0),
        stroke_color=Color(0, 128, 255, 1.0),
        stroke_width=1.5,
        stroke_alpha=0.8,
        line_cap=1,
        line_join=2,
        dash_array=[4.0, 2.0],
    )
    auto_styles: list[str] = []
    render_vector_path_odt(vec, auto_styles, page_num=2)

    assert len(auto_styles) == 1
    style = auto_styles[0]
    assert 'draw:stroke="dash"' in style
    assert 'svg:stroke-linecap="round"' in style
    assert 'svg:stroke-linejoin="bevel"' in style
    assert 'svg:stroke-opacity="0.80"' in style

    vec_sq = VectorBlock(
        svg_path="M 0 0 L 20 20 Z",
        bbox=BoundingBox(0.0, 0.0, 20.0, 20.0),
        stroke_color=Color(0, 0, 0, 1.0),
        stroke_width=1.0,
        line_cap=2,
        line_join=0,
        miter_limit=6.0,
    )
    auto_styles_sq: list[str] = []
    render_vector_path_odt(vec_sq, auto_styles_sq, page_num=1)
    assert 'svg:stroke-linecap="square"' in auto_styles_sq[0]
    assert 'svg:stroke-linejoin="miter"' in auto_styles_sq[0]
    assert 'svg:stroke-miterlimit="6.0"' in auto_styles_sq[0]


def test_odp_render_vector_path_basic() -> None:
    """Test generating ODP presentation shape <draw:path> placed on slide."""
    vec = VectorBlock(
        svg_path="M 50 50 C 70 20 90 20 110 50",
        bbox=BoundingBox(50.0, 20.0, 110.0, 50.0),
        fill_color=None,
        stroke_color=Color(255, 100, 0, 1.0),
        stroke_width=3.0,
        line_cap=1,
    )
    auto_styles: list[str] = []
    xml = render_vector_path_odp(vec, auto_styles, shape_id=10)

    assert len(auto_styles) == 1
    assert 'draw:fill="none"' in auto_styles[0]
    assert 'svg:stroke-linecap="round"' in auto_styles[0]
    assert 'draw:stroke="solid"' in auto_styles[0]

    assert '<draw:path draw:id="Vector_10" draw:style-name="V1"' in xml
    assert 'svg:d="M 50 50 C 70 20 90 20 110 50"' in xml
    assert 'svg:x="50.0pt" svg:y="20.0pt"' in xml


def test_odt_emitter_end_to_end_with_vectors() -> None:
    """Test full ODT document export containing vector shapes alongside paragraphs."""
    para = Paragraph(
        runs=[TextRun("Vector Shape in OpenDocument Text", "Helvetica", 14.0, Color.black())],
        bbox=BoundingBox(72.0, 72.0, 400.0, 100.0),
    )
    vec = VectorBlock(
        svg_path="M 100 150 L 250 150 L 250 300 L 100 300 Z",
        bbox=BoundingBox(100.0, 150.0, 250.0, 300.0),
        fill_color=Color(100, 200, 255, 1.0),
        stroke_color=Color(0, 50, 150, 1.0),
        stroke_width=2.5,
    )
    page = DocumentPage(
        page_number=1,
        width=612.0,
        height=792.0,
        blocks=[para, vec],
    )
    doc_ir = DocumentIR(pages=[page])

    emitter = OdtEmitter()
    odt_bytes = emitter.emit(doc_ir)
    assert len(odt_bytes) > 0

    pkg = ODFPackage.parse(odt_bytes)
    assert pkg.has_part("content.xml")
    content_xml = pkg.get_part("content.xml").content.decode("utf-8")

    assert '<draw:path' in content_xml
    assert 'svg:d="M 100 150 L 250 150 L 250 300 L 100 300 Z"' in content_xml
    assert 'draw:fill="solid"' in content_xml
    assert 'draw:fill-color="#64c8ff"' in content_xml


def test_odp_emitter_end_to_end_with_vectors() -> None:
    """Test full ODP presentation export containing vector shapes on presentation slides."""
    title = Paragraph(
        runs=[TextRun("Slide With Vector Markups", "Helvetica-Bold", 24.0, Color(10, 20, 80), is_bold=True)],
        bbox=BoundingBox(50.0, 40.0, 500.0, 80.0),
    )
    vec = VectorBlock(
        svg_path="M 200 200 L 300 200 L 250 300 Z",
        bbox=BoundingBox(200.0, 200.0, 300.0, 300.0),
        fill_color=Color(255, 180, 0, 1.0),
        stroke_color=Color(180, 50, 0, 1.0),
        stroke_width=2.0,
    )
    page = DocumentPage(
        page_number=1,
        width=720.0,
        height=540.0,
        blocks=[title, vec],
    )
    doc_ir = DocumentIR(pages=[page])

    emitter = OdpEmitter()
    odp_bytes = emitter.emit(doc_ir)
    assert len(odp_bytes) > 0

    pkg = ODFPackage.parse(odp_bytes)
    assert pkg.has_part("content.xml")
    content_xml = pkg.get_part("content.xml").content.decode("utf-8")

    assert '<draw:page' in content_xml
    assert '<draw:path' in content_xml
    assert 'Vector_' in content_xml
    assert 'draw:fill="solid"' in content_xml
    assert 'draw:fill-color="#ffb400"' in content_xml

    root = ET.fromstring(content_xml)
    assert root.tag.endswith("document-content")

