from __future__ import annotations

import pathlib
from typing import List
import zlib

import pytest

from anyconvert.api import (
    SUPPORTED_FORMATS,
    _get_emitter,
    convert,
    convert_bytes,
)
from anyconvert.cli import main
from anyconvert.common.color import Color
from anyconvert.common.geometry import BoundingBox
from anyconvert.emitters.base import ConversionMode
from anyconvert.emitters.md import (
    MarkdownDialect,
    MarkdownEmitter,
    format_yaml_scalar,
    normalize_frontmatter_metadata,
    parse_keywords,
    render_yaml_frontmatter,
    resolve_dialect,
)
from anyconvert.emitters.txt import TxtFlowEmitter
from anyconvert.pdf.document import parse_pdf_date
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
            b"4 0 obj\n<< /Length 165 >>\nstream\n"
            b"BT /F1 16 Tf 72 700 Td (Markdown Emitter Integration Test) Tj ET\n"
            b"BT /F1 12 Tf 72 650 Td (Verifying pure-Python Markdown generation.) Tj ET\n"
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


# ==============================================================================
# 1. Dialect & Emitter Initialization Tests
# ==============================================================================

def test_resolve_dialect() -> None:
    """Test resolving dialects from enums and strings."""
    assert resolve_dialect(MarkdownDialect.GFM) == MarkdownDialect.GFM
    assert resolve_dialect(MarkdownDialect.COMMONMARK) == MarkdownDialect.COMMONMARK
    assert resolve_dialect("gfm") == MarkdownDialect.GFM
    assert resolve_dialect("github") == MarkdownDialect.GFM
    assert resolve_dialect("commonmark") == MarkdownDialect.COMMONMARK
    assert resolve_dialect("cm") == MarkdownDialect.COMMONMARK

    with pytest.raises(ValueError):
        resolve_dialect("invalid_dialect")

    with pytest.raises(TypeError):
        resolve_dialect(123)  # type: ignore[arg-type]


def test_markdown_emitter_init() -> None:
    """Test initializing MarkdownEmitter with dialects and options."""
    emitter = MarkdownEmitter()
    assert emitter.dialect == MarkdownDialect.GFM

    emitter_cm = MarkdownEmitter(dialect=MarkdownDialect.COMMONMARK)
    assert emitter_cm.dialect == MarkdownDialect.COMMONMARK


def test_markdown_emitter_empty_doc_raises() -> None:
    """Test that MarkdownEmitter raises SerializationError on empty DocumentIR."""
    doc_ir = DocumentIR(pages=[])
    emitter = MarkdownEmitter()
    with pytest.raises(SerializationError):
        emitter.emit(doc_ir)


# ==============================================================================
# 2. Heading & Formatting Tests
# ==============================================================================

def test_markdown_headings() -> None:
    """Test ATX heading generation for levels H1 through H6."""
    blocks: List[BlockNode] = [
        Paragraph(runs=[_make_run("Title 1")], heading_level=HeadingLevel.H1),
        Paragraph(runs=[_make_run("Title 2")], heading_level=HeadingLevel.H2),
        Paragraph(runs=[_make_run("Title 3")], heading_level=HeadingLevel.H3),
        Paragraph(runs=[_make_run("Title 4")], heading_level=HeadingLevel.H4),
        Paragraph(runs=[_make_run("Title 5")], heading_level=HeadingLevel.H5),
        Paragraph(runs=[_make_run("Title 6")], heading_level=HeadingLevel.H6),
    ]
    doc = DocumentIR(pages=[DocumentPage(1, 612.0, 792.0, blocks=blocks)])
    text = MarkdownEmitter().render(doc)

    assert "# Title 1" in text
    assert "## Title 2" in text
    assert "### Title 3" in text
    assert "#### Title 4" in text
    assert "##### Title 5" in text
    assert "###### Title 6" in text


