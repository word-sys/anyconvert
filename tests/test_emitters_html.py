"""Comprehensive test suite for HTML5 Emitter (Architecture, Flow, Canvas, Packaging, API/CLI)."""

from __future__ import annotations

import pathlib
from typing import List

import pytest

from anyconvert.api import (
    SUPPORTED_FORMATS,
    _get_emitter,
    convert,
    convert_bytes,
)
from anyconvert.cli import main
from anyconvert.common.color import Color
from anyconvert.common.geometry import BoundingBox
from anyconvert.emitters.base import ConversionMode
from anyconvert.emitters.html import (
    CanvasHTMLRenderer,
    FlowHTMLRenderer,
    HTMLEmitter,
    HTMLPackager,
    build_default_css,
    extract_embedded_images,
    is_self_contained,
    package_html,
    render_canvas_body,
    render_flow_body,
)
from anyconvert.exceptions import SerializationError
from anyconvert.ir.model import (
    Alignment,
    BlockNode,
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


def _make_run(
    text: str,
    font_name: str = "Helvetica",
    font_size: float = 12.0,
    color: Color = Color.black(),
    is_bold: bool = False,
    is_italic: bool = False,
    is_underline: bool = False,
    is_strikethrough: bool = False,
    tracking: float = 0.0,
    baseline_offset: float = 0.0,
) -> TextRun:
    return TextRun(
        text=text,
        font_name=font_name,
        font_size=font_size,
        color=color,
        is_bold=is_bold,
        is_italic=is_italic,
        is_underline=is_underline,
        is_strikethrough=is_strikethrough,
        tracking=tracking,
        baseline_offset=baseline_offset,
    )


def _build_test_pdf() -> bytes:
    """Build a minimal valid PDF containing headings, body text, and a vector box."""
    objs: List[bytes] = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Count 1 /Kids [3 0 R] >>\nendobj\n",
        (
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 << /Type /Font "
            b"/Subtype /Type1 /BaseFont /Helvetica >> >> >> >>\nendobj\n"
        ),
        (
            b"4 0 obj\n<< /Length 160 >>\nstream\n"
            b"BT /F1 16 Tf 72 700 Td (HTML5 Emitter Integration Test) Tj ET\n"
            b"BT /F1 12 Tf 72 650 Td (Verifying pure-Python HTML generation.) Tj ET\n"
            b"72 500 100 50 re S\n"
            b"endstream\nendobj\n"
        ),
    ]
    offsets = [0]
    out = bytearray(b"%PDF-1.4\n")
    for obj in objs:
        offsets.append(len(out))
        out.extend(obj)
    xref_offset = len(out)
    out.extend(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    out.extend(
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return bytes(out)


# ==============================================================================
# 1. Architecture & CSS Stylesheet Tests
# ==============================================================================

def test_html_emitter_import_and_init() -> None:
    """Test importing and initializing HTMLEmitter."""
    emitter = HTMLEmitter()
    assert isinstance(emitter, HTMLEmitter)


def test_build_default_css_flow_and_canvas() -> None:
    """Test CSS generation for FLOW and CANVAS modes with variables and print styles."""
    flow_css = build_default_css(ConversionMode.FLOW, include_print=True)
    assert "--font-sans:" in flow_css
    assert ".document-flow" in flow_css
    assert "@media print" in flow_css

    canvas_css = build_default_css(ConversionMode.CANVAS, include_print=False)
    assert "--font-sans:" in canvas_css
    assert ".canvas-page" in canvas_css
    assert "@media print" not in canvas_css


def test_html_emitter_empty_doc_raises() -> None:
    """Test that HTMLEmitter raises SerializationError on empty DocumentIR."""
    doc_ir = DocumentIR(pages=[])
    emitter = HTMLEmitter()
    with pytest.raises(SerializationError):
        emitter.emit(doc_ir)


# ==============================================================================
# 2. Semantic Flow Mode Tests
# ==============================================================================

def test_headings_generation() -> None:
    """Test heading levels H1 through H6 generation."""
    blocks: List[BlockNode] = [
        Paragraph(runs=[_make_run("Title 1")], heading_level=HeadingLevel.H1),
        Paragraph(runs=[_make_run("Subtitle 2")], heading_level=HeadingLevel.H2),
        Paragraph(runs=[_make_run("Section 3")], heading_level=HeadingLevel.H3),
        Paragraph(runs=[_make_run("Subsection 4")], heading_level=HeadingLevel.H4),
        Paragraph(runs=[_make_run("Minor 5")], heading_level=HeadingLevel.H5),
        Paragraph(runs=[_make_run("Detail 6")], heading_level=HeadingLevel.H6),
    ]
    pages = [DocumentPage(page_number=1, width=612.0, height=792.0, blocks=blocks)]
    doc_ir = DocumentIR(pages=pages)
    html = render_flow_body(doc_ir)

    assert "<h1>Title 1</h1>" in html
    assert "<h2>Subtitle 2</h2>" in html
    assert "<h3>Section 3</h3>" in html
    assert "<h4>Subsection 4</h4>" in html
    assert "<h5>Minor 5</h5>" in html
    assert "<h6>Detail 6</h6>" in html


def test_inline_text_formatting() -> None:
    """Test inline styles: bold, italic, underline, strikethrough, super, sub, code, color, links."""
    p = Paragraph(
        runs=[
            _make_run("Normal, "),
            _make_run("Bold, ", is_bold=True),
            _make_run("Italic, ", is_italic=True),
            _make_run("Underlined, ", is_underline=True),
            _make_run("Struck, ", is_strikethrough=True),
            _make_run("Super, ", baseline_offset=3.0),
            _make_run("Sub, ", baseline_offset=-3.0),
            _make_run("CodeFont, ", font_name="CourierNew"),
            _make_run("RedText, ", color=Color(255, 0, 0)),
            _make_run("https://example.com"),
        ],
        alignment=Alignment.CENTER,
    )
    doc_ir = DocumentIR(pages=[DocumentPage(page_number=1, width=600.0, height=800.0, blocks=[p])])
    html = render_flow_body(doc_ir)

    assert 'style="text-align: center;"' in html
    assert "Normal, " in html
    assert "<strong>Bold, </strong>" in html
    assert "<em>Italic, </em>" in html
    assert "<u>Underlined, </u>" in html
    assert "<s>Struck, </s>" in html
    assert "<sup>Super, </sup>" in html
    assert "<sub>Sub, </sub>" in html
    assert "<code>CodeFont, </code>" in html
    assert 'style="color: #ff0000;"' in html
    assert '<a href="https://example.com" rel="noopener">' in html


def test_unordered_and_ordered_lists() -> None:
    """Test grouping of contiguous list items into ul and ol."""
    blocks: List[BlockNode] = [
        Paragraph(runs=[_make_run("• First bullet item")]),
        Paragraph(runs=[_make_run("• Second bullet item")]),
        Paragraph(runs=[_make_run("Ordinary paragraph in between")]),
        Paragraph(runs=[_make_run("1. Step one")]),
        Paragraph(runs=[_make_run("2. Step two")]),
    ]
    doc_ir = DocumentIR(pages=[DocumentPage(page_number=1, width=600.0, height=800.0, blocks=blocks)])
    html = render_flow_body(doc_ir)

    assert '<ul class="flow-list">' in html
    assert "<li>First bullet item</li>" in html
    assert "<li>Second bullet item</li>" in html
    assert "<p>Ordinary paragraph in between</p>" in html
    assert '<ol class="flow-list">' in html
    assert "<li>Step one</li>" in html
    assert "<li>Step two</li>" in html


def test_table_generation_flow() -> None:
    """Test table generation in flow mode with thead, tbody, th, td, and spanning."""
    header_row = TableRow(
        is_header=True,
        cells=[
            TableCell(content=[Paragraph(runs=[_make_run("Col A")])]),
            TableCell(content=[Paragraph(runs=[_make_run("Col B")])], col_span=2),
        ],
    )
    data_row = TableRow(
        is_header=False,
        cells=[
            TableCell(content=[Paragraph(runs=[_make_run("Data 1")])]),
            TableCell(content=[Paragraph(runs=[_make_run("Data 2")])], background_color=Color(240, 240, 240)),
            TableCell(content=[Paragraph(runs=[_make_run("Data 3")])], row_span=2),
        ],
    )
    table = Table(rows=[header_row, data_row])
    doc_ir = DocumentIR(pages=[DocumentPage(page_number=1, width=600.0, height=800.0, blocks=[table])])
    html = render_flow_body(doc_ir)

    assert '<table class="pure-table">' in html
    assert "<thead>" in html
    assert "<th>Col A</th>" in html
    assert '<th colspan="2">Col B</th>' in html
    assert "</thead>" in html
    assert "<tbody>" in html
    assert "<td>Data 1</td>" in html
    assert '<td style="background-color: #f0f0f0;">Data 2</td>' in html
    assert '<td rowspan="2">Data 3</td>' in html
    assert "</tbody>" in html


def test_image_and_vector_generation_flow() -> None:
    """Test image figure and inline SVG vectors in flow mode."""
    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
    img = ImageBlock(
        image_bytes=png_bytes,
        bbox=BoundingBox(50, 50, 150, 150),
        alt_text="A sample diagram",
        format="png",
    )
    vec = VectorBlock(
        svg_path="M 0 0 L 100 100",
        bbox=BoundingBox(10, 20, 110, 120),
        stroke_color=Color(0, 0, 255),
        stroke_width=2.0,
    )
    doc_ir = DocumentIR(pages=[DocumentPage(page_number=1, width=600.0, height=800.0, blocks=[img, vec])])
    html = render_flow_body(doc_ir)

    assert '<figure class="flow-figure">' in html
    assert 'src="data:image/png;base64,' in html
    assert 'alt="A sample diagram"' in html
    assert "<figcaption>A sample diagram</figcaption>" in html
    assert '<div class="flow-vector">' in html
    assert '<svg viewBox="10.0 20.0 100.0 100.0"' in html
    assert 'd="M 0 0 L 100 100"' in html
    assert 'stroke="#0000ff"' in html
    assert 'stroke-width="2.00"' in html


# ==============================================================================
# 3. Pixel-Accurate Canvas Mode Tests
# ==============================================================================

def test_canvas_page_dimensions_and_structure() -> None:
    """Test canvas page wrapper and exact dimension styling."""
    page = DocumentPage(page_number=1, width=595.3, height=841.9, blocks=[])
    doc_ir = DocumentIR(pages=[page])
    html = render_canvas_body(doc_ir)

    assert '<div class="canvas-wrapper">' in html
    assert '<div id="page-1" class="canvas-page" style="width: 595.3pt; height: 841.9pt;">' in html


def test_canvas_text_positioning_and_styles() -> None:
    """Test canvas text absolute coordinates, tracking, font, and baseline offset."""
    p = Paragraph(
        runs=[
            _make_run("Main Heading", font_name="TimesNewRoman", font_size=24.0, is_bold=True),
            _make_run(" Subtext", font_name="Arial", font_size=12.0, is_italic=True, color=Color(0, 128, 255, 0.8)),
            _make_run(" [Tracked]", tracking=1.5),
            _make_run(" [Super]", baseline_offset=4.0),
        ],
        bbox=BoundingBox(72.0, 100.0, 400.0, 130.0),
    )
    blocks: List[BlockNode] = [p]
    page = DocumentPage(page_number=1, width=612.0, height=792.0, blocks=blocks)
    html = render_canvas_body(DocumentIR(pages=[page]))

    assert '<div class="canvas-element canvas-text"' in html
    assert "left: 72.0pt;" in html
    assert "top: 100.0pt;" in html
    assert "width: 328.0pt;" in html
    assert "font-family: 'TimesNewRoman', sans-serif;" in html
    assert "font-weight: bold;" in html
    assert "font-style: italic;" in html
    assert "color: #0080ff;" in html
    assert "opacity: 0.80;" in html
    assert "letter-spacing: 1.50pt;" in html
    assert "vertical-align: 4.0pt;" in html


def test_canvas_vector_layer() -> None:
    """Test canvas SVG layer with stroke attributes, fill rules, and dash patterns."""
    vec1 = VectorBlock(
        svg_path="M 10 10 L 90 90",
        bbox=BoundingBox(10.0, 10.0, 90.0, 90.0),
        stroke_color=Color(255, 0, 0),
        stroke_width=3.5,
        line_cap=1,
        line_join=1,
        dash_array=[5.0, 2.5],
    )
    vec2 = VectorBlock(
        svg_path="M 100 100 H 200 V 200 Z",
        bbox=BoundingBox(100.0, 100.0, 200.0, 200.0),
        fill_color=Color(0, 255, 0, 0.5),
        fill_rule="evenodd",
    )
    blocks: List[BlockNode] = [vec1, vec2]
    page = DocumentPage(page_number=1, width=600.0, height=800.0, blocks=blocks)
    html = render_canvas_body(DocumentIR(pages=[page]))

    assert '<svg class="canvas-vector" viewBox="0 0 600.0 800.0" width="600.0pt" height="800.0pt">' in html
    assert 'd="M 10 10 L 90 90"' in html
    assert 'stroke="#ff0000"' in html
    assert 'stroke-width="3.50"' in html
    assert 'stroke-linecap="round"' in html
    assert 'stroke-linejoin="round"' in html
    assert 'stroke-dasharray="5.00 2.50"' in html
    assert 'd="M 100 100 H 200 V 200 Z"' in html
    assert 'fill="#00ff00"' in html
    assert 'fill-opacity="0.50"' in html
    assert 'fill-rule="evenodd"' in html


def test_canvas_image_positioning_and_rotation() -> None:
    """Test canvas image positioning and affine matrix rotation."""
    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
    img = ImageBlock(
        image_bytes=png_bytes,
        bbox=BoundingBox(50.0, 80.0, 250.0, 230.0),
        alt_text="Canvas Chart",
        rotation=45.0,
        format="png",
    )
    blocks: List[BlockNode] = [img]
    page = DocumentPage(page_number=1, width=600.0, height=800.0, blocks=blocks)
    html = render_canvas_body(DocumentIR(pages=[page]))

    assert '<img class="canvas-element canvas-image"' in html
    assert "left: 50.0pt;" in html
    assert "top: 80.0pt;" in html
    assert "width: 200.0pt;" in html
    assert "height: 150.0pt;" in html
    assert "transform: matrix(" in html
    assert 'src="data:image/png;base64,' in html
    assert 'alt="Canvas Chart"' in html


def test_canvas_table_layout() -> None:
    """Test canvas table grid positioning with background colors and borders."""
    cell_a = TableCell(
        content=[Paragraph(runs=[_make_run("Header A")])],
        width=100.0,
        height=25.0,
        background_color=Color(220, 220, 220),
        borders={"bottom": Border(style="solid", width=1.5, color=Color(0, 0, 0))},
    )
    cell_b = TableCell(
        content=[Paragraph(runs=[_make_run("Header B")])],
        width=150.0,
        height=25.0,
        col_span=2,
    )
    row = TableRow(cells=[cell_a, cell_b], is_header=True)
    table = Table(
        rows=[row],
        bbox=BoundingBox(50.0, 300.0, 300.0, 350.0),
    )
    blocks: List[BlockNode] = [table]
    page = DocumentPage(page_number=1, width=600.0, height=800.0, blocks=blocks)
    html = render_canvas_body(DocumentIR(pages=[page]))

    assert '<table class="canvas-element canvas-table"' in html
    assert "left: 50.0pt;" in html
    assert "top: 300.0pt;" in html
    assert "width: 250.0pt;" in html
    assert "height: 50.0pt;" in html
    assert "background-color: #dcdcdc;" in html
    assert "border-bottom: 1.5pt solid #000000;" in html
    assert '<th style=' in html
    assert 'colspan="2"' in html
    assert "Header A</span></th>" in html
    assert "Header B</span></th>" in html


# ==============================================================================
# 4. Self-Contained Packaging & Verification Tests
# ==============================================================================

def _make_packaging_sample_doc() -> DocumentIR:
    run = TextRun("Self-contained portable document", "Helvetica", 12.0, Color.black())
    p = Paragraph(runs=[run])
    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
    img = ImageBlock(
        image_bytes=png_bytes,
        bbox=BoundingBox(50, 50, 150, 150),
        alt_text="Sample graphic",
        format="png",
    )
    vec = VectorBlock(
        svg_path="M 0 0 L 100 100",
        bbox=BoundingBox(0, 0, 100, 100),
        stroke_color=Color(0, 0, 0),
        stroke_width=1.0,
    )
    blocks: List[BlockNode] = [p, img, vec]
    page = DocumentPage(page_number=1, width=612.0, height=792.0, blocks=blocks)
    metadata = {
        "Title": "Annual Financial Report",
        "Author": "Acme Corp Finance Team",
        "Subject": "Quarterly metrics and projections",
        "Keywords": "finance, report, 2026, metrics",
        "CreationDate": "2026-10-29",
    }
    return DocumentIR(pages=[page], metadata=metadata)


def test_package_metadata_and_offline_csp() -> None:
    """Test metadata injection and strict offline Content-Security-Policy."""
    doc_ir = _make_packaging_sample_doc()
    packager = HTMLPackager(offline_csp=True)
    html = packager.package(doc_ir, mode=ConversionMode.FLOW)

    assert "<!DOCTYPE html>" in html
    assert "<title>Annual Financial Report</title>" in html
    assert '<meta name="generator" content="anyconvert 0.1.11">' in html
    assert '<meta name="author" content="Acme Corp Finance Team">' in html
    assert '<meta name="description" content="Quarterly metrics and projections">' in html
    assert '<meta name="keywords" content="finance, report, 2026, metrics">' in html
    assert '<meta name="date" content="2026-10-29">' in html
    assert '<meta http-equiv="Content-Security-Policy"' in html
    assert "default-src 'none';" in html
    assert "img-src 'self' data:;" in html


def test_self_contained_verification() -> None:
    """Test self-contained document verification and violation detection."""
    doc_ir = _make_packaging_sample_doc()
    html = package_html(doc_ir, mode=ConversionMode.FLOW)

    assert is_self_contained(html) is True

    leaky_html = (
        '<!DOCTYPE html><html><head>'
        '<link rel="stylesheet" href="https://cdn.example.com/styles.css">'
        '<style>@import url("https://fonts.googleapis.com/css?family=Roboto");</style>'
        '</head><body>'
        '<img src="https://tracker.example.com/pixel.gif">'
        '<script src="https://cdn.example.com/app.js"></script>'
        '</body></html>'
    )
    assert is_self_contained(leaky_html) is False
    valid, violations = HTMLPackager().verify_self_contained(leaky_html)
    assert valid is False
    assert len(violations) == 4


def test_extract_embedded_images() -> None:
    """Test extracting embedded Base64 Data URI images from HTML."""
    doc_ir = _make_packaging_sample_doc()
    html = package_html(doc_ir, mode=ConversionMode.FLOW)

    extracted = extract_embedded_images(html)
    assert len(extracted) == 1
    mime, data = extracted[0]
    assert mime == "image/png"
    assert data.startswith(b"\x89PNG")


def test_inline_resources_from_disk(tmp_path: pathlib.Path) -> None:
    """Test inlining relative stylesheets and local images into self-contained HTML."""
    css_file = tmp_path / "custom.css"
    css_file.write_text("body { background: purple; }", encoding="utf-8")

    png_file = tmp_path / "logo.png"
    sample_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
    png_file.write_bytes(sample_png)

    raw_html = (
        '<html><head>'
        '<link rel="stylesheet" href="custom.css">'
        '</head><body>'
        '<img src="logo.png" alt="Logo">'
        '</body></html>'
    )

    packager = HTMLPackager()
    inlined = packager.inline_resources(raw_html, base_dir=tmp_path)

    assert "custom.css" not in inlined
    assert "body { background: purple; }" in inlined
    assert "data:image/png;base64," in inlined
    assert is_self_contained(inlined) is True


# ==============================================================================
# 5. API & CLI Integration Tests
# ==============================================================================

def test_html_emitter_registration() -> None:
    """Verify that html is in SUPPORTED_FORMATS and _get_emitter instantiates HTMLEmitter."""
    assert "html" in SUPPORTED_FORMATS
    emitter = _get_emitter("html")
    assert isinstance(emitter, HTMLEmitter)
    assert isinstance(_get_emitter(".HTML"), HTMLEmitter)


def test_html_convert_bytes_flow() -> None:
    """Verify convert_bytes to HTML in FLOW mode."""
    pdf_bytes = _build_test_pdf()
    html_bytes = convert_bytes(pdf_bytes, output_format="html", mode="flow")

    assert html_bytes.startswith(b"<!DOCTYPE html>")
    html_str = html_bytes.decode("utf-8")
    assert '<main class="document-flow">' in html_str
    assert "HTML5 Emitter Integration Test" in html_str
    assert is_self_contained(html_str) is True


def test_html_convert_bytes_canvas() -> None:
    """Verify convert_bytes to HTML in CANVAS mode."""
    pdf_bytes = _build_test_pdf()
    html_bytes = convert_bytes(pdf_bytes, output_format="html", mode="canvas")

    assert html_bytes.startswith(b"<!DOCTYPE html>")
    html_str = html_bytes.decode("utf-8")
    assert '<div class="canvas-wrapper">' in html_str
    assert '<div id="page-1" class="canvas-page"' in html_str
    assert "HTML5 Emitter Integration Test" in html_str
    assert is_self_contained(html_str) is True


def test_html_convert_file_to_file_flow(tmp_path: pathlib.Path) -> None:
    """Verify file-to-file conversion via API in FLOW mode."""
    input_pdf = tmp_path / "doc.pdf"
    input_pdf.write_bytes(_build_test_pdf())
    output_html = tmp_path / "doc.html"

    res_bytes = convert(
        input_path=input_pdf,
        output_format="html",
        output_path=output_html,
        mode="flow",
    )

    assert output_html.is_file()
    assert output_html.stat().st_size == len(res_bytes)
    html_str = output_html.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in html_str
    assert '<article id="page-1" class="page-flow">' in html_str
    assert is_self_contained(html_str) is True


def test_html_convert_file_to_file_canvas(tmp_path: pathlib.Path) -> None:
    """Verify file-to-file conversion via API in CANVAS mode."""
    input_pdf = tmp_path / "canvas_doc.pdf"
    input_pdf.write_bytes(_build_test_pdf())
    output_html = tmp_path / "canvas_doc.html"

    res_bytes = convert(
        input_path=input_pdf,
        output_format="html",
        output_path=output_html,
        mode="canvas",
    )

    assert output_html.is_file()
    assert output_html.stat().st_size == len(res_bytes)
    html_str = output_html.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in html_str
    assert '<div class="canvas-wrapper">' in html_str
    assert is_self_contained(html_str) is True


def test_cli_html_flow_conversion(tmp_path: pathlib.Path) -> None:
    """Verify CLI command: anyconvert input.pdf -f html -o output.html."""
    input_pdf = tmp_path / "cli_input.pdf"
    input_pdf.write_bytes(_build_test_pdf())
    output_html = tmp_path / "cli_output.html"

    exit_code = main([str(input_pdf), "-f", "html", "-o", str(output_html)])
    assert exit_code == 0
    assert output_html.is_file()
    html_str = output_html.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in html_str
    assert '<main class="document-flow">' in html_str
    assert is_self_contained(html_str) is True


def test_cli_html_canvas_conversion(tmp_path: pathlib.Path) -> None:
    """Verify CLI command: anyconvert input.pdf -f html -m canvas -o output.html."""
    input_pdf = tmp_path / "cli_canvas.pdf"
    input_pdf.write_bytes(_build_test_pdf())
    output_html = tmp_path / "cli_canvas.html"

    exit_code = main([str(input_pdf), "-f", "html", "-m", "canvas", "-o", str(output_html)])
    assert exit_code == 0
    assert output_html.is_file()
    html_str = output_html.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in html_str
    assert '<div class="canvas-wrapper">' in html_str
    assert is_self_contained(html_str) is True


def test_cli_html_default_output_naming(tmp_path: pathlib.Path) -> None:
    """Verify CLI default output naming: anyconvert report.pdf -f html -> report.html."""
    input_pdf = tmp_path / "report.pdf"
    input_pdf.write_bytes(_build_test_pdf())

    exit_code = main([str(input_pdf), "-f", "html"])
    assert exit_code == 0

    expected_output = tmp_path / "report.html"
    assert expected_output.is_file()
    html_str = expected_output.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in html_str
    assert is_self_contained(html_str) is True
