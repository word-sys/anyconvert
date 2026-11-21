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
    CP_CYRILLIC,
    CP_GREEK,
    CP_JAPANESE,
    CP_KOREAN,
    CP_SIMPLIFIED_CHINESE,
    CP_TURKISH,
    CP_WESTERN,
    RtfColorTable,
    RtfEmitter,
    RtfFontTable,
    RtfStyleSheet,
    STYLE_FOOTER,
    STYLE_HEADER,
    STYLE_LIST,
    STYLE_NORMAL,
    classify_rtf_font_family,
    clean_rtf_font_name,
    detect_rtf_codepage,
    encode_rtf_unicode,
    escape_rtf_text,
    format_alignment,
    format_line_spacing,
    format_paragraph_controls,
    compute_rtf_col_widths,
    resolve_paragraph_style_index,
    resolve_rtf_font,
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


def test_rtf_unicode_escaping_and_ansi_fallbacks() -> None:
    """Verify \\uN\\'xx and \\uN? escaping across Turkish, Cyrillic, Greek, CJK, and supplementary planes."""
    # Turkish under cp1254 produces exact single-byte ANSI fallback hex escapes
    tr_out = encode_rtf_unicode("ğĞıİşŞçöü", codepage=1254)
    assert r"\u287\'f0" in tr_out  # ğ
    assert r"\u286\'d0" in tr_out  # Ğ
    assert r"\u305\'fd" in tr_out  # ı
    assert r"\u304\'dd" in tr_out  # İ
    assert r"\u351\'fe" in tr_out  # ş
    assert r"\u350\'de" in tr_out  # Ş
    assert r"\u231\'e7" in tr_out  # ç
    assert r"\u246\'f6" in tr_out  # ö
    assert r"\u252\'fc" in tr_out  # ü

    # Cyrillic under cp1251
    ru_out = encode_rtf_unicode("Привет", codepage=1251)
    assert r"\u1055\'cf" in ru_out
    assert ru_out.isascii()

    # Greek under cp1253
    el_out = encode_rtf_unicode("Αθήνα Ω", codepage=1253)
    assert r"\u913\'c1" in el_out
    assert r"\u937\'d9" in el_out
    assert el_out.isascii()

    # Asian scripts (Chinese, Japanese, Korean > 32767 signed 16-bit)
    cjk_out = encode_rtf_unicode("漢字かな한국어", codepage=1252)
    assert r"\u28450?" in cjk_out  # 漢 (U+6F22)
    assert r"\u-10916?" in cjk_out  # 한 (U+D55C = 54620 -> -10916)
    assert cjk_out.isascii()

    # Supplementary plane (U+1D400 -> UTF-16 surrogate pair)
    supp = encode_rtf_unicode("\U0001D400", codepage=1252)
    assert supp == r"\u-10187?\u-9216?"


def test_rtf_codepage_detection_and_font_resolution() -> None:
    """Verify automatic script/codepage detection and PDF PostScript font alias resolution."""
    assert detect_rtf_codepage("Plain ASCII text.") == CP_WESTERN
    assert detect_rtf_codepage("İstanbul'da güneşli bir gün") == CP_TURKISH
    assert detect_rtf_codepage("Привет мир") == CP_CYRILLIC
    assert detect_rtf_codepage("Ελληνικά γράμματα") == CP_GREEK
    assert detect_rtf_codepage("日本語のテスト") == CP_JAPANESE
    assert detect_rtf_codepage("中文文档测试") == CP_SIMPLIFIED_CHINESE
    assert detect_rtf_codepage("한국어 문서 테스트") == CP_KOREAN

    assert resolve_rtf_font("ABCDEF+TimesNewRomanPSMT") == ("Times New Roman", r"\froman")
    assert resolve_rtf_font("CourierNewPSMT") == ("Courier New", r"\fmodern")
    assert resolve_rtf_font("ArialMT") == ("Arial", r"\fswiss")
    assert resolve_rtf_font("ABCDEF+Helvetica-Bold") == ("Helvetica", r"\fswiss")


