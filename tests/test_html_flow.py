from __future__ import annotations

import pytest

from typing import List

from anyconvert.common.color import Color
from anyconvert.common.geometry import BoundingBox
from anyconvert.emitters.base import ConversionMode
from anyconvert.emitters.html.emitter import HTMLEmitter
from anyconvert.emitters.html.flow import FlowHTMLRenderer, render_flow_body
from anyconvert.ir.model import (
    Alignment,
    BlockNode,
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
    font_name: str = "Calibri",
    font_size: float = 11.0,
    color: Color = Color.black(),
    is_bold: bool = False,
    is_italic: bool = False,
    is_underline: bool = False,
    is_strikethrough: bool = False,
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
        baseline_offset=baseline_offset,
    )


def test_headings_generation() -> None:
    blocks: List[BlockNode] = [
        Paragraph(runs=[_make_run("Title 1")], heading_level=HeadingLevel.H1),
        Paragraph(runs=[_make_run("Subtitle 2")], heading_level=HeadingLevel.H2),
        Paragraph(runs=[_make_run("Section 3")], heading_level=HeadingLevel.H3),
        Paragraph(runs=[_make_run("Subsection 4")], heading_level=HeadingLevel.H4),
        Paragraph(runs=[_make_run("Minor 5")], heading_level=HeadingLevel.H5),
        Paragraph(runs=[_make_run("Detail 6")], heading_level=HeadingLevel.H6),
    ]
    pages = [
        DocumentPage(
            page_number=1,
            width=612.0,
            height=792.0,
            blocks=blocks,
        )
    ]
    doc_ir = DocumentIR(pages=pages)
    html = render_flow_body(doc_ir)

    assert "<h1>Title 1</h1>" in html
    assert "<h2>Subtitle 2</h2>" in html
    assert "<h3>Section 3</h3>" in html
    assert "<h4>Subsection 4</h4>" in html
    assert "<h5>Minor 5</h5>" in html
    assert "<h6>Detail 6</h6>" in html


def test_inline_text_formatting() -> None:
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
    blocks: List[BlockNode] = [
        Paragraph(runs=[_make_run("• First bullet item")]),
        Paragraph(runs=[_make_run("• Second bullet item")]),
        Paragraph(runs=[_make_run("Ordinary paragraph in between")]),
        Paragraph(runs=[_make_run("1. Step one")]),
        Paragraph(runs=[_make_run("2. Step two")]),
    ]
    doc_ir = DocumentIR(pages=[DocumentPage(page_number=1, width=600.0, height=800.0, blocks=blocks)])
    html = render_flow_body(doc_ir)

    # Check unordered list grouping
    assert '<ul class="flow-list">' in html
    assert "<li>First bullet item</li>" in html
    assert "<li>Second bullet item</li>" in html

    # Check separation by standard paragraph
    assert "<p>Ordinary paragraph in between</p>" in html

    # Check ordered list grouping
    assert '<ol class="flow-list">' in html
    assert "<li>Step one</li>" in html
    assert "<li>Step two</li>" in html


def test_table_generation() -> None:
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


def test_image_and_vector_generation() -> None:
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

    # Check figure and image
    assert '<figure class="flow-figure">' in html
    assert 'src="data:image/png;base64,' in html
    assert 'alt="A sample diagram"' in html
    assert "<figcaption>A sample diagram</figcaption>" in html

    # Check vector block
    assert '<div class="flow-vector">' in html
    assert '<svg viewBox="10.0 20.0 100.0 100.0"' in html
    assert 'd="M 0 0 L 100 100"' in html
    assert 'stroke="#0000ff"' in html
    assert 'stroke-width="2.00"' in html


def test_page_header_footer_and_full_emitter() -> None:
    header = PageHeaderFooter(content=[Paragraph(runs=[_make_run("Confidential Report")])], is_footer=False)
    footer = PageHeaderFooter(content=[Paragraph(runs=[_make_run("Page 1 of 10")])], is_footer=True)
    page = DocumentPage(
        page_number=1,
        width=612.0,
        height=792.0,
        blocks=[Paragraph(runs=[_make_run("Body content here.")])],
        header=header,
        footer=footer,
    )
    doc_ir = DocumentIR(pages=[page], metadata={"Title": "Quarterly Report"})

    emitter = HTMLEmitter()
    raw_bytes = emitter.emit(doc_ir, mode=ConversionMode.FLOW)
    html_text = raw_bytes.decode("utf-8")

    assert "<!DOCTYPE html>" in html_text
    assert "<title>Quarterly Report</title>" in html_text
    assert '<article id="page-1" class="page-flow">' in html_text
    assert '<header class="page-header" role="doc-pageheader">' in html_text
    assert "Confidential Report" in html_text
    assert '<footer class="page-footer" role="doc-pagefooter">' in html_text
    assert "Page 1 of 10" in html_text
    assert "<p>Body content here.</p>" in html_text
    assert "@media print" in html_text
