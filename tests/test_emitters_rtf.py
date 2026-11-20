"""Tests for pure-Python RTF 1.9.1 document emitter."""

from __future__ import annotations

import pathlib
from typing import List

import pytest

from anyconvert.api import SUPPORTED_FORMATS, _get_emitter, convert, convert_bytes
from anyconvert.cli import main
from anyconvert.common.color import Color
from anyconvert.common.geometry import BoundingBox
from anyconvert.emitters.rtf import (
    RtfColorTable,
    RtfEmitter,
    RtfFontTable,
    RtfStyleSheet,
    classify_rtf_font_family,
    clean_rtf_font_name,
    escape_rtf_text,
)
from anyconvert.exceptions import SerializationError
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
)


def assert_valid_rtf(rtf_bytes: bytes) -> str:
    """Assert 7-bit ASCII compliance, RTF 1.9.1 header, and balanced brace depth."""
    assert isinstance(rtf_bytes, bytes)
    assert all(b < 128 for b in rtf_bytes), "RTF stream contains non-ASCII bytes"
    text = rtf_bytes.decode("ascii")
    stripped = text.strip()
    assert stripped.startswith("{\\rtf1\\ansi")
    assert stripped.endswith("}")

    depth = 0
    i = 0
    n = len(stripped)
    while i < n:
        ch = stripped[i]
        if ch == "\\" and i + 1 < n:
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            assert depth >= 0, "Unbalanced closing brace in RTF stream"
        i += 1
    assert depth == 0, f"Unclosed RTF group braces remaining: depth={depth}"
    return text


