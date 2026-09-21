"""Tests for Document Intermediate Representation (DIR) models, validator, and builder."""

import pytest

from anyconvert.common.color import Color
from anyconvert.common.geometry import BoundingBox, Point
from anyconvert.exceptions import IRBuilderError, IRValidationError
from anyconvert.ir.builder import DocumentIRBuilder
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
from anyconvert.ir.validator import validate_document_ir
from anyconvert.pdf.content.interpreter import (
    ImageElement,
    InterpreterOutput,
    TextElement,
    VectorElement,
)
from anyconvert.pdf.parser import PDFDict, PDFName, PDFStream
from anyconvert.utils.png import PNG_SIGNATURE, encode_gray_png


# ==============================================================================
# 1. Model Instantiation & Properties
# ==============================================================================

def test_model_instantiation_and_properties() -> None:
    """Test creating DIR models and accessing helper properties."""
    run1 = TextRun(text="Hello ", font_name="Helvetica", font_size=12.0, color=Color.black())
    run2 = TextRun(text="World", font_name="Helvetica-Bold", font_size=12.0, color=Color.black(), is_bold=True)

    para = Paragraph(
        runs=[run1, run2],
        alignment=Alignment.LEFT,
        heading_level=HeadingLevel.H1,
        line_spacing=1.15,
        space_before=10.0,
        space_after=5.0,
    )

    assert para.text == "Hello World"
    assert para.heading_level == HeadingLevel.H1
    assert para.alignment == Alignment.LEFT

    table = Table(
        rows=[
            TableRow(
                cells=[TableCell(content=[para], width=100.0, height=20.0)],
                height=20.0,
                is_header=True,
            )
        ],
        col_widths=[100.0],
    )
    assert len(table.rows) == 1
    assert table.rows[0].is_header is True
    assert len(table.rows[0].cells) == 1

    png_data = encode_gray_png(2, 2, b"\x00\xFF\x00\xFF")
    img = ImageBlock(png_bytes=png_data, bbox=BoundingBox(50, 50, 150, 150))
    assert img.png_bytes.startswith(PNG_SIGNATURE)

    vec = VectorBlock(svg_path="M 0 0 L 10 10 Z", bbox=BoundingBox(0, 0, 10, 10))
    assert vec.svg_path == "M 0 0 L 10 10 Z"


# ==============================================================================
# 2. Validator Invariant Tests
# ==============================================================================

def test_validator_valid_document() -> None:
    """Test that a well-formed DocumentIR passes validation cleanly."""
    page = DocumentPage(
        page_number=1,
        width=612.0,
        height=792.0,
        margin_left=72.0,
        margin_right=72.0,
        margin_top=72.0,
        margin_bottom=72.0,
        blocks=[
            Paragraph(
                runs=[TextRun(text="Valid paragraph", font_name="Helv", font_size=12.0, color=Color.black())]
            )
        ],
    )

    doc_ir = DocumentIR(pages=[page], metadata={"Title": "Test Doc"})
    validate_document_ir(doc_ir)  # should not raise


def test_validator_empty_pages_raises() -> None:
    """Test that DocumentIR with empty pages list raises IRValidationError."""
    doc_ir = DocumentIR(pages=[])
    with pytest.raises(IRValidationError):
        validate_document_ir(doc_ir)


def test_validator_invalid_page_dimensions_raises() -> None:
    """Test that non-positive page dimensions raise IRValidationError."""
    page = DocumentPage(page_number=1, width=0.0, height=792.0)
    doc_ir = DocumentIR(pages=[page])
    with pytest.raises(IRValidationError):
        validate_document_ir(doc_ir)


def test_validator_margins_exceed_page_raises() -> None:
    """Test that margins exceeding page dimensions raise IRValidationError."""
    page = DocumentPage(
        page_number=1,
        width=200.0,
        height=792.0,
        margin_left=120.0,
        margin_right=100.0,  # sum = 220 > 200
    )
    doc_ir = DocumentIR(pages=[page])
    with pytest.raises(IRValidationError):
        validate_document_ir(doc_ir)


