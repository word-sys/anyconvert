"""Tests for pure-Python WordprocessingML (DOCX) and PresentationML (PPTX) emitters."""

import io
import pathlib
import zipfile
import pytest

from anyconvert.common.color import Color
from anyconvert.common.geometry import BoundingBox
from anyconvert.emitters.base import ConversionMode
from anyconvert.emitters.docx import DocxEmitter
from anyconvert.emitters.docx.drawing import (
    render_vector_block_flow,
    render_vector_run_canvas,
    svg_path_to_drawingml,
)
from anyconvert.emitters.pptx import PptxEmitter
from anyconvert.emitters.pptx.shapes import render_vector_shape
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
from anyconvert.packaging.opc import OPCPackage
from anyconvert.utils.png import encode_gray_png


# ==============================================================================
# DOCX Emitter Tests
# ==============================================================================

def test_docx_emitter_flow_mode() -> None:
    """Test DocxEmitter in Flow mode with paragraphs, headings, tables, images, and headers."""
    # Create sample runs and paragraphs
    h1_run = TextRun(
        text="Chapter 1: Mathematical Foundations",
        font_name="Calibri",
        font_size=24.0,
        color=Color(25, 51, 128),
        is_bold=True,
    )
    h1_para = Paragraph(
        runs=[h1_run],
        alignment=Alignment.LEFT,
        heading_level=HeadingLevel.H1,
        space_before=12.0,
        space_after=6.0,
    )

    body_run1 = TextRun(
        text="The anyconvert engine generates ",
        font_name="Calibri",
        font_size=11.0,
        color=Color.black(),
    )
    body_run2 = TextRun(
        text="pure Python ",
        font_name="Calibri",
        font_size=11.0,
        color=Color(204, 25, 25),
        is_bold=True,
        is_italic=True,
    )
    body_run3 = TextRun(
        text="documents with zero runtime dependencies.",
        font_name="Calibri",
        font_size=11.0,
        color=Color.black(),
    )
    body_para = Paragraph(
        runs=[body_run1, body_run2, body_run3],
        alignment=Alignment.JUSTIFIED,
        line_spacing=1.15,
    )

    # Bullet list item
    bullet_run = TextRun(
        text="High performance zero-copy architecture",
        font_name="Calibri",
        font_size=11.0,
        color=Color.black(),
    )
    bullet_para = Paragraph(
        runs=[bullet_run],
        list_marker="•",
        list_level=0,
    )

    # Table with 2 rows, 2 columns
    cell1 = TableCell(
        content=[Paragraph(runs=[TextRun("Metric", "Calibri", 10.0, Color.black(), is_bold=True)])],
        width=150.0,
        background_color=Color(230, 230, 230),
    )
    cell2 = TableCell(
        content=[Paragraph(runs=[TextRun("Value", "Calibri", 10.0, Color.black(), is_bold=True)])],
        width=150.0,
        background_color=Color(230, 230, 230),
    )
    cell3 = TableCell(
        content=[Paragraph(runs=[TextRun("Pass Rate", "Calibri", 10.0, Color.black())])],
        width=150.0,
    )
    cell4 = TableCell(
        content=[Paragraph(runs=[TextRun("100%", "Calibri", 10.0, Color.black())])],
        width=150.0,
    )

    row1 = TableRow(cells=[cell1, cell2], height=20.0, is_header=True)
    row2 = TableRow(cells=[cell3, cell4], height=20.0, is_header=False)
    table = Table(rows=[row1, row2], col_widths=[150.0, 150.0])

    # Image block
    png_data = encode_gray_png(4, 4, bytes(range(16)), bit_depth=8)
    image = ImageBlock(
        png_bytes=png_data,
        bbox=BoundingBox(50, 50, 200, 200),
        alt_text="Diagnostic Chart",
    )

    # Header and footer
    header = PageHeaderFooter(
        content=[Paragraph(runs=[TextRun("Confidential Report", "Calibri", 9.0, Color.black())])],
        is_footer=False,
    )
    footer = PageHeaderFooter(
        content=[Paragraph(runs=[TextRun("Page 1 of 1", "Calibri", 9.0, Color.black())])],
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
        metadata={"Title": "AnyConvert Technical Specification", "Author": "Antigravity Team"},
    )

    emitter = DocxEmitter()
    docx_bytes = emitter.emit(doc_ir, mode=ConversionMode.FLOW)
    assert len(docx_bytes) > 0

    # Parse and inspect OPC package
    pkg = OPCPackage.parse(docx_bytes)
    assert pkg.has_part("word/document.xml")
    assert pkg.has_part("word/styles.xml")
    assert pkg.has_part("word/numbering.xml")
    assert pkg.has_part("word/settings.xml")
    assert pkg.has_part("word/fontTable.xml")
    assert pkg.has_part("word/header1.xml")
    assert pkg.has_part("word/footer1.xml")
    assert pkg.has_part("word/media/image1.png")

    # Inspect XML text content
    doc_xml = pkg.get_part("word/document.xml").content.decode("utf-8")
    assert '<w:pStyle w:val="Heading1"/>' in doc_xml
    assert '<w:jc w:val="both"/>' in doc_xml
    assert '<w:b/>' in doc_xml
    assert '<w:i/>' in doc_xml
    assert '<w:numPr>' in doc_xml
    assert '<w:tbl>' in doc_xml
    assert '<w:gridCol w:w="3000"/>' in doc_xml  # 150 pt * 20 = 3000 dxa
    assert '<wp:inline' in doc_xml
    assert '<w:headerReference' in doc_xml
    assert '<w:footerReference' in doc_xml


