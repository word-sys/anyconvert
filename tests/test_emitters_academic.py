"""Tests for Academic & Scientific emitters: Typst (.typ) and LaTeX (.tex)."""

from __future__ import annotations

import pathlib
from typing import List

import pytest

from anyconvert.api import SUPPORTED_FORMATS, _get_emitter, convert, convert_bytes
from anyconvert.cli import main
from anyconvert.common.color import Color
from anyconvert.common.geometry import BoundingBox
from anyconvert.emitters.typst import (
    TypstEmitter,
    clean_typst_font_name,
    escape_typst_markup,
    escape_typst_string,
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


def _build_minimal_pdf() -> bytes:
    """Build a minimal valid PDF for Typst and LaTeX API/CLI integration tests."""
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
            b"BT /F1 14 Tf 72 700 Td (Academic Emitter Verification) Tj ET\n"
            b"endstream\nendobj\n"
        ),
        b"5 0 obj\n<< /Title (Research Paper) /Author (Dr. Researcher) >>\nendobj\n",
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
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R /Info 5 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("ascii")
    )
    return bytes(out)


def test_typst_escaping_and_font_helpers() -> None:
    """Verify Typst string literal escaping, markup escaping, and PDF font cleaning."""
    assert clean_typst_font_name("ABCDEF+TimesNewRoman-Bold") == "TimesNewRoman"
    assert clean_typst_font_name("Helvetica,Italic") == "Helvetica"
    assert clean_typst_font_name("") == "Libertinus Serif"

    assert escape_typst_string('Title "A"\\B\nC') == 'Title \\"A\\"\\\\B\\nC'

    escaped = escape_typst_markup("#set *bold* _it_ $x$ // comment /* blk */ [a]")
    assert r"\#set" in escaped
    assert r"\*bold\*" in escaped
    assert r"\_it\_" in escaped
    assert r"\$x\$" in escaped
    assert r"\/" in escaped
    assert r"\[a\]" in escaped