def test_rtf_emitter_turkish_and_multilingual_documents() -> None:
    """Verify RtfEmitter auto-switches codepage/charset for Turkish, Cyrillic, and CJK documents."""
    black = Color.black()
    doc_tr = DocumentIR(
        pages=[
            DocumentPage(
                1,
                595.0,
                842.0,
                blocks=[
                    Paragraph(
                        runs=[
                            TextRun(
                                "İstanbul'da güzel bir öğleden sonra: ğĞıİşŞçÇöÖüÜ",
                                "ABCDEF+TimesNewRomanPSMT",
                                12.0,
                                black,
                            )
                        ]
                    )
                ],
            )
        ],
        metadata={"Title": "Türkçe Belge", "Author": "Barın"},
    )
    rtf_tr_bytes = RtfEmitter().emit(doc_tr)
    rtf_tr = assert_valid_rtf(rtf_tr_bytes)
    assert r"\ansicpg1254" in rtf_tr
    assert r"\deflang1055" in rtf_tr
    assert r"\fcharset162 Times New Roman;" in rtf_tr
    assert r"\u351\'fe" in rtf_tr
    assert r"\u287\'f0" in rtf_tr
    assert r"\u305\'fd" in rtf_tr

    # Verify Cyrillic document selects cp1251 + fcharset204
    doc_ru = DocumentIR(
        pages=[
            DocumentPage(
                1,
                595.0,
                842.0,
                blocks=[Paragraph(runs=[TextRun("Привет, мир!", "ArialMT", 12.0, black)])],
            )
        ]
    )
    rtf_ru = assert_valid_rtf(RtfEmitter().emit(doc_ru))
    assert r"\ansicpg1251" in rtf_ru
    assert r"\fcharset204 Arial;" in rtf_ru
    assert r"\u1055\'cf" in rtf_ru


def test_rtf_paragraph_styles_headings_indentations_and_lists() -> None:
    """Verify paragraph control words (\\s1..\\s6, \\ql/\\qc/\\qr/\\qj, \\liN, \\fiN, \\sbN, \\saN, \\slN)."""
    assert format_alignment(Alignment.LEFT) == r"\ql"
    assert format_alignment(Alignment.CENTER) == r"\qc"
    assert format_alignment(Alignment.RIGHT) == r"\qr"
    assert format_alignment(Alignment.JUSTIFIED) == r"\qj"
    assert format_line_spacing(1.5) == r"\sl360\slmult1"
    assert format_line_spacing(2.0) == r"\sl480\slmult1"

    black = Color.black()
    p_h1 = Paragraph(runs=[TextRun("Title", "Helvetica", 20.0, black)], heading_level=HeadingLevel.H1)
    p_h3 = Paragraph(runs=[TextRun("Sub", "Helvetica", 14.0, black)], heading_level=HeadingLevel.H3)
    p_list = Paragraph(runs=[TextRun("- Item", "Helvetica", 11.0, black)], list_marker="-", list_level=1)
    p_norm = Paragraph(
        runs=[
            TextRun(
                "Indented body",
                "Helvetica",
                11.0,
                black,
                tracking=1.5,
                is_strikethrough=True,
            ),
            TextRun("2", "Helvetica", 8.0, black, baseline_offset=3.0),
            TextRun("0", "Helvetica", 8.0, black, baseline_offset=-3.0),
        ],
        alignment=Alignment.RIGHT,
        indent_left=36.0,
        indent_right=18.0,
        indent_first_line=18.0,
        space_before=12.0,
        space_after=6.0,
        line_spacing=1.5,
    )

    assert resolve_paragraph_style_index(p_h1) == 1
    assert resolve_paragraph_style_index(p_h3) == 3
    assert resolve_paragraph_style_index(p_list) == STYLE_LIST
    assert resolve_paragraph_style_index(p_norm) == STYLE_NORMAL
    assert resolve_paragraph_style_index(p_norm, role="header") == STYLE_HEADER
    assert resolve_paragraph_style_index(p_norm, role="footer") == STYLE_FOOTER

    ctrl_norm, _ = format_paragraph_controls(p_norm)
    assert r"\s0" in ctrl_norm
    assert r"\qr" in ctrl_norm
    assert r"\li720" in ctrl_norm
    assert r"\ri360" in ctrl_norm
    assert r"\fi360" in ctrl_norm
    assert r"\sb240" in ctrl_norm
    assert r"\sa120" in ctrl_norm
    assert r"\sl360\slmult1" in ctrl_norm

    ctrl_list, tab_twips = format_paragraph_controls(p_list)
    assert r"\s7" in ctrl_list
    assert ctrl_list.count(r"\li") == 1
    assert r"\li720" in ctrl_list
    assert r"\fi-360" in ctrl_list
    assert f"\\tx{tab_twips}" in ctrl_list

    doc = DocumentIR(pages=[DocumentPage(1, 612.0, 792.0, blocks=[p_h1, p_h3, p_list, p_norm])])
    rtf_text = assert_valid_rtf(RtfEmitter().emit(doc))

    assert "List Paragraph;" in rtf_text
    assert "Quote;" in rtf_text
    assert r"\s1\outlinelevel0\keepn" in rtf_text
    assert r"\s3\outlinelevel2\keepn" in rtf_text
    # Duplicate leading '-' in run text should be stripped when list_marker='-'
    assert r"-\tab {\f0\fs22\cf1 Item}" in rtf_text
    assert r"\expndtw30" in rtf_text
    assert r"\strike" in rtf_text
    assert r"\super" in rtf_text
    assert r"\sub" in rtf_text