def _build_minimal_pdf() -> bytes:
    """Build a minimal valid PDF for CLI and API RTF conversion tests."""
    objs: List[bytes] = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Count 1 /Kids [3 0 R] >>\nendobj\n",
        (
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 << /Type /Font "
            b"/Subtype /Type1 /BaseFont /Helvetica >> >> >> >>\nendobj\n"
        ),
        (
            b"4 0 obj\n<< /Length 70 >>\nstream\n"
            b"BT /F1 14 Tf 72 700 Td (RTF Architecture Verification) Tj ET\n"
            b"endstream\nendobj\n"
        ),
    ]
    out = bytearray(b"%PDF-1.4\n")
    offs = [0]
    for obj in objs:
        offs.append(len(out))
        out.extend(obj)
    xref_pos = len(out)
    out.extend(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for o in offs[1:]:
        out.extend(f"{o:010d} 00000 n \n".encode("ascii"))
    out.extend(
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("ascii")
    )
    return bytes(out)


def test_rtf_tables_and_escaping_helpers() -> None:
    """Verify font table, color table, stylesheet, and 7-bit ASCII text escaping."""
    assert clean_rtf_font_name("ABCDEF+Helvetica-Bold") == "Helvetica"
    assert clean_rtf_font_name("TimesNewRoman,Italic") == "TimesNewRoman"
    assert clean_rtf_font_name("") == "Helvetica"

    assert classify_rtf_font_family("Courier New") == r"\fmodern"
    assert classify_rtf_font_family("Times New Roman") == r"\froman"
    assert classify_rtf_font_family("Helvetica") == r"\fswiss"
    assert classify_rtf_font_family("Symbol") == r"\ftech"
    assert classify_rtf_font_family("CustomDisplay") == r"\fnil"

    ft = RtfFontTable("Helvetica")
    assert ft.get_index("ABCDEF+Helvetica-Bold") == 0
    assert ft.get_index("Times New Roman") == 1
    assert ft.get_index("Courier New") == 2
    ft_rtf = ft.to_rtf()
    assert r"\fonttbl" in ft_rtf
    assert r"\f0\fswiss\fcharset0 Helvetica;" in ft_rtf
    assert r"\f1\froman\fcharset0 Times New Roman;" in ft_rtf
    assert r"\f2\fmodern\fcharset0 Courier New;" in ft_rtf

    ct = RtfColorTable()
    assert ct.register(None) == 0
    assert ct.register(Color(0, 0, 0)) == 1
    assert ct.register(Color(200, 30, 40)) == 2
    assert ct.register(Color(200, 30, 40)) == 2
    assert ct.to_rtf() == r"{\colortbl ;\red0\green0\blue0;\red200\green30\blue40;}"

    ss = RtfStyleSheet().to_rtf()
    assert r"\stylesheet" in ss
    assert "Normal;" in ss
    assert "heading 1;" in ss
    assert "heading 6;" in ss

    assert escape_rtf_text(r"A\B{C}D") == r"A\\B\{C\}D"
    assert escape_rtf_text("Line1\n\tLine2") == r"Line1\line \tab Line2"
    # BMP non-ASCII (Turkish 'ş' = U+015F = 351)
    assert escape_rtf_text("ş") == r"\u351?"


def test_rtf_emitter_document_structure_and_multipage() -> None:
    """Verify RTF 1.9.1 header groups, page setup, sections, headers/footers, and body blocks."""
    black = Color.black()
    accent = Color(20, 80, 160)

    blocks_p1: List[BlockNode] = [
        Paragraph(
            runs=[TextRun("Quarterly Summary", "Helvetica-Bold", 20.0, accent, is_bold=True)],
            heading_level=HeadingLevel.H1,
        ),
        Paragraph(
            runs=[
                TextRun("Normal ", "Times New Roman", 12.0, black),
                TextRun("Italic", "Times New Roman", 12.0, black, is_italic=True),
                TextRun("Code", "Courier New", 10.0, black, is_underline=True),
            ],
            alignment=Alignment.JUSTIFIED,
            space_before=6.0,
            space_after=8.0,
        ),
        Paragraph(runs=[TextRun("Bullet item", "Helvetica", 11.0, black)], list_marker="•"),
        Table(
            rows=[
                TableRow(
                    cells=[
                        TableCell(content=[Paragraph(runs=[TextRun("Key", "Helvetica", 10.0, black)])]),
                        TableCell(content=[Paragraph(runs=[TextRun("Val", "Helvetica", 10.0, black)])]),
                    ],
                    is_header=True,
                )
            ]
        ),
        ImageBlock(image_bytes=b"\x89PNG", bbox=BoundingBox(0, 0, 50, 50), alt_text="Logo"),
    ]
    p1 = DocumentPage(
        page_number=1,
        width=612.0,
        height=792.0,
        blocks=blocks_p1,
        header=PageHeaderFooter(content=[Paragraph(runs=[TextRun("Header Text", "Helvetica", 9.0, black)])]),
        footer=PageHeaderFooter(
            content=[Paragraph(runs=[TextRun("Footer Text", "Helvetica", 9.0, black)])],
            is_footer=True,
        ),
    )
    # Page 2 has landscape dimensions -> triggers \sect\sectd\lndscpsxn
    p2 = DocumentPage(
        page_number=2,
        width=792.0,
        height=612.0,
        blocks=[Paragraph(runs=[TextRun("Landscape Page", "Helvetica", 12.0, black)])],
    )
    doc = DocumentIR(
        pages=[p1, p2],
        metadata={"Title": "RTF Report", "Author": "QA Team", "Subject": "Spec Check"},
    )

    emitter = RtfEmitter()
    rtf_bytes = emitter.emit(doc)
    text = assert_valid_rtf(rtf_bytes)

    assert r"\fonttbl" in text
    assert r"\colortbl" in text
    assert r"\stylesheet" in text
    assert r"{\info{\title RTF Report}{\author QA Team}{\subject Spec Check}{\operator anyconvert}}" in text
    assert r"\paperw12240\paperh15840\margl1440\margr1440\margt1440\margb1440" in text
    assert r"\sect\sectd\pgwsxn15840\pghsxn12240" in text
    assert r"\lndscpsxn" in text
    assert r"{\header " in text
    assert r"{\footer " in text
    assert r"\s1\outlinelevel0\keepn" in text
    assert r"\trowd" in text and r"\row" in text
    assert "[Logo]" in text

    with pytest.raises(SerializationError):
        emitter.emit(DocumentIR(pages=[]))


def test_rtf_api_and_cli_integration(tmp_path: pathlib.Path) -> None:
    """Verify 'rtf' registration in API and CLI: anyconvert input.pdf -f rtf -o output.rtf."""
    assert "rtf" in SUPPORTED_FORMATS
    assert isinstance(_get_emitter("rtf"), RtfEmitter)

    pdf_bytes = _build_minimal_pdf()
    rtf_bytes = convert_bytes(pdf_bytes, output_format="rtf")
    text = assert_valid_rtf(rtf_bytes)
    assert "RTF Architecture Verification" in text

    in_pdf = tmp_path / "input.pdf"
    out_rtf = tmp_path / "output.rtf"
    in_pdf.write_bytes(pdf_bytes)

    assert main([str(in_pdf), "-f", "rtf", "-o", str(out_rtf)]) == 0
    assert out_rtf.is_file()
    cli_text = assert_valid_rtf(out_rtf.read_bytes())
    assert "RTF Architecture Verification" in cli_text

    # Direct API file-to-file
    api_rtf = tmp_path / "api.rtf"
    convert(in_pdf, output_format="rtf", output_path=api_rtf)
    assert api_rtf.is_file()
