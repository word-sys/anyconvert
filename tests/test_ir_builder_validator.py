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


def test_builder_vector_underline_correlation() -> None:
    """Test that a thin horizontal vector stroke under text is recognized as an underline and absorbed."""
    from anyconvert.ir.model import VectorBlock
    page_w, page_h = 612.0, 792.0

    text_el = TextElement(
        text="Underlined Text",
        bbox=BoundingBox(100.0, 500.0, 200.0, 514.0),
        origin=Point(100.0, 500.0),
        font_name="Helvetica",
        font_size=12.0,
        color=Color.black(),
    )

    underline_vec = VectorElement(
        svg_path="M 100 498.5 L 200 498.5",
        bbox=BoundingBox(100.0, 498.0, 200.0, 499.0),
        stroke_width=1.0,
        stroke_color=Color.black(),
    )

    interp_output = InterpreterOutput(
        text_elements=[text_el],
        vector_elements=[underline_vec],
        image_elements=[],
    )

    builder = DocumentIRBuilder()
    page = builder.build_page(interp_output, page_width=page_w, page_height=page_h, page_number=1)

    vector_blocks = [b for b in page.blocks if isinstance(b, VectorBlock)]
    assert len(vector_blocks) == 0

    paras = [b for b in page.blocks if isinstance(b, Paragraph)]
    assert len(paras) == 1
    assert any(run.is_underline for run in paras[0].runs)