def test_rtf_table_matrix_borders_shading_and_spans() -> None:
    """Verify RTF table generator emits \\trowd, \\clbrdr*, \\clcbpat, \\clvmgf/\\clvmrg, \\cellxN, \\intbl, \\cell, \\row."""
    black = Color.black()
    header_bg = Color(230, 240, 250)
    border_blue = Color(30, 90, 160)

    hdr_cell = TableCell(
        content=[Paragraph(runs=[TextRun("Merged Header", "Helvetica", 11.0, black, is_bold=True)])],
        col_span=2,
        background_color=header_bg,
        borders={
            "top": Border(style="double", width=1.5, color=border_blue),
            "bottom": Border(style="solid", width=1.0, color=border_blue),
            "left": Border(style="dashed", width=0.75, color=border_blue),
            "right": Border(style="dotted", width=0.75, color=border_blue),
        },
    )
    row_hdr = TableRow(cells=[hdr_cell], height=24.0, is_header=True)

    vmerge_cell = TableCell(
        content=[Paragraph(runs=[TextRun("Spanned Cat", "Helvetica", 10.0, black)])],
        row_span=2,
    )
    multi_p_cell = TableCell(
        content=[
            Paragraph(runs=[TextRun("Line A", "Helvetica", 10.0, black)]),
            Paragraph(runs=[TextRun("Line B", "Helvetica", 10.0, black)]),
        ]
    )
    row_1 = TableRow(cells=[vmerge_cell, multi_p_cell])

    row_2 = TableRow(
        cells=[TableCell(content=[Paragraph(runs=[TextRun("Row 2 Val", "Helvetica", 10.0, black)])])]
    )

    tbl = Table(
        rows=[row_hdr, row_1, row_2],
        col_widths=[120.0, 240.0],
        alignment=Alignment.CENTER,
    )
    empty_tbl = Table(rows=[])

    doc = DocumentIR(pages=[DocumentPage(1, 612.0, 792.0, blocks=[tbl, empty_tbl])])
    rtf_text = assert_valid_rtf(RtfEmitter().emit(doc))

    assert r"\trowd" in rtf_text
    assert r"\trqc" in rtf_text
    assert r"\trhdr" in rtf_text
    assert r"\trrh480" in rtf_text
    assert r"\clbrdrt\brdrdb" in rtf_text
    assert r"\clbrdrl\brdrdash" in rtf_text
    assert r"\clbrdrr\brdrdot" in rtf_text
    assert r"\clbrdrb\brdrs" in rtf_text
    assert r"\clcbpat" in rtf_text
    assert r"\clvmgf" in rtf_text
    assert r"\clvmrg" in rtf_text
    assert r"\intbl" in rtf_text
    assert r"\cellx2400" in rtf_text
    assert r"\cellx7200" in rtf_text
    assert r"\cell" in rtf_text
    assert r"\row" in rtf_text
    assert "Merged Header" in rtf_text
    assert "Line A" in rtf_text and "Line B" in rtf_text
    assert "Row 2 Val" in rtf_text

    # Verify proportional width scaling when total width exceeds page printable area
    wide_tbl = Table(rows=[row_1], col_widths=[400.0, 400.0])
    scaled = compute_rtf_col_widths(wide_tbl, num_cols=2, max_width_twips=9360)
    assert sum(scaled) <= 9360
    assert scaled[0] == scaled[1]



