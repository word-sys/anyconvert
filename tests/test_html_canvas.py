"""Tests for HTML5 Pixel-Accurate Canvas Mode Generation (Step 28)."""

from __future__ import annotations

from typing import List

import pytest

from anyconvert.common.color import Color
from anyconvert.common.geometry import BoundingBox
from anyconvert.emitters.base import ConversionMode
from anyconvert.emitters.html.canvas import CanvasHTMLRenderer, render_canvas_body
from anyconvert.emitters.html.emitter import HTMLEmitter
from anyconvert.ir.model import (
    BlockNode,
    Border,
    DocumentIR,
    DocumentPage,
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


def test_canvas_page_dimensions_and_structure() -> None:
    page = DocumentPage(page_number=1, width=595.3, height=841.9, blocks=[])
    doc_ir = DocumentIR(pages=[page])
    html = render_canvas_body(doc_ir)

    assert '<div class="canvas-wrapper">' in html
    assert '<div id="page-1" class="canvas-page" style="width: 595.3pt; height: 841.9pt;">' in html


def test_canvas_text_positioning_and_styles() -> None:
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
    vec1 = VectorBlock(
        svg_path="M 10 10 L 90 90",
        bbox=BoundingBox(10.0, 10.0, 90.0, 90.0),
        stroke_color=Color(255, 0, 0),
        stroke_width=3.5,
        line_cap=1,  # round
        line_join=1,  # round
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


def test_canvas_full_emitter_integration() -> None:
    header = PageHeaderFooter(content=[Paragraph(runs=[_make_run("Header Bar")], bbox=BoundingBox(72, 36, 540, 50))])
    footer = PageHeaderFooter(content=[Paragraph(runs=[_make_run("Footer Page 1")], bbox=BoundingBox(72, 750, 540, 764))])
    page = DocumentPage(
        page_number=1,
        width=612.0,
        height=792.0,
        blocks=[Paragraph(runs=[_make_run("Visual canvas text")], bbox=BoundingBox(100, 200, 300, 220))],
        header=header,
        footer=footer,
    )
    doc_ir = DocumentIR(pages=[page], metadata={"Title": "Visual Flyer"})

    emitter = HTMLEmitter()
    output_bytes = emitter.emit(doc_ir, mode=ConversionMode.CANVAS)
    html_str = output_bytes.decode("utf-8")

    assert "<!DOCTYPE html>" in html_str
    assert "<title>Visual Flyer</title>" in html_str
    assert '<div class="canvas-wrapper">' in html_str
    assert '<div id="page-1" class="canvas-page"' in html_str
    assert "Header Bar" in html_str
    assert "Footer Page 1" in html_str
    assert "Visual canvas text" in html_str
