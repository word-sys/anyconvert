"""Tests for pure-Python WordprocessingML (DOCX) and PresentationML (PPTX) emitters."""

import io
import pathlib
import zipfile
import pytest

from anyconvert.common.color import Color
from anyconvert.common.geometry import BoundingBox
from anyconvert.emitters.base import ConversionMode
from anyconvert.emitters.docx import DocxEmitter
from anyconvert.emitters.pptx import PptxEmitter
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