def test_docx_emitter_canvas_mode(tmp_path: pathlib.Path) -> None:
    """Test DocxEmitter in Canvas mode emitting positioned frames and anchored drawings."""
    para = Paragraph(
        runs=[TextRun("Anchored Text Block", "Arial", 14.0, Color.black())],
        bbox=BoundingBox(100.0, 150.0, 300.0, 200.0),
    )
    png_data = encode_gray_png(2, 2, b"\x00\xFF\x00\xFF")
    img = ImageBlock(
        png_bytes=png_data,
        bbox=BoundingBox(350.0, 150.0, 500.0, 300.0),
        alt_text="Anchored Logo",
    )

    page = DocumentPage(
        page_number=1,
        width=612.0,
        height=792.0,
        blocks=[para, img],
    )
    doc_ir = DocumentIR(pages=[page])

    emitter = DocxEmitter()
    out_file = tmp_path / "canvas_output.docx"
    emitter.emit_to_file(doc_ir, out_file, mode=ConversionMode.CANVAS)
    assert out_file.exists()

    pkg = OPCPackage.parse(out_file)
    doc_xml = pkg.get_part("word/document.xml").content.decode("utf-8")

    # In Canvas mode, paragraphs use framePr for positioning
    assert '<w:framePr' in doc_xml
    assert 'w:x="2000"' in doc_xml  # 100 pt * 20 = 2000 dxa
    assert 'w:y="3000"' in doc_xml  # 150 pt * 20 = 3000 dxa

    # Images use wp:anchor
    assert '<wp:anchor' in doc_xml
    assert '<wp:positionH' in doc_xml
    assert '<wp:positionV' in doc_xml


def test_docx_emitter_empty_doc_raises() -> None:
    """Test that DocxEmitter raises SerializationError when given an empty DocumentIR."""
    doc_ir = DocumentIR(pages=[])
    emitter = DocxEmitter()
    with pytest.raises(SerializationError):
        emitter.emit(doc_ir)


# ==============================================================================
# PPTX Emitter Tests
# ==============================================================================

