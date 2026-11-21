"""Tests for Academic & Scientific emitters: Typst (.typ) and LaTeX (.tex)."""

from __future__ import annotations

import pathlib
from typing import List

import pytest

from anyconvert.api import SUPPORTED_FORMATS, _get_emitter, convert, convert_bytes
from anyconvert.cli import main
from anyconvert.common.color import Color
from anyconvert.common.geometry import BoundingBox
from anyconvert.emitters.latex import (
    LatexEmitter,
    classify_math_font,
    decode_math_font_text,
    detect_script_kind,
    escape_latex_text,
    escape_latex_url,
    is_math_font,
    translate_math_text_to_latex,
)
from anyconvert.emitters.typst import (
    TypstEmitter,
    clean_typst_font_name,
    escape_typst_markup,
    escape_typst_string,
    render_typst_table,
    translate_math_text_to_typst,
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
    assert "= Introduction" in typ_text
    assert "*Strong*" in typ_text
    assert "_Italic_" in typ_text
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


def test_typst_content_inline_formatting_lists_and_code_blocks() -> None:
    """Verify idiomatic *bold*, _italic_, *_both_*, links, nested lists, and grouped code fences."""
    black = Color.black()
    red = Color(200, 10, 20)

    p_inline = Paragraph(
        runs=[
            TextRun("Plain ", "Libertinus Serif", 11.0, black),
            TextRun("Bold ", "Libertinus Serif", 11.0, black, is_bold=True),
            TextRun("Italic ", "Libertinus Serif", 11.0, black, is_italic=True),
            TextRun("Both ", "Libertinus Serif", 11.0, black, is_bold=True, is_italic=True),
            TextRun("Under ", "Libertinus Serif", 11.0, black, is_underline=True),
            TextRun("Strike ", "Libertinus Serif", 11.0, red, is_strikethrough=True),
            TextRun("2", "Libertinus Serif", 8.0, black, baseline_offset=3.0),
            TextRun("n ", "Libertinus Serif", 8.0, black, baseline_offset=-3.0),
            TextRun("https://typst.app", "Libertinus Serif", 11.0, black),
        ]
    )

    p_ul1 = Paragraph(runs=[TextRun("- Top item", "Libertinus Serif", 11.0, black)], list_marker="-", list_level=0)
    p_ul2 = Paragraph(runs=[TextRun("Nested item", "Libertinus Serif", 11.0, black)], list_marker="•", list_level=1)
    p_ol1 = Paragraph(runs=[TextRun("1. Step one", "Libertinus Serif", 11.0, black)], list_marker="1.", list_level=0)

    p_code1 = Paragraph(runs=[TextRun("def solve(x):", "Courier New", 10.0, black)])
    p_code2 = Paragraph(runs=[TextRun("    return x + 1", "Courier New", 10.0, black)])
    p_sep = Paragraph(runs=[TextRun("Intervening prose.", "Libertinus Serif", 11.0, black)])
    p_code_bt = Paragraph(runs=[TextRun("Use ```typst raw fence", "Consolas", 10.0, black)])

    doc = DocumentIR(
        pages=[
            DocumentPage(
                1,
                612.0,
                792.0,
                blocks=[p_inline, p_ul1, p_ul2, p_ol1, p_code1, p_code2, p_sep, p_code_bt],
            )
        ]
    )
    typ_text = TypstEmitter().render(doc)

    assert "*Bold*" in typ_text
    assert "_Italic_" in typ_text
    assert "*_Both_*" in typ_text
    assert "#underline[Under]" in typ_text
    assert '#text(fill: rgb("#C80A14"))[#strike[Strike]]' in typ_text
    assert "#super[2]" in typ_text
    assert "#sub[n]" in typ_text
    assert '#link("https://typst.app")' in typ_text

    # Contiguous list items joined with single newline and deduplicated markers
    assert "- Top item\n  - Nested item\n+ Step one" in typ_text

    # Consecutive monospace paragraphs grouped into one raw block
    assert "```\ndef solve(x):\n    return x + 1\n```" in typ_text
    # Backtick fence expansion
    assert "````\nUse ```typst raw fence\n````" in typ_text


def test_typst_native_table_spans_alignments_and_headers() -> None:
    """Verify #table(columns: ..., align: ..., table.header(...), table.cell(colspan/rowspan/fill))."""
    black = Color.black()
    header_fill = Color(240, 244, 248)

    h1 = TableCell(
        content=[Paragraph(runs=[TextRun("Dataset", "H", 10.0, black)])],
        col_span=2,
        background_color=header_fill,
    )
    h2 = TableCell(content=[Paragraph(runs=[TextRun("Accuracy", "H", 10.0, black)])])
    row_hdr = TableRow(cells=[h1, h2], is_header=True)

    c_rowspan = TableCell(
        content=[Paragraph(runs=[TextRun("Benchmark A", "H", 10.0, black)])],
        row_span=2,
    )
    c_sub1 = TableCell(
        content=[Paragraph(runs=[TextRun("Fold 1", "H", 10.0, black)], alignment=Alignment.CENTER)]
    )
    c_num1 = TableCell(content=[Paragraph(runs=[TextRun("98.4%", "H", 10.0, black)])])
    row_1 = TableRow(cells=[c_rowspan, c_sub1, c_num1])

    # Row 2 has only 2 cells because col 0 is occupied by c_rowspan (row_span=2)
    c_sub2 = TableCell(
        content=[Paragraph(runs=[TextRun("Fold 2", "H", 10.0, black)], alignment=Alignment.CENTER)]
    )
    c_num2 = TableCell(content=[Paragraph(runs=[TextRun("99.1%", "H", 10.0, black)])])
    row_2 = TableRow(cells=[c_sub2, c_num2])

    tbl = Table(
        rows=[row_hdr, row_1, row_2],
        col_widths=[140.0, 80.0, 90.0],
    )

    tbl_typ = render_typst_table(tbl)
    assert "columns: (140pt, 80pt, 90pt)," in tbl_typ
    assert "align: (left, center, right)," in tbl_typ
    assert 'table.header(table.cell(colspan: 2, fill: rgb("#F0F4F8"))[Dataset], [Accuracy]),' in tbl_typ
    assert "table.cell(rowspan: 2)[Benchmark A], [Fold 1], [98.4%]," in tbl_typ
    assert "  [Fold 2], [99.1%]," in tbl_typ


def test_latex_escaping_helpers() -> None:
    """Verify escaping of all 10 LaTeX special characters, typographic Unicode, and URLs."""
    raw = r"\ { } $ & # % _ ^ ~ < > — – …"
    escaped = escape_latex_text(raw)
    assert r"\textbackslash{}" in escaped
    assert r"\{" in escaped
    assert r"\}" in escaped
    assert r"\$" in escaped
    assert r"\&" in escaped
    assert r"\#" in escaped
    assert r"\%" in escaped
    assert r"\_" in escaped
    assert r"\textasciicircum{}" in escaped
    assert r"\textasciitilde{}" in escaped
    assert r"\textless{}" in escaped
    assert r"\textgreater{}" in escaped
    assert "---" in escaped
    assert "--" in escaped
    assert r"\ldots{}" in escaped

    # Control characters stripped cleanly without breaking output
    assert escape_latex_text("A\x00\x07B\r\nC") == "AB \\\\\nC"

    # URL escaping
    url_esc = escape_latex_url("https://example.org/a%20b#sec{1}")
    assert r"\%" in url_esc
    assert r"\#" in url_esc
    assert r"\{" in url_esc
    assert r"\}" in url_esc


def test_latex_emitter_preamble_blocks_lists_code_and_tables(tmp_path: pathlib.Path) -> None:
    """Verify full LaTeX preamble, headings, inline runs, nested lists, verbatim, booktabs, and figures."""
    black = Color.black()
    blue = Color(10, 60, 180)
    header_fill = Color(240, 244, 248)

    blocks_p1: List[BlockNode] = [
        Paragraph(
            runs=[TextRun("Introduction", "Helvetica-Bold", 18.0, black, is_bold=True)],
            heading_level=HeadingLevel.H1,
        ),
        Paragraph(
            runs=[
                TextRun("Plain ", "Times New Roman", 11.0, black),
                TextRun("Bold ", "Times New Roman", 11.0, blue, is_bold=True),
                TextRun("Italic ", "Times New Roman", 11.0, black, is_italic=True),
                TextRun("Under ", "Times New Roman", 11.0, black, is_underline=True),
                TextRun("Strike ", "Times New Roman", 11.0, black, is_strikethrough=True),
                TextRun("Note", "Times New Roman", 11.0, black),
                TextRun("2", "Times New Roman", 8.0, black, baseline_offset=3.0),
                TextRun(" ", "Times New Roman", 11.0, black),
                TextRun("i ", "Times New Roman", 8.0, black, baseline_offset=-3.0),
                TextRun("fn()", "Courier New", 10.0, black),
                TextRun(" ", "Times New Roman", 11.0, black),
                TextRun("https://ctan.org/pkg/booktabs", "Times New Roman", 11.0, black),
            ]
        ),
        Paragraph(
            runs=[TextRun("Centered Note", "Times New Roman", 11.0, black)],
            alignment=Alignment.CENTER,
        ),
        Paragraph(runs=[TextRun("- Bullet one", "Times New Roman", 11.0, black)], list_marker="-", list_level=0),
        Paragraph(runs=[TextRun("Sub bullet", "Times New Roman", 11.0, black)], list_marker="•", list_level=1),
        Paragraph(runs=[TextRun("1. Step one", "Times New Roman", 11.0, black)], list_marker="1.", list_level=0),
        Paragraph(runs=[TextRun("def f(x):", "Courier New", 10.0, black)]),
        Paragraph(runs=[TextRun("    return x * 2", "Courier New", 10.0, black)]),
        Table(
            rows=[
                TableRow(
                    cells=[
                        TableCell(
                            content=[Paragraph(runs=[TextRun("Dataset", "H", 10.0, black)])],
                            col_span=2,
                            background_color=header_fill,
                        ),
                        TableCell(content=[Paragraph(runs=[TextRun("Score", "H", 10.0, black)])]),
                    ],
                    is_header=True,
                ),
                TableRow(
                    cells=[
                        TableCell(
                            content=[Paragraph(runs=[TextRun("Bench A", "H", 10.0, black)])],
                            row_span=2,
                        ),
                        TableCell(
                            content=[Paragraph(runs=[TextRun("Fold 1", "H", 10.0, black)], alignment=Alignment.CENTER)]
                        ),
                        TableCell(content=[Paragraph(runs=[TextRun("98.4%", "H", 10.0, black)])]),
                    ]
                ),
                TableRow(
                    cells=[
                        TableCell(
                            content=[Paragraph(runs=[TextRun("Fold 2", "H", 10.0, black)], alignment=Alignment.CENTER)]
                        ),
                        TableCell(content=[Paragraph(runs=[TextRun("99.1%", "H", 10.0, black)])]),
                    ]
                ),
            ]
        ),
        ImageBlock(
            image_bytes=b"\x89PNG\r\n\x1a\nFAKEPNG",
            bbox=BoundingBox(0, 0, 240, 120),
            alt_text="Convergence Curve",
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
        header=PageHeaderFooter(content=[Paragraph(runs=[TextRun("Preprint 2026", "H", 9.0, black)])]),
        footer=PageHeaderFooter(
            content=[Paragraph(runs=[TextRun("Page 1", "H", 9.0, black)])],
            is_footer=True,
        ),
    )
    p2 = DocumentPage(
        page_number=2,
        width=612.0,
        height=792.0,
        margin_top=54.0,
        margin_bottom=54.0,
        margin_left=54.0,
        margin_right=54.0,
        blocks=[
            Paragraph(
                runs=[TextRun("Appendix", "Helvetica-Bold", 14.0, black)],
                heading_level=HeadingLevel.H2,
            ),
            Paragraph(runs=[TextRun(r"\end{verbatim} edge case", "Courier New", 10.0, black)]),
        ],
    )
    doc = DocumentIR(
        pages=[p1, p2],
        metadata={
            "Title": "Pure-Python LaTeX Synthesis",
            "Author": "Alice Smith; Bob Jones",
            "Subject": "Academic Publishing",
            "Keywords": "latex, pdf, python",
        },
    )

    tex_bytes = LatexEmitter(emit_maketitle=True).emit(doc)
    tex_text = tex_bytes.decode("utf-8")

    # Core preamble requirements
    assert r"\documentclass[11pt]{article}" in tex_text
    assert r"\usepackage[utf8]{inputenc}" in tex_text
    assert r"\usepackage[T1]{fontenc}" in tex_text
    assert r"\usepackage{geometry}" in tex_text
    assert r"\usepackage{graphicx}" in tex_text
    assert r"\usepackage{booktabs}" in tex_text
    assert r"\usepackage{xcolor}" in tex_text
    assert r"\usepackage{multirow}" in tex_text
    assert r"\usepackage{colortbl}" in tex_text
    assert r"\usepackage[normalem]{ulem}" in tex_text
    assert r"\usepackage{fancyhdr}" in tex_text
    assert r"\usepackage[hidelinks]{hyperref}" in tex_text

    # Geometry, headers/footers, metadata
    assert "paperwidth=612pt," in tex_text
    assert "paperheight=792pt," in tex_text
    assert "top=72pt," in tex_text
    assert r"\fancyhead[R]{\small Preprint 2026}" in tex_text
    assert r"\fancyfoot[C]{\small Page 1}" in tex_text
    assert r"\title{Pure-Python LaTeX Synthesis}" in tex_text
    assert r"\author{Alice Smith \and Bob Jones}" in tex_text
    assert r"\maketitle" in tex_text
    assert r"\begin{document}" in tex_text
    assert r"\end{document}" in tex_text

    # Headings and inline styling
    assert r"\section{Introduction}" in tex_text
    assert r"\textcolor[HTML]{0A3CB4}{\textbf{Bold}}" in tex_text
    assert r"\textit{Italic}" in tex_text
    assert r"\underline{Under}" in tex_text
    assert r"\sout{Strike}" in tex_text
    assert r"\textsuperscript{2}" in tex_text
    assert r"\textsubscript{i}" in tex_text
    assert r"\texttt{fn()}" in tex_text
    assert r"\url{https://ctan.org/pkg/booktabs}" in tex_text
    assert "\\begin{center}\nCentered Note\n\\end{center}" in tex_text

    # Balanced nested lists
    assert tex_text.count(r"\begin{itemize}") == tex_text.count(r"\end{itemize}") == 2
    assert tex_text.count(r"\begin{enumerate}") == tex_text.count(r"\end{enumerate}") == 1
    assert r"\item Bullet one" in tex_text
    assert r"\item Sub bullet" in tex_text
    assert r"\item Step one" in tex_text

    # Verbatim code block and safe \end{verbatim} fallback
    assert "\\begin{verbatim}\ndef f(x):\n    return x * 2\n\\end{verbatim}" in tex_text
    assert r"\begin{quote}\ttfamily" in tex_text

    # Booktabs table with spans, alignment, and fill
    assert r"\begin{tabular}{lcr}" in tex_text
    assert r"\toprule" in tex_text
    assert r"\midrule" in tex_text
    assert r"\bottomrule" in tex_text
    assert r"\multicolumn{2}{l}{\cellcolor[HTML]{F0F4F8}Dataset}" in tex_text
    assert r"\multirow{2}{*}{Bench A}" in tex_text

    # Page 2 geometry change & heading
    assert r"\newgeometry{top=54pt, bottom=54pt, left=54pt, right=54pt}" in tex_text
    assert r"\subsection{Appendix}" in tex_text

    # Standalone figure placeholder
    assert r"\begin{figure}[htbp]" in tex_text
    assert r"\caption{Convergence Curve}" in tex_text

    # Image extraction mode with relative prefix
    img_out = tmp_path / "latex_assets"
    emitter_img = LatexEmitter(image_dir=img_out, image_link_prefix="images")
    tex_with_img = emitter_img.render(doc)
    assert r"\includegraphics[width=240pt]{images/img_1.png}" in tex_with_img
    assert (img_out / "img_1.png").is_file()
    assert len(emitter_img.extracted_images) == 1

    # Unnumbered headings option
    unnumbered = LatexEmitter(numbered_headings=False).render(doc)
    assert r"\section*{Introduction}" in unnumbered
    assert r"\subsection*{Appendix}" in unnumbered

    # Empty DocumentIR raises SerializationError
    with pytest.raises(SerializationError):
        LatexEmitter().emit(DocumentIR(pages=[]))


def test_latex_api_and_cli_integration(tmp_path: pathlib.Path) -> None:
    """Verify 'latex' format registration in API and CLI including default .tex output extension."""
    assert "latex" in SUPPORTED_FORMATS
    assert isinstance(_get_emitter("latex"), LatexEmitter)
    assert isinstance(_get_emitter("tex"), LatexEmitter)

    pdf_bytes = _build_minimal_pdf()
    tex_bytes = convert_bytes(pdf_bytes, output_format="latex")
    tex_text = tex_bytes.decode("utf-8")
    assert r"\documentclass[" in tex_text
    assert r"\usepackage{geometry}" in tex_text
    assert r"\usepackage{graphicx}" in tex_text
    assert r"\usepackage{booktabs}" in tex_text
    assert r"\title{Research Paper}" in tex_text
    assert "Academic Emitter Verification" in tex_text

    in_pdf = tmp_path / "paper.pdf"
    out_tex = tmp_path / "custom.tex"
    in_pdf.write_bytes(pdf_bytes)

    assert main([str(in_pdf), "-f", "latex", "-o", str(out_tex)]) == 0
    assert out_tex.is_file()
    assert "Academic Emitter Verification" in out_tex.read_text(encoding="utf-8")

    # Default output naming produces paper.tex (not paper.latex)
    assert main([str(in_pdf), "-f", "latex"]) == 0
    default_tex = tmp_path / "paper.tex"
    assert default_tex.is_file()
    assert "Academic Emitter Verification" in default_tex.read_text(encoding="utf-8")

    # Direct API file-to-file
    api_tex = tmp_path / "api_out.tex"
    convert(in_pdf, output_format="latex", output_path=api_tex)
    assert api_tex.is_file()


def test_math_font_classification_decoding_and_baseline_detection() -> None:
    """Verify Symbol/CMSY/CMMI/CMEX/MSBM decoding and explicit/geometric script detection."""
    black = Color.black()

    assert classify_math_font("Symbol") == "symbol"
    assert classify_math_font("ABCDEF+CMSY10") == "cmsy"
    assert classify_math_font("XYZABC+CMMI10") == "cmmi"
    assert classify_math_font("CMEX10") == "cmex"
    assert classify_math_font("MSBM10") == "msbm"
    assert classify_math_font("Cambria Math") == "unicode_math"
    assert is_math_font("Symbol")
    assert not is_math_font("Times New Roman")
    assert not is_math_font("Helvetica")

    # Adobe Symbol decoding
    assert decode_math_font_text("abgS\xa3\xa5\xb1\xce", "Symbol") == "αβγΣ≤∞±∈"
    # CMSY decoding
    assert decode_math_font_text("\x02\x14\x31\x32\x38", "ABCDEF+CMSY10") == "×≤∞∈∀"
    # CMMI and CMEX decoding
    assert decode_math_font_text("\x0b\x19", "CMMI10") == "απ"
    assert decode_math_font_text("\x50", "CMEX10") == "∑"

    # Font-aware LaTeX & Typst symbol translation
    assert translate_math_text_to_latex("L", "CMSY10") == r"\mathcal{L}"
    assert translate_math_text_to_latex("R", "MSBM10") == r"\mathbb{R}"
    assert translate_math_text_to_typst("L", "CMSY10") == "cal(L)"
    assert translate_math_text_to_typst("R", "MSBM10") == "RR"

    # Explicit baseline_offset detection
    base = TextRun("x", "Times New Roman", 11.0, black, bbox=BoundingBox(100.0, 200.0, 108.0, 212.0))
    sup_explicit = TextRun("2", "Times New Roman", 8.0, black, baseline_offset=3.0)
    sub_explicit = TextRun("i", "Times New Roman", 8.0, black, baseline_offset=-3.0)
    assert detect_script_kind(sup_explicit, base) == "sup"
    assert detect_script_kind(sub_explicit, base) == "sub"

    # Geometric bounding-box detection (baseline_offset == 0.0, top-down doc Y)
    sup_geom = TextRun("2", "Times New Roman", 7.5, black, bbox=BoundingBox(108.5, 197.0, 113.0, 205.0))
    sub_geom = TextRun("i", "Times New Roman", 7.5, black, bbox=BoundingBox(108.5, 207.0, 113.0, 215.5))
    normal_next = TextRun("y", "Times New Roman", 11.0, black, bbox=BoundingBox(114.0, 200.0, 122.0, 212.0))
    assert detect_script_kind(sup_geom, base) == "sup"
    assert detect_script_kind(sub_geom, base) == "sub"
    assert detect_script_kind(normal_next, base) is None


def test_latex_and_typst_math_heuristics_end_to_end() -> None:
    """Verify inline math extraction for scripts, Symbol/CMSY/MSBM fonts, and Unicode symbols."""
    black = Color.black()

    # 1. Explicit baseline shifts: For any x^2 and x_i^{n+1}
    p_scripts = Paragraph(
        runs=[
            TextRun("For any x", "Times New Roman", 11.0, black),
            TextRun("2", "Times New Roman", 8.0, black, baseline_offset=3.0),
            TextRun(" and x", "Times New Roman", 11.0, black),
            TextRun("i", "Times New Roman", 8.0, black, baseline_offset=-3.0),
            TextRun("n+1", "Times New Roman", 8.0, black, baseline_offset=3.0),
            TextRun(".", "Times New Roman", 11.0, black),
        ]
    )

    # 2. Geometric bbox baseline shift (zero baseline_offset): E = mc^2
    p_geom = Paragraph(
        runs=[
            TextRun("E = mc", "Times New Roman", 12.0, black, bbox=BoundingBox(72.0, 100.0, 116.0, 113.0)),
            TextRun("2", "Times New Roman", 8.0, black, bbox=BoundingBox(116.5, 97.0, 122.0, 105.0)),
        ]
    )

    # 3. Legacy Symbol, CMSY, and MSBM math fonts merged across connectors
    p_fonts = Paragraph(
        runs=[
            TextRun("a", "Symbol", 11.0, black),
            TextRun(" + ", "Times New Roman", 11.0, black),
            TextRun("b", "Symbol", 11.0, black),
            TextRun(" ", "Times New Roman", 11.0, black),
            TextRun("\x14", "ABCDEF+CMSY10", 11.0, black),
            TextRun(" ", "Times New Roman", 11.0, black),
            TextRun("g", "Symbol", 11.0, black),
            TextRun(" with ", "Times New Roman", 11.0, black),
            TextRun("L", "CMSY10", 11.0, black),
            TextRun(" in ", "Times New Roman", 11.0, black),
            TextRun("R", "MSBM10", 11.0, black),
        ]
    )

    # 4. Inline Unicode Greek/math symbols & superscripts in standard font
    p_unicode = Paragraph(
        runs=[TextRun("We observe α ≤ β and σ² → 0 for all x ∈ ℝ.", "Times New Roman", 11.0, black)]
    )

    # 5. Prose footnotes and ordinals must NOT be misclassified as math
    p_prose = Paragraph(
        runs=[
            TextRun("The 1", "Times New Roman", 11.0, black),
            TextRun("st", "Times New Roman", 8.0, black, baseline_offset=3.0),
            TextRun(" results", "Times New Roman", 11.0, black),
            TextRun("1", "Times New Roman", 8.0, black, baseline_offset=3.0),
            TextRun(" hold.", "Times New Roman", 11.0, black),
        ]
    )

    doc = DocumentIR(
        pages=[DocumentPage(1, 612.0, 792.0, blocks=[p_scripts, p_geom, p_fonts, p_unicode, p_prose])]
    )

    # LaTeX verification
    tex = LatexEmitter().render(doc)
    assert r"\usepackage{amsmath,amssymb}" in tex
    assert "For any $x^2$ and $x_i^{n+1}$." in tex
    assert "$E = mc^2$" in tex
    assert r"$\alpha + \beta \le \gamma$ with $\mathcal{L}$ in $\mathbb{R}$" in tex
    assert r"We observe $\alpha \le \beta$ and $\sigma^2 \rightarrow 0$ for all $x \in \mathbb{R}$." in tex
    assert r"The 1\textsuperscript{st} results\textsuperscript{1} hold." in tex

    # Plain prose document without math should NOT pull in amsmath unnecessarily
    plain_doc = DocumentIR(pages=[DocumentPage(1, 612.0, 792.0, blocks=[p_prose])])
    plain_tex = LatexEmitter().render(plain_doc)
    assert r"\usepackage{amsmath,amssymb}" not in plain_tex

    # Opt-out flag disables math heuristics cleanly
    tex_disabled = LatexEmitter(enable_math_heuristics=False).render(doc)
    assert r"\textsuperscript{2}" in tex_disabled

    # Typst verification
    typ = TypstEmitter().render(doc)
    assert "For any $x^2$ and $x_i^(n+1)$." in typ
    assert "$E = mc^2$" in typ
    assert "$alpha + beta <= gamma$ with $cal(L)$ in $RR$" in typ
    assert "We observe $alpha <= beta$ and $sigma^2 -> 0$ for all $x in RR$." in typ
    assert "The 1#super[st] results#super[1] hold." in typ

    typ_disabled = TypstEmitter(enable_math_heuristics=False).render(doc)
    assert "#super[2]" in typ_disabled


def test_pdf_symbol_font_end_to_end_math_extraction() -> None:
    """Verify a real PDF using /BaseFont /Symbol extracts math notation in LaTeX and Typst."""
    stream = (
        b"BT /F1 11 Tf 72 700 Td (Let ) Tj "
        b"/F2 11 Tf (a) Tj "
        b"/F1 11 Tf ( + ) Tj "
        b"/F2 11 Tf (b) Tj ET"
    )
    objs: List[bytes] = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Count 1 /Kids [3 0 R] >>\nendobj\n",
        (
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << "
            b"/F1 << /Type /Font /Subtype /Type1 /BaseFont /Times-Roman >> "
            b"/F2 << /Type /Font /Subtype /Type1 /BaseFont /Symbol >> "
            b">> >> >>\nendobj\n"
        ),
        f"4 0 obj\n<< /Length {len(stream)} >>\nstream\n".encode("ascii") + stream + b"\nendstream\nendobj\n",
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
    pdf_bytes = bytes(out)

    tex_out = convert_bytes(pdf_bytes, output_format="latex").decode("utf-8")
    assert r"\usepackage{amsmath,amssymb}" in tex_out
    assert r"\alpha" in tex_out
    assert r"\beta" in tex_out

    typ_out = convert_bytes(pdf_bytes, output_format="typst").decode("utf-8")
    assert "$alpha" in typ_out or "alpha" in typ_out
    assert "beta$" in typ_out or "beta" in typ_out