def test_markdown_inline_formatting() -> None:
    """Test inline formatting: bold, italic, bold-italic, code span, underline, strikethrough, autolink."""
    p = Paragraph(
        runs=[
            _make_run("Normal, "),
            _make_run("Bold, ", is_bold=True),
            _make_run("Italic, ", is_italic=True),
            _make_run("Both, ", is_bold=True, is_italic=True),
            _make_run("Code, ", font_name="CourierNew"),
            _make_run("Underline, ", is_underline=True),
            _make_run("Strike, ", is_strikethrough=True),
            _make_run("Super, ", baseline_offset=3.0),
            _make_run("Sub, ", baseline_offset=-3.0),
            _make_run("https://example.com"),
        ]
    )
    doc = DocumentIR(pages=[DocumentPage(1, 612.0, 792.0, blocks=[p])])

    # GFM dialect
    text_gfm = MarkdownEmitter(dialect=MarkdownDialect.GFM).render(doc)
    assert "**Bold, **" in text_gfm
    assert "*Italic, *" in text_gfm
    assert "***Both, ***" in text_gfm
    assert "`Code, `" in text_gfm
    assert "<u>Underline, </u>" in text_gfm
    assert "~~Strike, ~~" in text_gfm
    assert "<sup>Super, </sup>" in text_gfm
    assert "<sub>Sub, </sub>" in text_gfm
    assert "<https://example.com>" in text_gfm

    # CommonMark dialect (strikethrough falls back to HTML <s>)
    text_cm = MarkdownEmitter(dialect=MarkdownDialect.COMMONMARK).render(doc)
    assert "<s>Strike, </s>" in text_cm


# ==============================================================================
# 3. Lists & Task Lists Tests
# ==============================================================================

def test_markdown_lists_and_checklists() -> None:
    """Test unordered lists, nested levels, ordered lists, and GFM task checklists."""
    blocks: List[BlockNode] = [
        Paragraph(runs=[_make_run("Top bullet")], list_marker="•", list_level=0),
        Paragraph(runs=[_make_run("Nested bullet")], list_marker="•", list_level=1),
        Paragraph(runs=[_make_run("Step one")], list_marker="1.", list_level=0),
        Paragraph(runs=[_make_run("Step two")], list_marker="2.", list_level=0),
        Paragraph(runs=[_make_run("Open task")], list_marker="[ ]", list_level=0),
        Paragraph(runs=[_make_run("Done task")], list_marker="[x]", list_level=0),
    ]
    doc = DocumentIR(pages=[DocumentPage(1, 612.0, 792.0, blocks=blocks)])

    text_gfm = MarkdownEmitter(dialect=MarkdownDialect.GFM).render(doc)
    assert "- Top bullet" in text_gfm
    assert "  - Nested bullet" in text_gfm
    assert "1. Step one" in text_gfm
    assert "2. Step two" in text_gfm
    assert "- [ ] Open task" in text_gfm
    assert "- [x] Done task" in text_gfm


# ==============================================================================
# 4. Tables, Images, and Page Structure Tests
# ==============================================================================

def test_markdown_tables_and_escaping() -> None:
    """Test GFM tables with column alignment and pipe character escaping."""
    c1 = TableCell(content=[Paragraph(runs=[_make_run("Feature | Option")])], width=100.0)
    c2 = TableCell(content=[Paragraph(runs=[_make_run("Status")])], width=100.0)
    c3 = TableCell(content=[Paragraph(runs=[_make_run("Engine | Core")])], width=100.0)
    c4 = TableCell(content=[Paragraph(runs=[_make_run("Active")])], width=100.0)

    row1 = TableRow(cells=[c1, c2], height=20.0, is_header=True)
    row2 = TableRow(cells=[c3, c4], height=20.0, is_header=False)
    table = Table(rows=[row1, row2], col_widths=[120.0, 80.0], alignment=Alignment.CENTER)

    doc = DocumentIR(pages=[DocumentPage(1, 612.0, 792.0, blocks=[table])])
    text = MarkdownEmitter().render(doc)

    assert "Feature \\| Option" in text
    assert "Engine \\| Core" in text
    assert "| :---------------: | :----: |" in text