def test_pptx_emitter_multi_slide(tmp_path: pathlib.Path) -> None:
    """Test PptxEmitter mapping multiple pages to presentation slides with shapes, tables, and images."""
    # Slide 1: Title, Subtitle, and Image
    title_run = TextRun("AnyConvert Presentation", "Calibri", 32.0, Color(51, 76, 204), is_bold=True)
    title_p = Paragraph(runs=[title_run], bbox=BoundingBox(50, 50, 650, 120), alignment=Alignment.CENTER)

    sub_run = TextRun("Zero-Dependency Document Conversion Engine", "Calibri", 18.0, Color(102, 102, 102))
    sub_p = Paragraph(runs=[sub_run], bbox=BoundingBox(50, 130, 650, 180), alignment=Alignment.CENTER)

    png_data = encode_gray_png(2, 2, b"\xFF\x00\x00\xFF")
    img_block = ImageBlock(png_bytes=png_data, bbox=BoundingBox(250, 200, 450, 400), alt_text="Slide Diagram")

    page1 = DocumentPage(
        page_number=1,
        width=720.0,
        height=540.0,
        blocks=[title_p, sub_p, img_block],
    )

    # Slide 2: Table
    c1 = TableCell(content=[Paragraph(runs=[TextRun("Format", "Arial", 12.0, Color.black())])], width=100.0)
    c2 = TableCell(content=[Paragraph(runs=[TextRun("Support", "Arial", 12.0, Color.black())])], width=100.0)
    c3 = TableCell(content=[Paragraph(runs=[TextRun("DOCX", "Arial", 12.0, Color.black())])], width=100.0)
    c4 = TableCell(content=[Paragraph(runs=[TextRun("Full", "Arial", 12.0, Color.black())])], width=100.0)

    r1 = TableRow(cells=[c1, c2], height=30.0, is_header=True)
    r2 = TableRow(cells=[c3, c4], height=30.0, is_header=False)
    table = Table(rows=[r1, r2], col_widths=[100.0, 100.0], bbox=BoundingBox(100, 100, 300, 160))

    page2 = DocumentPage(
        page_number=2,
        width=720.0,
        height=540.0,
        blocks=[table],
    )

    doc_ir = DocumentIR(
        pages=[page1, page2],
        metadata={"Title": "Presentation Test", "Author": "Antigravity"},
    )

    emitter = PptxEmitter()
    out_file = tmp_path / "test_presentation.pptx"
    emitter.emit_to_file(doc_ir, out_file)
    assert out_file.exists()

    # Parse and validate PPTX package
    pkg = OPCPackage.parse(out_file)
    assert pkg.has_part("ppt/presentation.xml")
    assert pkg.has_part("ppt/slideMasters/slideMaster1.xml")
    assert pkg.has_part("ppt/slideLayouts/slideLayout1.xml")
    assert pkg.has_part("ppt/theme/theme1.xml")
    assert pkg.has_part("ppt/slides/slide1.xml")
    assert pkg.has_part("ppt/slides/slide2.xml")
    assert pkg.has_part("ppt/media/image1.png")

    # Check slide 1 contents
    s1_xml = pkg.get_part("ppt/slides/slide1.xml").content.decode("utf-8")
    assert '<p:sp>' in s1_xml
    assert 'AnyConvert Presentation' in s1_xml
    assert 'sz="3200"' in s1_xml  # 32 pt * 100 = 3200
    assert '<p:pic>' in s1_xml
    assert 'Slide Diagram' in s1_xml

    # Check slide 2 table contents
    s2_xml = pkg.get_part("ppt/slides/slide2.xml").content.decode("utf-8")
    assert '<p:graphicFrame>' in s2_xml
    assert '<a:tbl>' in s2_xml
    assert 'DOCX' in s2_xml

    # Check presentation.xml links to both slides
    pres_xml = pkg.get_part("ppt/presentation.xml").content.decode("utf-8")
    assert 'r:id="rIdSlide1"' in pres_xml
    assert 'r:id="rIdSlide2"' in pres_xml


def test_pptx_emitter_empty_doc_raises() -> None:
    """Test that PptxEmitter raises SerializationError when given an empty DocumentIR."""
    doc_ir = DocumentIR(pages=[])
    emitter = PptxEmitter()
    with pytest.raises(SerializationError):
        emitter.emit(doc_ir)


def test_docx_heading_color_preservation() -> None:
    """Verify DOCX emitter explicitly emits run color for headings instead of defaulting to blue."""
    h1_run = TextRun(
        text="Black Title",
        font_name="Calibri",
        font_size=20.0,
        color=Color.black(),
    )
    h1_para = Paragraph(
        runs=[h1_run],
        alignment=Alignment.LEFT,
        heading_level=HeadingLevel.H1,
    )
    doc_ir = DocumentIR(pages=[DocumentPage(1, 612.0, 792.0, blocks=[h1_para])])
    emitter = DocxEmitter()
    docx_bytes = emitter.emit(doc_ir)
    pkg = OPCPackage.parse(docx_bytes)
    doc_xml = pkg.get_part("word/document.xml").content.decode("utf-8")
    assert '<w:color w:val="000000"/>' in doc_xml


