"""Comprehensive tests for HTML Emitter API and CLI Integration (Step 30)."""

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
from anyconvert.emitters.base import ConversionMode
from anyconvert.emitters.html import (
    HTMLEmitter,
    is_self_contained,
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