def test_markdown_complex_table_matrix_spans_and_multiline() -> None:
    """Test table matrix handling with col_span, row_span, multi-line cells, and ragged rows."""
    # Row 1 (Header): cell 1 has col_span=2
    hdr_c1 = TableCell(
        content=[Paragraph(runs=[_make_run("Spanned Header")])],
        col_span=2,
    )
    hdr_c2 = TableCell(content=[Paragraph(runs=[_make_run("Notes")])])
    row1 = TableRow(cells=[hdr_c1, hdr_c2], is_header=True)

    # Row 2: cell 1 has row_span=2, cell 2 has multi-paragraph content
    p_multi1 = Paragraph(runs=[_make_run("Line 1")])
    p_multi2 = Paragraph(runs=[_make_run("Line 2 | extra")])
    row2_c1 = TableCell(content=[Paragraph(runs=[_make_run("Spanned Row")])], row_span=2)
    row2_c2 = TableCell(content=[p_multi1, p_multi2])
    row2_c3 = TableCell(content=[Paragraph(runs=[_make_run("Trailing")])])
    row2 = TableRow(cells=[row2_c1, row2_c2, row2_c3])

    # Row 3: ragged row (only 1 cell provided, row2_c1 spans into column 0)
    row3_c2 = TableCell(content=[Paragraph(runs=[_make_run("Cell 3-2")])])
    row3 = TableRow(cells=[row3_c2])

    table = Table(rows=[row1, row2, row3])
    doc = DocumentIR(pages=[DocumentPage(1, 612.0, 792.0, blocks=[table])])
    text = MarkdownEmitter().render(doc)

    assert "Spanned Header" in text
    assert "Line 1<br>Line 2 \\| extra" in text
    assert "Spanned Row" in text
    assert "Cell 3-2" in text

    # Verify that each line has exact column count matching header (ignoring escaped pipes)
    table_lines = [ln for ln in text.splitlines() if ln.startswith("|")]
    assert len(table_lines) == 4  # header, delimiter, row2, row3
    for line in table_lines:
        assert line.replace(r"\|", "").count("|") == 4  # 3 columns require 4 delimiter pipes


def test_markdown_table_column_alignment_detection() -> None:
    """Test automatic column alignment resolution for left, right (numeric), and center."""
    h1 = TableCell(content=[Paragraph(runs=[_make_run("Item")])])
    h2 = TableCell(content=[Paragraph(runs=[_make_run("Price")])])
    h3 = TableCell(content=[Paragraph(runs=[_make_run("Status")])])
    row1 = TableRow(cells=[h1, h2, h3], is_header=True)

    d1 = TableCell(content=[Paragraph(runs=[_make_run("Widget")])])
    d2 = TableCell(content=[Paragraph(runs=[_make_run("$1,234.50")])])
    d3 = TableCell(content=[Paragraph(runs=[_make_run("Active")], alignment=Alignment.CENTER)])
    row2 = TableRow(cells=[d1, d2, d3])

    d4 = TableCell(content=[Paragraph(runs=[_make_run("Gadget")])])
    d5 = TableCell(content=[Paragraph(runs=[_make_run("$42.00")])])
    d6 = TableCell(content=[Paragraph(runs=[_make_run("Pending")], alignment=Alignment.CENTER)])
    row3 = TableRow(cells=[d4, d5, d6])

    table = Table(rows=[row1, row2, row3])
    doc = DocumentIR(pages=[DocumentPage(1, 612.0, 792.0, blocks=[table])])
    text = MarkdownEmitter().render(doc)

    # Delimiter row should have: Left (:---), Right (---:), Center (:---:)
    delims_line = [ln for ln in text.splitlines() if ":-" in ln or "-:" in ln][0]
    parts = [p.strip() for p in delims_line.strip("|").split("|")]
    assert parts[0].startswith(":") and not parts[0].endswith(":")  # Left
    assert not parts[1].startswith(":") and parts[1].endswith(":")  # Right (numeric)
    assert parts[2].startswith(":") and parts[2].endswith(":")      # Center


def test_markdown_fenced_code_blocks() -> None:
    """Test fenced code blocks with language hints and consecutive grouping."""
    p_code1 = Paragraph(runs=[_make_run("def calculate(x, y):", font_name="CourierNew")])
    p_code2 = Paragraph(runs=[_make_run("    return x * y + 1", font_name="CourierNew")])
    p_text = Paragraph(runs=[_make_run("A standard prose explanation.")])
    p_bash = Paragraph(runs=[_make_run("git status --short", font_name="LiberationMono")])

    doc = DocumentIR(pages=[DocumentPage(1, 612.0, 792.0, blocks=[p_code1, p_code2, p_text, p_bash])])
    text = MarkdownEmitter().render(doc)

    # p_code1 and p_code2 should be grouped into a single python code fence
    assert "```python\ndef calculate(x, y):\n    return x * y + 1\n```" in text
    assert "A standard prose explanation." in text
    # p_bash should be fenced as bash
    assert "```bash\ngit status --short\n```" in text