def test_validator_invalid_heading_level_raises() -> None:
    """Test that invalid heading level raises IRValidationError."""
    p = Paragraph(
        runs=[TextRun(text="Heading", font_name="Helv", font_size=16.0, color=Color.black())],
        heading_level="INVALID",  # type: ignore[arg-type]
    )
    page = DocumentPage(page_number=1, width=612, height=792, blocks=[p])
    doc_ir = DocumentIR(pages=[page])
    with pytest.raises(IRValidationError):
        validate_document_ir(doc_ir)


def test_validator_invalid_table_spans_raises() -> None:
    """Test that TableCell with non-positive span raises IRValidationError."""
    cell = TableCell(col_span=0, row_span=1)  # col_span must be >= 1
    row = TableRow(cells=[cell])
    table = Table(rows=[row], col_widths=[100.0])
    page = DocumentPage(page_number=1, width=612, height=792, blocks=[table])
    doc_ir = DocumentIR(pages=[page])
    with pytest.raises(IRValidationError):
        validate_document_ir(doc_ir)


def test_validator_corrupt_image_bytes_raises() -> None:
    """Test that ImageBlock with invalid PNG signature raises IRValidationError."""
    img = ImageBlock(png_bytes=b"CORRUPT_NOT_PNG", bbox=BoundingBox(0, 0, 50, 50))
    page = DocumentPage(page_number=1, width=612, height=792, blocks=[img])
    doc_ir = DocumentIR(pages=[page])
    with pytest.raises(IRValidationError):
        validate_document_ir(doc_ir)


# ==============================================================================
# 3. DocumentIRBuilder End-to-End Tests
# ==============================================================================

def test_builder_synthesizes_page_and_document() -> None:
    """Test DocumentIRBuilder synthesizing paragraphs, headings, lists, and images."""
    page_w = 612.0
    page_h = 792.0

    # In PDF coordinates:
    # Running header at top of PDF: y in [760, 775] (doc y in [17, 32])
    header_el = TextElement(
        text="Annual Technical Report",
        bbox=BoundingBox(50, 760, 250, 775),
        origin=Point(50, 760),
        font_name="Helvetica",
        font_size=10.0,
        color=Color.black(),
    )

    # Document Title H1 at y in [680, 710] (font size 24)
    title_el = TextElement(
        text="Enterprise Document Converter",
        bbox=BoundingBox(50, 680, 450, 710),
        origin=Point(50, 680),
        font_name="Helvetica-Bold",
        font_size=24.0,
        color=Color.black(),
        is_bold=True,
    )

    # Body Paragraph at y in [630, 650] (font size 11)
    body_el = TextElement(
        text="The conversion engine operates in pure Python with zero dependencies.",
        bbox=BoundingBox(50, 630, 450, 650),
        origin=Point(50, 630),
        font_name="Helvetica",
        font_size=11.0,
        color=Color.black(),
    )

    # Bullet List Item at y in [590, 610]
    list_el = TextElement(
        text="• High performance mathematical pipeline",
        bbox=BoundingBox(50, 590, 350, 610),
        origin=Point(50, 590),
        font_name="Helvetica",
        font_size=11.0,
        color=Color.black(),
    )

    # Image element at y in [450, 550]
    png_bytes = encode_gray_png(2, 2, b"\x00\xFF\xFF\x00")
    img_stream = PDFStream(
        dict=PDFDict({
            "Type": PDFName("XObject"),
            "Subtype": PDFName("Image"),
            "Width": 2,
            "Height": 2,
            "ColorSpace": PDFName("DeviceGray"),
            "BitsPerComponent": 8,
        }),
        data=memoryview(b"\x00\xFF\xFF\x00"),
    )
    img_el = ImageElement(
        name="Chart1",
        ctm=None,  # type: ignore[arg-type]
        bbox=BoundingBox(50, 450, 200, 550),
        stream=img_stream,
    )

    # Footer at y in [20, 35] (doc y in [757, 772])
    footer_el = TextElement(
        text="Page 1 of 1",
        bbox=BoundingBox(250, 20, 350, 35),
        origin=Point(250, 20),
        font_name="Helvetica",
        font_size=10.0,
        color=Color.black(),
    )

    interp_output = InterpreterOutput(
        text_elements=[header_el, title_el, body_el, list_el, footer_el],
        vector_elements=[],
        image_elements=[img_el],
    )

    builder = DocumentIRBuilder()
    doc_page = builder.build_page(
        output=interp_output,
        page_width=page_w,
        page_height=page_h,
        page_number=1,
    )

    assert doc_page.page_number == 1
    assert doc_page.width == page_w
    assert doc_page.height == page_h

    # Check header and footer
    assert doc_page.header is not None
    assert "Annual Technical Report" in doc_page.header.content[0].text

    assert doc_page.footer is not None
    assert "Page 1 of 1" in doc_page.footer.content[0].text

    # Check body blocks
    blocks = doc_page.blocks
    paragraphs = [b for b in blocks if isinstance(b, Paragraph)]
    images = [b for b in blocks if isinstance(b, ImageBlock)]

    assert len(images) == 1
    assert images[0].png_bytes.startswith(PNG_SIGNATURE)

    # Check heading and list
    h1_paras = [p for p in paragraphs if p.heading_level == HeadingLevel.H1]
    assert len(h1_paras) == 1
    assert "Enterprise Document Converter" in h1_paras[0].text

    list_paras = [p for p in paragraphs if p.list_marker == "•"]
    assert len(list_paras) == 1
    assert "High performance mathematical pipeline" in list_paras[0].text

    # Build full document and validate
    doc_ir = builder.build_document([doc_page], metadata={"Title": "Annual Technical Report"})
    assert len(doc_ir.pages) == 1
    assert doc_ir.metadata["Title"] == "Annual Technical Report"


