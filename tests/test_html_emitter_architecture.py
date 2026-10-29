from __future__ import annotations

import pytest

from anyconvert.common.color import Color
from anyconvert.common.geometry import BoundingBox
from anyconvert.emitters.base import ConversionMode
from anyconvert.emitters.html import (
    HTMLEmitter,
    build_default_css,
)
from anyconvert.emitters.html.css import (
    BASE_RESET_CSS,
    CANVAS_MODE_CSS,
    CORE_CSS_VARIABLES,
    FLOW_MODE_CSS,
    PRINT_MEDIA_CSS,
)
from anyconvert.exceptions import SerializationError
from anyconvert.ir.model import (
    DocumentIR,
    DocumentPage,
    HeadingLevel,
    Paragraph,
    TextRun,
    VectorBlock,
)


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


def test_html_emitter_flow_mode_basic() -> None:
    """Test HTMLEmitter rendering in FLOW mode with semantic elements."""
    p1 = Paragraph(
        runs=[TextRun("Introduction to Antigravity", "Helvetica", 20.0, Color.black(), is_bold=True)],
        heading_level=HeadingLevel.H1,
    )
    p2 = Paragraph(
        runs=[
            TextRun("This is standard flow text with ", "Helvetica", 11.0, Color.black()),
            TextRun("bold formatting", "Helvetica", 11.0, Color.black(), is_bold=True),
            TextRun(" and ", "Helvetica", 11.0, Color.black()),
            TextRun("italics", "Helvetica", 11.0, Color.black(), is_italic=True),
            TextRun(".", "Helvetica", 11.0, Color.black()),
        ],
    )
    page = DocumentPage(page_number=1, width=612.0, height=792.0, blocks=[p1, p2])
    doc_ir = DocumentIR(pages=[page], metadata={"Title": "Sample Document"})

    emitter = HTMLEmitter()
    html_bytes = emitter.emit(doc_ir, mode=ConversionMode.FLOW)
    html_str = html_bytes.decode("utf-8")

    assert "<!DOCTYPE html>" in html_str
    assert '<html lang="en">' in html_str
    assert "<title>Sample Document</title>" in html_str
    assert '<main class="document-flow">' in html_str
    assert "<h1><strong>Introduction to Antigravity</strong></h1>" in html_str
    assert "<strong>bold formatting</strong>" in html_str
    assert "<em>italics</em>" in html_str


def test_html_emitter_canvas_mode_basic() -> None:
    """Test HTMLEmitter rendering in CANVAS mode with positioned elements."""
    p = Paragraph(
        runs=[TextRun("Canvas Absolute Text", "Arial", 14.0, Color.black())],
        bbox=BoundingBox(100.0, 150.0, 300.0, 170.0),
    )
    vec = VectorBlock(
        svg_path="M 50 50 L 150 50 L 150 150 Z",
        bbox=BoundingBox(50.0, 50.0, 150.0, 150.0),
        fill_color=Color(255, 0, 0, 1.0),
        stroke_color=Color(0, 0, 0, 1.0),
        stroke_width=2.0,
    )
    page = DocumentPage(page_number=1, width=612.0, height=792.0, blocks=[p, vec])
    doc_ir = DocumentIR(pages=[page])

    emitter = HTMLEmitter()
    html_bytes = emitter.emit(doc_ir, mode=ConversionMode.CANVAS)
    html_str = html_bytes.decode("utf-8")

    assert '<div class="canvas-wrapper">' in html_str
    assert '<div id="page-1" class="canvas-page" style="width: 612.0pt; height: 792.0pt;">' in html_str
    assert '<svg class="canvas-vector"' in html_str
    assert 'left: 100.0pt; top: 150.0pt;' in html_str
    assert "Canvas Absolute Text" in html_str


def test_html_emitter_empty_doc_raises() -> None:
    """Test that HTMLEmitter raises SerializationError on empty DocumentIR."""
    doc_ir = DocumentIR(pages=[])
    emitter = HTMLEmitter()
    with pytest.raises(SerializationError):
        emitter.emit(doc_ir)