def test_markdown_code_fence_backtick_escaping() -> None:
    """Test that code blocks containing backticks use quadruple backticks."""
    code_with_backticks = "Use ```markdown to start a fence."
    p = Paragraph(runs=[_make_run(code_with_backticks, font_name="Consolas")])
    doc = DocumentIR(pages=[DocumentPage(1, 612.0, 792.0, blocks=[p])])
    text = MarkdownEmitter().render(doc)

    assert "````" in text
    assert code_with_backticks in text


def test_markdown_extended_task_lists() -> None:
    """Test Unicode ballot boxes, checkmarks, radio buttons, and text-embedded checkboxes."""
    blocks: List[BlockNode] = [
        Paragraph(runs=[_make_run("Unchecked ballot")], list_marker="☐"),
        Paragraph(runs=[_make_run("Checked ballot")], list_marker="☑"),
        Paragraph(runs=[_make_run("Checked X ballot")], list_marker="☒"),
        Paragraph(runs=[_make_run("Checkmark task")], list_marker="✓"),
        Paragraph(runs=[_make_run("Radio unselected")], list_marker="( )"),
        Paragraph(runs=[_make_run("Radio selected")], list_marker="(x)"),
        # Embedded in text without list_marker
        Paragraph(runs=[_make_run("[ ] Text embedded open task")]),
        Paragraph(runs=[_make_run("☑ Text embedded done task")]),
    ]
    doc = DocumentIR(pages=[DocumentPage(1, 612.0, 792.0, blocks=blocks)])
    text = MarkdownEmitter(dialect=MarkdownDialect.GFM).render(doc)

    assert "- [ ] Unchecked ballot" in text
    assert "- [x] Checked ballot" in text
    assert "- [x] Checked X ballot" in text
    assert "- [x] Checkmark task" in text
    assert "- [ ] Radio unselected" in text
    assert "- [x] Radio selected" in text
    assert "- [ ] Text embedded open task" in text
    assert "- [x] Text embedded done task" in text


def test_markdown_multipage_and_marginal_headers_footers() -> None:
    """Test marginal headers/footers rendered as blockquotes and horizontal rules for page breaks."""
    header = PageHeaderFooter(content=[Paragraph(runs=[_make_run("Confidential Document")])])
    footer = PageHeaderFooter(content=[Paragraph(runs=[_make_run("Page 1 of 2")])], is_footer=True)
    img = ImageBlock(png_bytes=b"\x89PNG\r\n\x1a\n", bbox=BoundingBox(0, 0, 50, 50), alt_text="Report Chart")

    p1 = Paragraph(runs=[_make_run("Content of page 1")])
    p2 = Paragraph(runs=[_make_run("Content of page 2")])

    page1 = DocumentPage(1, 612.0, 792.0, blocks=[p1, img], header=header, footer=footer)
    page2 = DocumentPage(2, 612.0, 792.0, blocks=[p2])

    doc = DocumentIR(pages=[page1, page2])
    text = MarkdownEmitter().render(doc)

    assert "> Confidential Document" in text
    assert "> Page 1 of 2" in text
    assert "![Report Chart](image_1.png)" in text
    assert "---" in text
    assert "Content of page 2" in text


# ==============================================================================
# 5. API & CLI Integration Tests
# ==============================================================================

def test_markdown_emitter_registration() -> None:
    """Verify that md is in SUPPORTED_FORMATS and _get_emitter instantiates MarkdownEmitter."""
    assert "md" in SUPPORTED_FORMATS
    emitter = _get_emitter("md")
    assert isinstance(emitter, MarkdownEmitter)
    assert isinstance(_get_emitter(".MD"), MarkdownEmitter)
    assert isinstance(_get_emitter("markdown"), MarkdownEmitter)


def test_markdown_convert_bytes() -> None:
    """Verify convert_bytes to Markdown."""
    pdf_bytes = _build_test_pdf()
    md_bytes = convert_bytes(pdf_bytes, output_format="md")

    assert isinstance(md_bytes, bytes)
    text = md_bytes.decode("utf-8")
    assert "Markdown Emitter Integration Test" in text
    assert "Verifying pure-Python Markdown generation." in text


def test_markdown_convert_file_to_file(tmp_path: pathlib.Path) -> None:
    """Verify file-to-file conversion via API to Markdown."""
    input_pdf = tmp_path / "doc.pdf"
    input_pdf.write_bytes(_build_test_pdf())
    output_md = tmp_path / "doc.md"

    res_bytes = convert(
        input_path=input_pdf,
        output_format="md",
        output_path=output_md,
    )

    assert output_md.is_file()
    assert output_md.stat().st_size == len(res_bytes)
    text = output_md.read_text(encoding="utf-8")
    assert "Markdown Emitter Integration Test" in text