def test_typst_emitter_preamble_pages_and_blocks(tmp_path: pathlib.Path) -> None:
    """Verify #set document/page/text preamble, page geometry changes, headings, and assets."""
    black = Color.black()
    blue = Color(10, 60, 180)

    blocks_p1: List[BlockNode] = [
        Paragraph(
            runs=[TextRun("Introduction", "Helvetica-Bold", 18.0, black, is_bold=True)],
            heading_level=HeadingLevel.H1,
        ),
        Paragraph(
            runs=[
                TextRun("Body ", "Times New Roman", 11.0, black),
                TextRun("Strong", "Times New Roman", 11.0, blue, is_bold=True),
                TextRun(" ", "Times New Roman", 11.0, black),
                TextRun("Italic", "Times New Roman", 11.0, black, is_italic=True),
                TextRun(" ", "Times New Roman", 11.0, black),
                TextRun("fn()", "CourierNew", 10.0, black),
            ],
            alignment=Alignment.JUSTIFIED,
        ),
        Paragraph(runs=[TextRun("First bullet", "Times New Roman", 11.0, black)], list_marker="•"),
        Paragraph(runs=[TextRun("First step", "Times New Roman", 11.0, black)], list_marker="1."),
        Table(
            rows=[
                TableRow(
                    cells=[
                        TableCell(content=[Paragraph(runs=[TextRun("Col A", "H", 10.0, black)])]),
                        TableCell(content=[Paragraph(runs=[TextRun("Col B", "H", 10.0, black)])]),
                    ],
                    is_header=True,
                )
            ]
        ),
        ImageBlock(
            image_bytes=b"\x89PNG\r\n\x1a\nFAKEPNG",
            bbox=BoundingBox(0, 0, 100, 60),
            alt_text="Experiment Plot",
            format="png",
        ),
    ]
    p1 = DocumentPage(
        page_number=1,
        width=612.0,
        height=792.0,
        margin_top=72.0,
        margin_bottom=72.0,
        margin_left=72.0,
        margin_right=72.0,
        blocks=blocks_p1,
        header=PageHeaderFooter(content=[Paragraph(runs=[TextRun("Journal Preprint", "H", 9.0, black)])]),
        footer=PageHeaderFooter(
            content=[Paragraph(runs=[TextRun("Page 1", "H", 9.0, black)])],
            is_footer=True,
        ),
    )
    p2 = DocumentPage(
        page_number=2,
        width=792.0,
        height=612.0,
        blocks=[Paragraph(runs=[TextRun("Landscape Appendix", "Times New Roman", 14.0, black)], heading_level=HeadingLevel.H2)],
    )
    doc = DocumentIR(
        pages=[p1, p2],
        metadata={
            "Title": "Pure-Python Document Synthesis",
            "Author": "Alice Smith; Bob Jones",
            "Subject": "Scientific Publishing",
            "Keywords": "typst, pdf, python",
        },
    )

    # 1. Default standalone compilable emission (placeholder rect for figure)
    typ_bytes = TypstEmitter().emit(doc)
    typ_text = typ_bytes.decode("utf-8")

    assert "#set document(" in typ_text
    assert 'title: "Pure-Python Document Synthesis"' in typ_text
    assert 'author: ("Alice Smith", "Bob Jones")' in typ_text
    assert 'keywords: ("typst", "pdf", "python")' in typ_text
    assert "#set page(" in typ_text
    assert "width: 612pt," in typ_text
    assert "height: 792pt," in typ_text
    assert "margin: (top: 72pt, bottom: 72pt, left: 72pt, right: 72pt)," in typ_text
    assert "header: align(right)[#text(size: 9pt)[Journal Preprint]]" in typ_text
    assert "footer: align(center)[#text(size: 9pt)[Page 1]]" in typ_text
    assert "#set text(" in typ_text
    assert '"Times New Roman"' in typ_text
    assert "size: 11pt," in typ_text
    assert "= #strong[Introduction]" in typ_text
    assert "== Landscape Appendix" in typ_text
    assert "width: 792pt," in typ_text
    assert "height: 612pt," in typ_text
    assert "- First bullet" in typ_text
    assert "+ First step" in typ_text
    assert "#table(" in typ_text
    assert "#figure(" in typ_text

    # 2. With image_dir extraction
    img_out = tmp_path / "typ_assets"
    emitter_img = TypstEmitter(image_dir=img_out)
    typ_with_img = emitter_img.render(doc)
    assert 'image("' in typ_with_img
    assert (img_out / "img_1.png").is_file()
    assert len(emitter_img.extracted_images) == 1

    # 3. Empty DocumentIR raises SerializationError
    with pytest.raises(SerializationError):
        TypstEmitter().emit(DocumentIR(pages=[]))


def test_typst_api_and_cli_integration(tmp_path: pathlib.Path) -> None:
    """Verify 'typst' format registration in API and CLI including default .typ output extension."""
    assert "typst" in SUPPORTED_FORMATS
    assert isinstance(_get_emitter("typst"), TypstEmitter)
    assert isinstance(_get_emitter("typ"), TypstEmitter)

    pdf_bytes = _build_minimal_pdf()
    typ_bytes = convert_bytes(pdf_bytes, output_format="typst")
    typ_text = typ_bytes.decode("utf-8")
    assert "#set page(" in typ_text
    assert "#set text(" in typ_text
    assert 'title: "Research Paper"' in typ_text
    assert "Academic Emitter Verification" in typ_text

    in_pdf = tmp_path / "paper.pdf"
    out_typ = tmp_path / "custom.typ"
    in_pdf.write_bytes(pdf_bytes)

    assert main([str(in_pdf), "-f", "typst", "-o", str(out_typ)]) == 0
    assert out_typ.is_file()
    assert "Academic Emitter Verification" in out_typ.read_text(encoding="utf-8")

    # Default output naming produces paper.typ (not paper.typst)
    assert main([str(in_pdf), "-f", "typst"]) == 0
    default_typ = tmp_path / "paper.typ"
    assert default_typ.is_file()
    assert "Academic Emitter Verification" in default_typ.read_text(encoding="utf-8")

    # Direct API file-to-file
    api_typ = tmp_path / "api_out.typ"
    convert(in_pdf, output_format="typst", output_path=api_typ)
    assert api_typ.is_file()