def test_docx_canvas_line_breaks_and_indents() -> None:
    """Verify DOCX emitter handles multi-line runs with w:br and suppresses frame indents."""
    para = Paragraph(
        runs=[TextRun("Line 1\nLine 2", "Calibri", 12.0, Color.black())],
        bbox=BoundingBox(50.0, 50.0, 200.0, 100.0),
        indent_right=30.0,
    )
    doc_ir = DocumentIR(pages=[DocumentPage(1, 612.0, 792.0, blocks=[para])])
    emitter = DocxEmitter()
    docx_bytes = emitter.emit(doc_ir, mode=ConversionMode.CANVAS)
    pkg = OPCPackage.parse(docx_bytes)
    doc_xml = pkg.get_part("word/document.xml").content.decode("utf-8")

    assert "<w:br/>" in doc_xml
    assert "<w:t xml:space=\"preserve\">Line 1</w:t>" in doc_xml
    assert "<w:t xml:space=\"preserve\">Line 2</w:t>" in doc_xml
    # Verify right indent is NOT emitted inside the canvas frame
    assert '<w:ind w:right=' not in doc_xml


# ==============================================================================
# DOCX & PPTX DrawingML Vector Tests
# ==============================================================================

def test_svg_path_to_drawingml_basic() -> None:
    """Test translating SVG path commands M, L, C, Z to DrawingML."""
    svg = "M 10.00 20.00 L 50.00 60.00 C 70.00 80.00 90.00 100.00 110.00 120.00 Z"
    dml = svg_path_to_drawingml(svg, scale=100.0, origin_x=10.0, origin_y=20.0)

    assert '<a:moveTo><a:pt x="0" y="0"/></a:moveTo>' in dml
    assert '<a:lnTo><a:pt x="4000" y="4000"/></a:lnTo>' in dml
    assert '<a:cubicBezTo>' in dml
    assert '<a:pt x="6000" y="6000"/>' in dml
    assert '<a:pt x="8000" y="8000"/>' in dml
    assert '<a:pt x="10000" y="10000"/>' in dml
    assert '<a:close/>' in dml


def test_svg_path_to_drawingml_multi_subpaths() -> None:
    """Test translating paths with multiple subpaths."""
    svg = "M 0 0 L 10 0 L 10 10 Z M 20 20 L 30 20 L 30 30 Z"
    dml = svg_path_to_drawingml(svg, scale=10.0, origin_x=0.0, origin_y=0.0)

    assert dml.count("<a:moveTo>") == 2
    assert dml.count("<a:close/>") == 2


def test_drawingml_fill_and_alpha() -> None:
    """Test solid fill with and without transparency."""
    vec_opaque = VectorBlock(
        svg_path="M 0 0 L 10 10 Z",
        bbox=BoundingBox(0.0, 0.0, 10.0, 10.0),
        fill_color=Color(255, 0, 0, 1.0),
        stroke_color=None,
    )
    xml_opaque = render_vector_block_flow(vec_opaque, 101)
    assert '<a:solidFill><a:srgbClr val="FF0000"/></a:solidFill>' in xml_opaque

    vec_alpha = VectorBlock(
        svg_path="M 0 0 L 10 10 Z",
        bbox=BoundingBox(0.0, 0.0, 10.0, 10.0),
        fill_color=Color(0, 255, 0, 1.0),
        fill_alpha=0.5,
        stroke_color=None,
    )
    xml_alpha = render_vector_block_flow(vec_alpha, 102)
    assert '<a:solidFill><a:srgbClr val="00FF00"><a:alpha val="50000"/></a:srgbClr></a:solidFill>' in xml_alpha

    vec_nofill = VectorBlock(
        svg_path="M 0 0 L 10 10 Z",
        bbox=BoundingBox(0.0, 0.0, 10.0, 10.0),
        fill_color=None,
        stroke_color=Color(0, 0, 0, 1.0),
    )
    xml_nofill = render_vector_block_flow(vec_nofill, 103)
    assert '<a:noFill/>' in xml_nofill


def test_drawingml_stroke_attributes() -> None:
    """Test line caps, line joins, dashes, and stroke width in DrawingML."""
    vec = VectorBlock(
        svg_path="M 0 0 L 100 100 Z",
        bbox=BoundingBox(0.0, 0.0, 100.0, 100.0),
        stroke_color=Color(0, 0, 255, 1.0),
        stroke_width=2.0,
        line_cap=1,
        line_join=2,
        dash_array=[4.0, 2.0],
    )
    xml = render_vector_block_flow(vec, 104)
    assert 'cap="rnd"' in xml
    assert '<a:bevel/>' in xml
    assert '<a:custDash>' in xml
    assert '<a:ds d="200000" sp="100000"/>' in xml

    vec_miter = VectorBlock(
        svg_path="M 0 0 L 50 50 Z",
        bbox=BoundingBox(0.0, 0.0, 50.0, 50.0),
        stroke_color=Color(0, 0, 0, 1.0),
        stroke_width=1.0,
        line_cap=0,
        line_join=0,
        miter_limit=8.0,
    )
    xml_miter = render_vector_block_flow(vec_miter, 105)
    assert 'cap="flat"' in xml_miter
    assert '<a:miter lim="800000"/>' in xml_miter