def test_cli_markdown_conversion(tmp_path: pathlib.Path) -> None:
    """Verify CLI command: anyconvert input.pdf -f md -o output.md."""
    input_pdf = tmp_path / "cli_input.pdf"
    input_pdf.write_bytes(_build_test_pdf())
    output_md = tmp_path / "cli_output.md"

    exit_code = main([str(input_pdf), "-f", "md", "-o", str(output_md)])
    assert exit_code == 0
    assert output_md.is_file()
    text = output_md.read_text(encoding="utf-8")
    assert "Markdown Emitter Integration Test" in text


def test_cli_markdown_default_output_naming(tmp_path: pathlib.Path) -> None:
    """Verify CLI default output naming: anyconvert report.pdf -f md -> report.md."""
    input_pdf = tmp_path / "report.pdf"
    input_pdf.write_bytes(_build_test_pdf())

    exit_code = main([str(input_pdf), "-f", "md"])
    assert exit_code == 0

    expected_output = tmp_path / "report.md"
    assert expected_output.is_file()
    text = expected_output.read_text(encoding="utf-8")
    assert "Markdown Emitter Integration Test" in text


# ==============================================================================
# 6. Metadata & YAML Frontmatter Tests
# ==============================================================================

def test_pdf_date_parsing_and_frontmatter_helpers() -> None:
    """Test PDF date string conversion to ISO 8601 and YAML scalar escaping."""
    assert parse_pdf_date("D:20261030141205+03'00'") == "2026-10-30T14:12:05+03:00"
    assert parse_pdf_date("D:20261030141205Z") == "2026-10-30T14:12:05Z"
    assert parse_pdf_date("D:20261030") == "2026-10-30"
    assert parse_pdf_date("D:202610") == "2026-10"
    assert parse_pdf_date("2026-10-29") == "2026-10-29"
    assert parse_pdf_date("D:20261399") == "D:20261399"  # Invalid month stays intact

    assert format_yaml_scalar('Report: "Q4" & Beyond') == '"Report: \\"Q4\\" & Beyond"'
    assert format_yaml_scalar("Line1\nLine2") == '"Line1\\nLine2"'
    assert parse_keywords("pdf, markdown; python, PDF") == ["pdf", "markdown", "python"]


def test_yaml_frontmatter_rendering_and_empty_handling() -> None:
    """Test structured YAML frontmatter output and omission when metadata is empty."""
    assert render_yaml_frontmatter({}) == ""
    assert render_yaml_frontmatter({"Title": "   ", "Author": ""}) == ""

    meta = {
        "Title": "Engine Guide: Part 1",
        "Author": "Word-Sys Team",
        "Subject": "Zero-dependency conversion",
        "Keywords": "pdf, markdown; static-site",
        "CreationDate": "D:20261118110000+03'00'",
        "Creator": "anyconvert",
        "CustomField": "Alpha",
    }
    fm = render_yaml_frontmatter(meta)
    assert fm.startswith("---\n")
    assert fm.endswith("\n---")
    assert 'title: "Engine Guide: Part 1"' in fm
    assert 'author: "Word-Sys Team"' in fm
    assert 'description: "Zero-dependency conversion"' in fm
    assert 'keywords:\n  - "pdf"\n  - "markdown"\n  - "static-site"' in fm
    assert 'date: "2026-11-18T11:00:00+03:00"' in fm
    assert 'creator: "anyconvert"' in fm
    assert 'customfield: "Alpha"' in fm

    norm = normalize_frontmatter_metadata(meta)
    assert list(norm.keys())[:5] == ["title", "author", "description", "keywords", "date"]


def test_markdown_emitter_frontmatter_toggle_and_txt_exclusion() -> None:
    """Verify MarkdownEmitter prepends frontmatter by default and TxtFlowEmitter omits it."""
    doc = DocumentIR(
        pages=[DocumentPage(1, 612.0, 792.0, blocks=[Paragraph(runs=[_make_run("Body text.")])])],
        metadata={"Title": "SSG Article", "Author": "Jane Doe"},
    )

    md_with_fm = MarkdownEmitter().render(doc)
    assert md_with_fm.startswith("---\ntitle: \"SSG Article\"\nauthor: \"Jane Doe\"\n---\n\nBody text.")

    md_no_fm = MarkdownEmitter(include_frontmatter=False).render(doc)
    assert not md_no_fm.startswith("---")
    assert md_no_fm.strip() == "Body text."

    txt_flow = TxtFlowEmitter().emit(doc).decode("utf-8")
    assert not txt_flow.startswith("---")
    assert txt_flow.strip() == "Body text."