def test_json_ast_lossless_roundtrip_all_node_types() -> None:
    """Verify lossless JSON AST serialization and deserialization across all DocumentIR node types."""
    import copy
    import json

    from anyconvert.ir import (
        JSON_AST_SCHEMA_VERSION,
        VectorBlock,
        deserialize_document_ir,
        document_ir_from_dict,
        document_ir_to_dict,
        serialize_document_ir,
        validate_json_ast_schema,
    )

    png_bytes = encode_gray_png(2, 2, b"\x00\x7F\xFF\x20")
    accent = Color(12, 95, 210, 0.75)

    nested_table = Table(
        rows=[
            TableRow(
                cells=[
                    TableCell(
                        content=[
                            Paragraph(
                                runs=[TextRun("Inner", "Helvetica", 9.0, Color.black())]
                            )
                        ]
                    )
                ]
            )
        ],
        col_widths=[60.0],
        alignment=Alignment.LEFT,
    )

    outer_table = Table(
        rows=[
            TableRow(
                height=24.0,
                is_header=True,
                cells=[
                    TableCell(
                        content=[
                            Paragraph(
                                runs=[TextRun("Metric", "Helvetica-Bold", 11.0, Color.black(), is_bold=True)],
                                alignment=Alignment.CENTER,
                            )
                        ],
                        col_span=2,
                        row_span=1,
                        width=220.0,
                        height=24.0,
                        background_color=Color(240, 245, 250),
                        borders={
                            "top": Border(style="solid", width=1.5, color=Color.black()),
                            "bottom": Border(style="dashed", width=0.5, color=accent),
                        },
                    )
                ],
            ),
            TableRow(
                height=30.0,
                is_header=False,
                cells=[
                    TableCell(
                        content=[
                            Paragraph(
                                runs=[TextRun("Value", "Helvetica", 10.0, Color.black())],
                            )
                        ],
                        width=100.0,
                        height=30.0,
                    ),
                    TableCell(
                        content=[nested_table],
                        width=120.0,
                        height=30.0,
                    ),
                ],
            ),
        ],
        col_widths=[100.0, 120.0],
        alignment=Alignment.CENTER,
        bbox=BoundingBox(72.0, 200.0, 292.0, 260.0),
    )

    p_heading = Paragraph(
        runs=[
            TextRun(
                text="Section 1: Overview",
                font_name="Times-Bold",
                font_size=18.0,
                color=accent,
                is_bold=True,
                is_italic=True,
                is_underline=True,
                is_strikethrough=False,
                tracking=0.25,
                baseline_offset=1.5,
                bbox=BoundingBox(72.0, 80.0, 280.0, 100.0),
            )
        ],
        alignment=Alignment.JUSTIFIED,
        heading_level=HeadingLevel.H1,
        line_spacing=1.3,
        space_before=12.0,
        space_after=6.0,
        indent_left=4.0,
        indent_right=2.0,
        indent_first_line=8.0,
        list_marker="1.",
        list_level=1,
        bbox=BoundingBox(72.0, 80.0, 280.0, 100.0),
    )

    img_block = ImageBlock(
        image_bytes=png_bytes,
        bbox=BoundingBox(72.0, 300.0, 172.0, 400.0),
        alt_text="Sample Raster",
        rotation=15.0,
        format="png",
        pixel_width=2,
        pixel_height=2,
    )

    vec_block = VectorBlock(
        svg_path="M 72 420 L 200 420 L 200 480 Z",
        bbox=BoundingBox(72.0, 420.0, 200.0, 480.0),
        fill_color=Color(255, 200, 0, 0.5),
        stroke_color=Color.black(),
        stroke_width=2.0,
        fill_rule="evenodd",
        fill_alpha=0.5,
        stroke_alpha=0.9,
        line_cap=1,
        line_join=2,
        miter_limit=8.0,
        dash_array=[4.0, 2.0],
        dash_phase=1.0,
    )

    page1 = DocumentPage(
        page_number=1,
        width=612.0,
        height=792.0,
        margin_top=60.0,
        margin_bottom=60.0,
        margin_left=72.0,
        margin_right=72.0,
        blocks=[p_heading, outer_table, img_block, vec_block],
        header=PageHeaderFooter(
            content=[Paragraph(runs=[TextRun("Top Header", "Helvetica", 9.0, Color.black())])],
            is_footer=False,
        ),
        footer=PageHeaderFooter(
            content=[Paragraph(runs=[TextRun("Page 1", "Helvetica", 9.0, Color.black())])],
            is_footer=True,
        ),
    )

    doc_ir = DocumentIR(
        pages=[page1],
        metadata={"Title": "JSON AST Spec", "Author": "Data Pipeline"},
    )

    # 1. Serialize to JSON string and validate AST structure
    json_str = serialize_document_ir(doc_ir, indent=2)
    parsed = json.loads(json_str)
    validate_json_ast_schema(parsed)

    assert parsed["schema_version"] == JSON_AST_SCHEMA_VERSION
    assert parsed["type"] == "document"
    assert parsed["metadata"]["Title"] == "JSON AST Spec"
    assert len(parsed["pages"]) == 1
    p0 = parsed["pages"][0]
    assert p0["margins"] == {"top": 60.0, "bottom": 60.0, "left": 72.0, "right": 72.0}
    assert p0["blocks"][0]["text"] == "Section 1: Overview"
    assert p0["blocks"][0]["runs"][0]["color"]["hex"] == "#0C5FD2"
    assert p0["blocks"][2]["mime_type"] == "image/png"
    assert isinstance(p0["blocks"][2]["data_base64"], str)

    # 2. Lossless round-trip from str and UTF-8 bytes
    reconstructed = deserialize_document_ir(json_str)
    reconstructed_bytes = deserialize_document_ir(json_str.encode("utf-8"))
    assert reconstructed == doc_ir
    assert reconstructed_bytes == doc_ir

    # 3. Lightweight text-only AST mode (include_images=False)
    lite_dict = document_ir_to_dict(doc_ir, include_images=False)
    assert lite_dict["pages"][0]["blocks"][2]["data_base64"] is None
    lite_ir = document_ir_from_dict(lite_dict, validate=False)
    lite_img = lite_ir.pages[0].blocks[2]
    assert isinstance(lite_img, ImageBlock)
    assert lite_img.image_bytes == b""
    assert lite_img.alt_text == "Sample Raster"

    # 4. Hex color shorthand acceptance during deserialization
    hex_variant = copy.deepcopy(parsed)
    hex_variant["pages"][0]["blocks"][0]["runs"][0]["color"] = "#0C5FD2"
    hex_ir = document_ir_from_dict(hex_variant)
    hex_para = hex_ir.pages[0].blocks[0]
    assert isinstance(hex_para, Paragraph)
    assert hex_para.runs[0].color == Color(12, 95, 210, 1.0)

    # 5. Compact JSON & ensure_ascii options
    compact = serialize_document_ir(doc_ir, indent=None, ensure_ascii=True)
    assert "\n" not in compact
    assert deserialize_document_ir(compact) == doc_ir