def test_docx_emitter_flow_with_vector_blocks() -> None:
    """Test DOCX emitter generating inline DrawingML shapes in Flow mode."""
    vec = VectorBlock(
        svg_path="M 10 10 L 50 10 L 50 50 L 10 50 Z",
        bbox=BoundingBox(10.0, 10.0, 50.0, 50.0),
        fill_color=Color(255, 200, 0, 1.0),
        stroke_color=Color(0, 0, 0, 1.0),
        stroke_width=1.5,
    )
    page = DocumentPage(
        page_number=1,
        width=612.0,
        height=792.0,
        blocks=[
            Paragraph(runs=[TextRun("Above vector shape", "Calibri", 11.0, Color.black())]),
            vec,
            Paragraph(runs=[TextRun("Below vector shape", "Calibri", 11.0, Color.black())]),
        ],
    )
    doc_ir = DocumentIR(pages=[page])
    emitter = DocxEmitter()
    docx_bytes = emitter.emit(doc_ir, mode=ConversionMode.FLOW)
    pkg = OPCPackage.parse(docx_bytes)
    doc_xml = pkg.get_part("word/document.xml").content.decode("utf-8")

    assert '<wp:inline' in doc_xml
    assert '<wps:wsp>' in doc_xml
    assert '<a:custGeom>' in doc_xml
    assert '<a:pathLst>' in doc_xml
    assert '<a:solidFill><a:srgbClr val="FFC800"/></a:solidFill>' in doc_xml


def test_docx_emitter_canvas_with_vector_blocks() -> None:
    """Test DOCX emitter generating positioned DrawingML shapes in Canvas mode."""
    vec = VectorBlock(
        svg_path="M 100 200 L 300 200 L 300 400 Z",
        bbox=BoundingBox(100.0, 200.0, 300.0, 400.0),
        fill_color=Color(100, 150, 200, 1.0),
        stroke_color=Color(50, 50, 50, 1.0),
        stroke_width=2.0,
    )
    page = DocumentPage(
        page_number=1,
        width=612.0,
        height=792.0,
        blocks=[vec],
    )
    doc_ir = DocumentIR(pages=[page])
    emitter = DocxEmitter()
    docx_bytes = emitter.emit(doc_ir, mode=ConversionMode.CANVAS)
    pkg = OPCPackage.parse(docx_bytes)
    doc_xml = pkg.get_part("word/document.xml").content.decode("utf-8")

    assert '<wp:anchor' in doc_xml
    assert 'behindDoc="1"' in doc_xml
    assert '<wps:wsp>' in doc_xml
    assert '<a:custGeom>' in doc_xml
    assert '<a:pathLst>' in doc_xml
    assert '<wp:posOffset>1270000</wp:posOffset>' in doc_xml
    assert '<wp:posOffset>2540000</wp:posOffset>' in doc_xml


def test_pptx_render_vector_shape_basic() -> None:
    """Test generating PresentationML shape <p:sp> with custom geometry."""
    vec = VectorBlock(
        svg_path="M 50 60 L 150 60 L 150 160 Z",
        bbox=BoundingBox(50.0, 60.0, 150.0, 160.0),
        fill_color=Color(255, 0, 0, 1.0),
        stroke_color=Color(0, 0, 0, 1.0),
        stroke_width=2.0,
    )
    xml = render_vector_shape(vec, shape_id=201)

    assert '<p:sp>' in xml
    assert '<p:cNvPr id="201" name="Vector_201"/>' in xml
    assert '<a:custGeom>' in xml
    assert '<a:pathLst>' in xml
    assert '<a:moveTo><a:pt x="0" y="0"/></a:moveTo>' in xml
    assert '<a:lnTo><a:pt x="10000" y="0"/></a:lnTo>' in xml
    assert '<a:close/>' in xml
    assert '<a:off x="635000" y="762000"/>' in xml
    assert '<a:ext cx="1270000" cy="1270000"/>' in xml