def test_pdf_info_dictionary_frontmatter_e2e() -> None:
    """Verify end-to-end PDF /Info extraction (including indirect string refs) to YAML frontmatter."""
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
            b"BT /F1 12 Tf 72 700 Td (Document body content.) Tj ET\n"
            b"endstream\nendobj\n"
        ),
        (
            b"5 0 obj\n<< /Title 6 0 R /Author (Alice Writer) "
            b"/Subject (Documentation: Hugo & Jekyll) "
            b"/Keywords (hugo, jekyll, vitepress) "
            b"/CreationDate (D:20261118093000Z) >>\nendobj\n"
        ),
        b"6 0 obj\n(Frontmatter E2E Title)\nendobj\n",
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
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R /Info 5 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )

    md_text = convert_bytes(bytes(out), output_format="md").decode("utf-8")
    assert md_text.startswith("---\n")
    assert 'title: "Frontmatter E2E Title"' in md_text
    assert 'author: "Alice Writer"' in md_text
    assert 'description: "Documentation: Hugo & Jekyll"' in md_text
    assert '  - "hugo"\n  - "jekyll"\n  - "vitepress"' in md_text
    assert 'date: "2026-11-18T09:30:00Z"' in md_text
    assert "Document body content." in md_text


# ==============================================================================
# 7. Image Extraction Mode (--extract-images) Tests
# ==============================================================================