def test_json_ast_schema_validation_errors() -> None:
    """Verify strict schema and invariant rejections on malformed JSON AST payloads."""
    from anyconvert.exceptions import SerializationError
    from anyconvert.ir import (
        deserialize_document_ir,
        document_ir_from_dict,
        document_ir_to_dict,
        serialize_document_ir,
    )

    base_valid = document_ir_to_dict(
        DocumentIR(
            pages=[
                DocumentPage(
                    page_number=1,
                    width=612.0,
                    height=792.0,
                    blocks=[Paragraph(runs=[TextRun("Ok", "Helvetica", 11.0, Color.black())])],
                )
            ]
        )
    )

    # Malformed JSON and invalid UTF-8
    with pytest.raises(SerializationError):
        deserialize_document_ir("{not valid json")
    with pytest.raises(SerializationError):
        deserialize_document_ir(b"\xff\xfe\xfd")

    # Unsupported schema_version
    bad_ver = dict(base_valid, schema_version="9.9")
    with pytest.raises(SerializationError, match="schema_version"):
        document_ir_from_dict(bad_ver)

    # Wrong root type
    bad_root = dict(base_valid, type="not_a_document")
    with pytest.raises(SerializationError, match=r"\$\.type"):
        document_ir_from_dict(bad_root)

    # Boolean masquerading as int (Python bool is subclass of int)
    bad_bool_page = dict(base_valid, pages=[dict(base_valid["pages"][0], page_number=True)])
    with pytest.raises(SerializationError, match="expected int"):
        document_ir_from_dict(bad_bool_page)

    # Unknown block type
    bad_block = dict(
        base_valid,
        pages=[dict(base_valid["pages"][0], blocks=[{"type": "video"}])],
    )
    with pytest.raises(SerializationError, match="unsupported block type"):
        document_ir_from_dict(bad_block)

    # Invalid Base64 payload on ImageBlock
    bad_img = dict(
        base_valid,
        pages=[
            dict(
                base_valid["pages"][0],
                blocks=[
                    {
                        "type": "image",
                        "format": "png",
                        "bbox": {"x0": 0.0, "y0": 0.0, "x1": 10.0, "y1": 10.0},
                        "data_base64": "!!!not-base64!!!",
                    }
                ],
            )
        ],
    )
    with pytest.raises(SerializationError, match="Base64"):
        document_ir_from_dict(bad_img)

    # Invalid bounding box (x1 < x0)
    bad_bbox = dict(
        base_valid,
        pages=[
            dict(
                base_valid["pages"][0],
                blocks=[
                    {
                        "type": "vector",
                        "svg_path": "M 0 0 L 1 1",
                        "bbox": {"x0": 20.0, "y0": 0.0, "x1": 10.0, "y1": 10.0},
                    }
                ],
            )
        ],
    )
    with pytest.raises(SerializationError, match="invalid bbox bounds"):
        document_ir_from_dict(bad_bbox)

    # Non-finite float rejected during serialization (RFC 8259 allow_nan=False)
    nan_doc = DocumentIR(
        pages=[
            DocumentPage(
                page_number=1,
                width=612.0,
                height=792.0,
                blocks=[
                    Paragraph(
                        runs=[TextRun("NaN", "Helvetica", 11.0, Color.black(), tracking=float("nan"))]
                    )
                ],
            )
        ]
    )
    with pytest.raises(SerializationError):
        serialize_document_ir(nan_doc)

    # Empty pages rejected when validate=True, accepted structurally when validate=False
    empty_dict = dict(base_valid, pages=[])
    with pytest.raises(IRValidationError):
        document_ir_from_dict(empty_dict, validate=True)
    empty_ir = document_ir_from_dict(empty_dict, validate=False)
    assert empty_ir.pages == []


