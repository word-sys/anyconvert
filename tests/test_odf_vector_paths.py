from __future__ import annotations

import pathlib
import xml.etree.ElementTree as ET
import pytest

from anyconvert.common.color import Color
from anyconvert.common.geometry import BoundingBox
from anyconvert.emitters.base import ConversionMode
from anyconvert.emitters.odp import OdpEmitter, render_vector_path_odp
from anyconvert.emitters.odt import OdtEmitter, render_vector_path_odt
from anyconvert.ir.model import (
    DocumentIR,
    DocumentPage,
    Paragraph,
    TextRun,
    VectorBlock,
)
from anyconvert.packaging.odf import ODFPackage


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
    # Round cap, bevel join, dash array [4.0, 2.0], opacity 0.8
    vec = VectorBlock(
        svg_path="M 0 0 L 50 50 Z",
        bbox=BoundingBox(0.0, 0.0, 50.0, 50.0),
        stroke_color=Color(0, 128, 255, 1.0),
        stroke_width=1.5,
        stroke_alpha=0.8,
        line_cap=1,     # round
        line_join=2,    # bevel
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

    # Miter join and square cap
    vec_sq = VectorBlock(
        svg_path="M 0 0 L 20 20 Z",
        bbox=BoundingBox(0.0, 0.0, 20.0, 20.0),
        stroke_color=Color(0, 0, 0, 1.0),
        stroke_width=1.0,
        line_cap=2,     # square
        line_join=0,    # miter
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