def test_pptx_render_vector_shape_fills() -> None:
    """Test PPTX shape fill options: solid, alpha transparency, noFill."""
    v1 = VectorBlock(
        svg_path="M 0 0 L 10 10 Z",
        bbox=BoundingBox(0.0, 0.0, 10.0, 10.0),
        fill_color=Color(0, 128, 255, 1.0),
        stroke_color=None,
    )
    xml1 = render_vector_shape(v1, 1)
    assert '<a:solidFill><a:srgbClr val="0080FF"/></a:solidFill>' in xml1

    v2 = VectorBlock(
        svg_path="M 0 0 L 10 10 Z",
        bbox=BoundingBox(0.0, 0.0, 10.0, 10.0),
        fill_color=Color(10, 20, 30, 1.0),
        fill_alpha=0.4,
        stroke_color=None,
    )
    xml2 = render_vector_shape(v2, 2)
    assert '<a:solidFill><a:srgbClr val="0A141E"><a:alpha val="40000"/></a:srgbClr></a:solidFill>' in xml2

    v3 = VectorBlock(
        svg_path="M 0 0 L 10 10 Z",
        bbox=BoundingBox(0.0, 0.0, 10.0, 10.0),
        fill_color=None,
        stroke_color=Color(0, 0, 0, 1.0),
    )
    xml3 = render_vector_shape(v3, 3)
    assert '<a:noFill/>' in xml3


def test_pptx_render_vector_shape_strokes() -> None:
    """Test PPTX shape stroke attributes: width, cap, join, dashes, alpha."""
    vec = VectorBlock(
        svg_path="M 0 0 L 100 100 Z",
        bbox=BoundingBox(0.0, 0.0, 100.0, 100.0),
        stroke_color=Color(200, 100, 50, 1.0),
        stroke_width=3.0,
        stroke_alpha=0.75,
        line_cap=1,
        line_join=2,
        dash_array=[6.0, 3.0],
    )
    xml = render_vector_shape(vec, 4)

    assert 'cap="rnd"' in xml
    assert '<a:bevel/>' in xml
    assert '<a:custDash>' in xml
    assert '<a:ds d="200000" sp="100000"/>' in xml
    assert '<a:alpha val="75000"/>' in xml

    vec_sq = VectorBlock(
        svg_path="M 0 0 L 50 50 Z",
        bbox=BoundingBox(0.0, 0.0, 50.0, 50.0),
        stroke_color=Color(0, 0, 0, 1.0),
        stroke_width=1.0,
        line_cap=2,
        line_join=0,
        miter_limit=5.0,
    )
    xml_sq = render_vector_shape(vec_sq, 5)
    assert 'cap="sq"' in xml_sq
    assert '<a:miter lim="500000"/>' in xml_sq


def test_pptx_emitter_end_to_end_with_vectors() -> None:
    """Test end-to-end PPTX generation with VectorBlock shapes alongside text."""
    para = Paragraph(
        runs=[TextRun("Slide Title", "Calibri", 28.0, Color(0, 0, 0), is_bold=True)],
        bbox=BoundingBox(50.0, 40.0, 400.0, 80.0),
    )
    triangle = VectorBlock(
        svg_path="M 50 150 L 150 150 L 100 250 Z",
        bbox=BoundingBox(50.0, 150.0, 150.0, 250.0),
        fill_color=Color(0, 150, 255, 1.0),
        stroke_color=Color(0, 50, 150, 1.0),
        stroke_width=2.0,
    )
    curve = VectorBlock(
        svg_path="M 200 150 C 250 100 300 200 350 150",
        bbox=BoundingBox(200.0, 100.0, 350.0, 200.0),
        fill_color=None,
        stroke_color=Color(255, 50, 50, 1.0),
        stroke_width=3.0,
        line_cap=1,
    )
    page = DocumentPage(
        page_number=1,
        width=720.0,
        height=540.0,
        blocks=[para, triangle, curve],
    )
    doc_ir = DocumentIR(pages=[page])
    emitter = PptxEmitter()
    pptx_bytes = emitter.emit(doc_ir)
    assert len(pptx_bytes) > 0

    pkg = OPCPackage.parse(pptx_bytes)
    assert pkg.has_part("ppt/slides/slide1.xml")
    slide_xml = pkg.get_part("ppt/slides/slide1.xml").content.decode("utf-8")
    assert '<p:spTree>' in slide_xml


