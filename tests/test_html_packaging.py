from __future__ import annotations

import pathlib
from typing import List

import pytest

from anyconvert.common.color import Color
from anyconvert.common.geometry import BoundingBox
from anyconvert.emitters.base import ConversionMode
from anyconvert.emitters.html.emitter import HTMLEmitter
from anyconvert.emitters.html.packaging import (
    HTMLPackager,
    extract_embedded_images,
    is_self_contained,
    package_html,
)
from anyconvert.ir.model import (
    BlockNode,
    DocumentIR,
    DocumentPage,
    ImageBlock,
    Paragraph,
    TextRun,
    VectorBlock,
)


def _make_sample_doc() -> DocumentIR:
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
    doc_ir = _make_sample_doc()
    packager = HTMLPackager(offline_csp=True)
    html = packager.package(doc_ir, mode=ConversionMode.FLOW)

    assert "<!DOCTYPE html>" in html
    assert "<title>Annual Financial Report</title>" in html
    assert '<meta name="generator" content="anyconvert 0.1.0">' in html
    assert '<meta name="author" content="Acme Corp Finance Team">' in html
    assert '<meta name="description" content="Quarterly metrics and projections">' in html
    assert '<meta name="keywords" content="finance, report, 2026, metrics">' in html
    assert '<meta name="date" content="2026-10-29">' in html
    assert '<meta http-equiv="Content-Security-Policy"' in html
    assert "default-src 'none';" in html
    assert "img-src 'self' data:;" in html


def test_self_contained_verification_success() -> None:
    doc_ir = _make_sample_doc()
    html = package_html(doc_ir, mode=ConversionMode.FLOW)

    assert is_self_contained(html) is True

    packager = HTMLPackager()
    valid, violations = packager.verify_self_contained(html)
    assert valid is True
    assert len(violations) == 0


def test_self_contained_verification_detects_violations() -> None:
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

    packager = HTMLPackager()
    valid, violations = packager.verify_self_contained(leaky_html)
    assert valid is False
    assert len(violations) == 4
    assert any("stylesheet" in v for v in violations)
    assert any("@import" in v for v in violations)
    assert any("image" in v for v in violations)
    assert any("script" in v for v in violations)


def test_extract_embedded_images() -> None:
    doc_ir = _make_sample_doc()
    html = package_html(doc_ir, mode=ConversionMode.FLOW)

    extracted = extract_embedded_images(html)
    assert len(extracted) == 1
    mime, data = extracted[0]
    assert mime == "image/png"
    assert data.startswith(b"\x89PNG")


def test_inline_resources_from_disk(tmp_path: pathlib.Path) -> None:
    # Prepare dummy files
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


def test_emitter_default_self_contained_canvas_and_flow() -> None:
    doc_ir = _make_sample_doc()
    emitter = HTMLEmitter()

    # Flow mode
    flow_bytes = emitter.emit(doc_ir, mode=ConversionMode.FLOW)
    flow_str = flow_bytes.decode("utf-8")
    assert is_self_contained(flow_str) is True
    assert "Annual Financial Report" in flow_str

    # Canvas mode
    canvas_bytes = emitter.emit(doc_ir, mode=ConversionMode.CANVAS)
    canvas_str = canvas_bytes.decode("utf-8")
    assert is_self_contained(canvas_str) is True
    assert "Annual Financial Report" in canvas_str