def test_builder_table_integration() -> None:
    """Test DocumentIRBuilder recognizing vector rulings and emitting a DIR Table."""
    page_w = 612.0
    page_h = 792.0

    # In PDF space (Y ascending from 0 at bottom):
    # Table from y=400 to y=500, x=50 to x=250
    h1 = VectorElement(svg_path="", bbox=BoundingBox(50, 499.5, 250, 500.5))
    h2 = VectorElement(svg_path="", bbox=BoundingBox(50, 449.5, 250, 450.5))
    h3 = VectorElement(svg_path="", bbox=BoundingBox(50, 399.5, 250, 400.5))

    v1 = VectorElement(svg_path="", bbox=BoundingBox(49.5, 400, 50.5, 500))
    v2 = VectorElement(svg_path="", bbox=BoundingBox(149.5, 400, 150.5, 500))
    v3 = VectorElement(svg_path="", bbox=BoundingBox(249.5, 400, 250.5, 500))

    # Text lines in cells
    # Top row in doc space: y in [292, 342]
    l00 = TextElement(text="Header 1", bbox=BoundingBox(60, 460, 120, 480), origin=Point(60, 460), font_name="H", font_size=11, color=Color.black())
    l01 = TextElement(text="Header 2", bbox=BoundingBox(160, 460, 220, 480), origin=Point(160, 460), font_name="H", font_size=11, color=Color.black())
    # Bottom row in doc space: y in [342, 392]
    l10 = TextElement(text="Data A", bbox=BoundingBox(60, 410, 120, 430), origin=Point(60, 410), font_name="H", font_size=11, color=Color.black())
    l11 = TextElement(text="Data B", bbox=BoundingBox(160, 410, 220, 430), origin=Point(160, 410), font_name="H", font_size=11, color=Color.black())

    interp_output = InterpreterOutput(
        text_elements=[l00, l01, l10, l11],
        vector_elements=[h1, h2, h3, v1, v2, v3],
        image_elements=[],
    )

    builder = DocumentIRBuilder()
    page = builder.build_page(interp_output, page_width=page_w, page_height=page_h, page_number=1)

    tables = [b for b in page.blocks if isinstance(b, Table)]
    assert len(tables) == 1
    table = tables[0]
    assert len(table.rows) == 2
    assert len(table.col_widths) == 2

    # Validate full DocumentIR
    doc = builder.build_document([page])
    assert len(doc.pages) == 1


def test_builder_empty_pages_raises() -> None:
    """Test that DocumentIRBuilder.build_document with empty pages raises IRBuilderError."""
    builder = DocumentIRBuilder()
    with pytest.raises(IRBuilderError):
        builder.build_document([])