def _build_pdf_with_images() -> bytes:
    """Build a synthetic PDF containing both a DCTDecode JPEG image and FlateDecode PNG image."""
    # Minimal valid 1x1 JPEG header + EOI bytes
    jpeg_bytes = (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xd9"
    )
    # 1x1 RGB raw pixels compressed with FlateDecode (will be converted to PNG by PDFImage)
    flate_pixels = zlib.compress(b"\x10\x20\x30")

    content_stream = (
        b"BT /F1 12 Tf 72 720 Td (Embedded Media Test) Tj ET\n"
        b"q 100 0 0 100 72 550 cm /Im1 Do Q\n"
        b"q 80 0 0 80 200 550 cm /Im2 Do Q\n"
    )

    objs: List[bytes] = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Count 1 /Kids [3 0 R] >>\nendobj\n",
        (
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 << /Type /Font "
            b"/Subtype /Type1 /BaseFont /Helvetica >> >> "
            b"/XObject << /Im1 5 0 R /Im2 6 0 R >> >> >>\nendobj\n"
        ),
        (
            f"4 0 obj\n<< /Length {len(content_stream)} >>\nstream\n".encode("ascii")
            + content_stream
            + b"\nendstream\nendobj\n"
        ),
        (
            f"5 0 obj\n<< /Type /XObject /Subtype /Image /Width 1 /Height 1 "
            f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode "
            f"/Length {len(jpeg_bytes)} >>\nstream\n".encode("ascii")
            + jpeg_bytes
            + b"\nendstream\nendobj\n"
        ),
        (
            f"6 0 obj\n<< /Type /XObject /Subtype /Image /Width 1 /Height 1 "
            f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode "
            f"/Length {len(flate_pixels)} >>\nstream\n".encode("ascii")
            + flate_pixels
            + b"\nendstream\nendobj\n"
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


def test_markdown_emitter_extract_images_to_dir(tmp_path: pathlib.Path) -> None:
    """Test MarkdownEmitter writing JPEG and PNG assets to image_dir."""
    jpeg_data = b"\xff\xd8\xff\xe0TESTJPEG\xff\xd9"
    png_data = b"\x89PNG\r\n\x1a\nTESTPNG"

    img1 = ImageBlock(
        image_bytes=jpeg_data,
        bbox=BoundingBox(0, 0, 100, 100),
        alt_text="Photo",
        format="png",  # Intentionally mismatched to verify sync_format()
    )
    img2 = ImageBlock(
        image_bytes=png_data,
        bbox=BoundingBox(0, 120, 100, 220),
        alt_text="Diagram",
        format="png",
    )
    doc = DocumentIR(pages=[DocumentPage(1, 612.0, 792.0, blocks=[img1, img2])])

    assets_dir = tmp_path / "assets"
    emitter = MarkdownEmitter(image_dir=assets_dir, image_link_prefix="assets")
    md_text = emitter.render(doc)

    assert "![Photo](assets/img_1.jpeg)" in md_text
    assert "![Diagram](assets/img_2.png)" in md_text
    assert (assets_dir / "img_1.jpeg").read_bytes() == jpeg_data
    assert (assets_dir / "img_2.png").read_bytes() == png_data
    assert len(emitter.extracted_images) == 2


def test_api_and_cli_extract_images_e2e(tmp_path: pathlib.Path) -> None:
    """Test end-to-end PDF image extraction via API and CLI --extract-images [DIR]."""
    pdf_bytes = _build_pdf_with_images()
    pdf_path = tmp_path / "media.pdf"
    pdf_path.write_bytes(pdf_bytes)

    # 1. API with explicit custom asset directory
    out_md_custom = tmp_path / "custom.md"
    custom_assets = tmp_path / "my_assets"
    convert(
        pdf_path,
        output_format="md",
        output_path=out_md_custom,
        extract_images=custom_assets,
    )
    custom_text = out_md_custom.read_text(encoding="utf-8")
    assert "![Im1](my_assets/img_1.jpeg)" in custom_text
    assert "![Im2](my_assets/img_2.png)" in custom_text
    assert (custom_assets / "img_1.jpeg").is_file()
    assert (custom_assets / "img_2.png").is_file()
    assert (custom_assets / "img_1.jpeg").read_bytes().startswith(b"\xff\xd8\xff")
    assert (custom_assets / "img_2.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")

    # 2. API with extract_images=True (defaults to 'images/' beside output)
    sub_dir = tmp_path / "sub"
    sub_dir.mkdir()
    out_md_default = sub_dir / "article.md"
    convert(
        pdf_path,
        output_format="md",
        output_path=out_md_default,
        extract_images=True,
    )
    default_text = out_md_default.read_text(encoding="utf-8")
    assert "![Im1](images/img_1.jpeg)" in default_text
    assert "![Im2](images/img_2.png)" in default_text
    assert (sub_dir / "images" / "img_1.jpeg").is_file()
    assert (sub_dir / "images" / "img_2.png").is_file()

    # 3. CLI: anyconvert input.pdf -f md -o out.md --extract-images ./assets/
    cli_dir = tmp_path / "cli_run"
    cli_dir.mkdir()
    cli_out = cli_dir / "out.md"
    cli_assets = cli_dir / "assets"
    exit_code = main([
        str(pdf_path),
        "-f",
        "md",
        "-o",
        str(cli_out),
        "--extract-images",
        str(cli_assets),
    ])
    assert exit_code == 0
    cli_text = cli_out.read_text(encoding="utf-8")
    assert "![Im1](assets/img_1.jpeg)" in cli_text
    assert "![Im2](assets/img_2.png)" in cli_text
    assert (cli_assets / "img_1.jpeg").is_file()
    assert (cli_assets / "img_2.png").is_file()

    # 4. CLI without DIR argument (flag before positional input recovery)
    cli_no_dir_out = cli_dir / "auto" / "doc.md"
    exit_code_2 = main([
        "--extract-images",
        str(pdf_path),
        "-f",
        "md",
        "-o",
        str(cli_no_dir_out),
    ])
    assert exit_code_2 == 0
    auto_text = cli_no_dir_out.read_text(encoding="utf-8")
    assert "![Im1](images/img_1.jpeg)" in auto_text
    assert "![Im2](images/img_2.png)" in auto_text
    assert (cli_dir / "auto" / "images" / "img_1.jpeg").is_file()
    assert (cli_dir / "auto" / "images" / "img_2.png").is_file()

    # 5. convert_bytes with extract_images directory
    bytes_assets = tmp_path / "bytes_assets"
    bytes_md = convert_bytes(
        pdf_bytes,
        output_format="md",
        extract_images=bytes_assets,
    ).decode("utf-8")
    assert "img_1.jpeg)" in bytes_md
    assert (bytes_assets / "img_1.jpeg").is_file()
    assert (bytes_assets / "img_2.png").is_file()
