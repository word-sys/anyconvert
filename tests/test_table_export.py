"""Tests for structured table extraction and export emitters (CSV, XLSX, CLI table options)."""

from __future__ import annotations

import csv
import io
import pathlib
from typing import List, Set
import xml.etree.ElementTree as ET
import zipfile

import pytest

from anyconvert.api import SUPPORTED_FORMATS, _get_emitter, convert, convert_bytes
from anyconvert.cli import create_parser, main
from anyconvert.common.color import Color
from anyconvert.emitters.csv import (
    CsvEmitter,
    extract_tables_from_ir,
    table_to_grid,
)
from anyconvert.emitters.xlsx import XlsxEmitter
from anyconvert.exceptions import PackagingError, SerializationError
from anyconvert.ir.model import (
    BlockNode,
    DocumentIR,
    DocumentPage,
    Paragraph,
    Table,
    TableCell,
    TableRow,
    TextRun,
)
from anyconvert.packaging.xlsx import (
    SPREADSHEETML_NS,
    XLSXPackage,
    cell_ref,
    col_index_to_letter,
    merge_range_ref,
    sanitize_sheet_name,
    sanitize_xlsx_text,
)


def _cell(text: str, *, col_span: int = 1, row_span: int = 1) -> TableCell:
    """Create a TableCell with a single plain Paragraph."""
    paras: List[BlockNode] = [
        Paragraph(runs=[TextRun(line, "Helvetica", 10.0, Color.black())])
        for line in text.split("\n")
    ]
    return TableCell(content=paras, col_span=col_span, row_span=row_span)


def _build_pdf_with_statement_table() -> bytes:
    """Build a valid single-page PDF containing a vector-ruled 3x3 financial statement table."""
    # Grid rulings: x in {50, 170, 350, 470}, y in {400, 440, 480, 520} (PDF bottom-up coords)
    stream_lines = [
        # Horizontal rules
        "50 520 m 470 520 l S",
        "50 480 m 470 480 l S",
        "50 440 m 470 440 l S",
        "50 400 m 470 400 l S",
        # Vertical rules
        "50 400 m 50 520 l S",
        "170 400 m 170 520 l S",
        "350 400 m 350 520 l S",
        "470 400 m 470 520 l S",
        # Row 0 (header): y ~ 495
        "BT /F1 10 Tf 60 495 Td (Date) Tj ET",
        "BT /F1 10 Tf 180 495 Td (Description) Tj ET",
        "BT /F1 10 Tf 360 495 Td (Amount) Tj ET",
        # Row 1: y ~ 455
        "BT /F1 10 Tf 60 455 Td (2026-11-01) Tj ET",
        "BT /F1 10 Tf 180 455 Td (Acme, Inc. Cloud) Tj ET",
        "BT /F1 10 Tf 360 455 Td ($1,250.00) Tj ET",
        # Row 2: y ~ 415
        "BT /F1 10 Tf 60 415 Td (2026-11-02) Tj ET",
        "BT /F1 10 Tf 180 415 Td (Office Supplies) Tj ET",
        "BT /F1 10 Tf 360 415 Td ($89.50) Tj ET",
    ]
    stream = ("\n".join(stream_lines) + "\n").encode("ascii")

    objs: List[bytes] = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Count 1 /Kids [3 0 R] >>\nendobj\n",
        (
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 << /Type /Font "
            b"/Subtype /Type1 /BaseFont /Helvetica >> >> >> >>\nendobj\n"
        ),
        (
            f"4 0 obj\n<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            + stream
            + b"endstream\nendobj\n"
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


def test_table_to_grid_spans_and_nested_content() -> None:
    """Verify 2D occupancy normalization for col_span, row_span, fill_merged_cells, and merges."""
    tbl = Table(
        rows=[
            TableRow(
                cells=[
                    _cell("Region", col_span=2),
                    _cell("Q1"),
                ],
                is_header=True,
            ),
            TableRow(
                cells=[
                    _cell("EMEA", row_span=2),
                    _cell("North"),
                    _cell("120"),
                ]
            ),
            TableRow(
                cells=[
                    _cell("South"),
                    _cell("145"),
                ]
            ),
        ],
        col_widths=[100.0, 100.0, 80.0],
    )

    grid, hdr_count, merges = table_to_grid(tbl, fill_merged_cells=False)
    assert hdr_count == 1
    assert grid == [
        ["Region", "", "Q1"],
        ["EMEA", "North", "120"],
        ["", "South", "145"],
    ]
    assert merges == [(0, 0, 0, 1), (1, 0, 2, 0)]

    filled_grid, _, _ = table_to_grid(tbl, fill_merged_cells=True)
    assert filled_grid == [
        ["Region", "Region", "Q1"],
        ["EMEA", "North", "120"],
        ["EMEA", "South", "145"],
    ]


def test_multipage_continuous_table_merging_and_indexing() -> None:
    """Verify continuous multi-page tables merge with header deduplication, while separated tables stay distinct."""
    tbl_p1 = Table(
        rows=[
            TableRow(cells=[_cell("Date"), _cell("Item"), _cell("Total")], is_header=True),
            TableRow(cells=[_cell("2026-01-01"), _cell("Alpha"), _cell("10.00")]),
        ],
        col_widths=[100.0, 200.0, 80.0],
    )
    # Continuation at top of page 2 with repeated header row
    tbl_p2_cont = Table(
        rows=[
            TableRow(cells=[_cell("Date"), _cell("Item"), _cell("Total")], is_header=True),
            TableRow(cells=[_cell("2026-01-02"), _cell("Beta"), _cell("25.50")]),
        ],
        col_widths=[102.0, 198.0, 80.0],
    )
    # Separate table on page 3 preceded by a heading paragraph
    heading_p3 = Paragraph(runs=[TextRun("Summary Section", "Helvetica-Bold", 14.0, Color.black())])
    tbl_p3_sep = Table(
        rows=[
            TableRow(cells=[_cell("Metric"), _cell("Count")], is_header=True),
            TableRow(cells=[_cell("Transactions"), _cell("2")]),
        ],
        col_widths=[180.0, 80.0],
    )

    doc = DocumentIR(
        pages=[
            DocumentPage(1, 612.0, 792.0, blocks=[tbl_p1]),
            DocumentPage(2, 612.0, 792.0, blocks=[tbl_p2_cont]),
            DocumentPage(3, 612.0, 792.0, blocks=[heading_p3, tbl_p3_sep]),
        ]
    )

    merged_tables = extract_tables_from_ir(doc, merge_multipage=True)
    assert len(merged_tables) == 2
    assert merged_tables[0].index == 0
    assert merged_tables[0].page_numbers == [1, 2]
    assert merged_tables[0].rows == [
        ["Date", "Item", "Total"],
        ["2026-01-01", "Alpha", "10.00"],
        ["2026-01-02", "Beta", "25.50"],
    ]
    assert merged_tables[1].index == 1
    assert merged_tables[1].page_numbers == [3]
    assert merged_tables[1].rows == [["Metric", "Count"], ["Transactions", "2"]]

    # Opt-out keeps all 3 tables distinct
    unmerged = extract_tables_from_ir(doc, merge_multipage=False)
    assert len(unmerged) == 3

    # Multi-table indexing selection
    csv_t0 = CsvEmitter(table_index=0).render(doc)
    rows_t0 = list(csv.reader(io.StringIO(csv_t0)))
    assert rows_t0 == merged_tables[0].rows

    csv_t1 = CsvEmitter(table_index=1).render(doc)
    rows_t1 = list(csv.reader(io.StringIO(csv_t1)))
    assert rows_t1 == merged_tables[1].rows

    # Out-of-range table_index raises SerializationError
    with pytest.raises(SerializationError, match="out of range"):
        CsvEmitter(table_index=5).render(doc)


def test_csv_rfc4180_quoting_delimiters_bom_and_edge_cases() -> None:
    """Verify RFC 4180 CRLF quoting for commas, quotes, and newlines, plus BOM and empty cases."""
    tbl = Table(
        rows=[
            TableRow(cells=[_cell("Company"), _cell("Quote"), _cell("Notes")], is_header=True),
            TableRow(cells=[_cell("Acme, Inc."), _cell('Said "Hello"'), _cell("Line 1\nLine 2")]),
        ],
        col_widths=[120.0, 120.0, 160.0],
    )
    doc = DocumentIR(pages=[DocumentPage(1, 612.0, 792.0, blocks=[tbl])])

    raw_bytes = CsvEmitter().emit(doc)
    assert b"\r\n" in raw_bytes
    text = raw_bytes.decode("utf-8")
    assert '"Acme, Inc."' in text
    assert '"Said ""Hello"""' in text
    assert '"Line 1\nLine 2"' in text

    parsed = list(csv.reader(io.StringIO(text)))
    assert parsed == [
        ["Company", "Quote", "Notes"],
        ["Acme, Inc.", 'Said "Hello"', "Line 1\nLine 2"],
    ]

    # UTF-8 BOM and semicolon delimiter
    semi_bytes = CsvEmitter(delimiter=";", utf8_bom=True).emit(doc)
    assert semi_bytes.startswith(b"\xef\xbb\xbf")
    assert b"Company;Quote;Notes\r\n" in semi_bytes

    # Empty DocumentIR raises SerializationError
    with pytest.raises(SerializationError):
        CsvEmitter().emit(DocumentIR(pages=[]))

    # Document with pages but no tables: empty bytes for default, error when table_index set
    no_tbl_doc = DocumentIR(
        pages=[DocumentPage(1, 612.0, 792.0, blocks=[Paragraph(runs=[TextRun("Just prose", "H", 11.0, Color.black())])])]
    )
    assert CsvEmitter().emit(no_tbl_doc) == b""
    with pytest.raises(SerializationError, match="No tables found"):
        CsvEmitter(table_index=0).emit(no_tbl_doc)


def test_csv_api_and_cli_end_to_end(tmp_path: pathlib.Path) -> None:
    """Verify 'csv' format registration and end-to-end PDF-to-CSV conversion via API and CLI."""
    assert "csv" in SUPPORTED_FORMATS
    assert isinstance(_get_emitter("csv"), CsvEmitter)

    parser = create_parser()
    fmt_action = next(a for a in parser._actions if a.dest == "format")
    assert fmt_action.choices is not None
    assert "csv" in fmt_action.choices

    pdf_bytes = _build_pdf_with_statement_table()
    csv_bytes = convert_bytes(pdf_bytes, output_format="csv")
    rows = list(csv.reader(io.StringIO(csv_bytes.decode("utf-8"))))
    assert len(rows) == 3
    assert rows[0] == ["Date", "Description", "Amount"]
    assert rows[1] == ["2026-11-01", "Acme, Inc. Cloud", "$1,250.00"]
    assert rows[2] == ["2026-11-02", "Office Supplies", "$89.50"]

    in_pdf = tmp_path / "statement.pdf"
    out_csv = tmp_path / "statement_out.csv"
    in_pdf.write_bytes(pdf_bytes)

    assert main([str(in_pdf), "-f", "csv", "-o", str(out_csv)]) == 0
    assert out_csv.is_file()
    cli_rows = list(csv.reader(io.StringIO(out_csv.read_text(encoding="utf-8"))))
    assert cli_rows == rows

    # Default output extension produces statement.csv
    assert main([str(in_pdf), "-f", "csv"]) == 0
    default_csv = tmp_path / "statement.csv"
    assert default_csv.is_file()

    # Direct API file-to-file
    api_csv = tmp_path / "api_statement.csv"
    convert(in_pdf, output_format="csv", output_path=api_csv)
    assert api_csv.is_file()


def test_xlsx_coordinate_and_sheet_name_helpers() -> None:
    """Verify A1 column/cell/merge references, sheet title sanitization, and XML character stripping."""
    assert col_index_to_letter(0) == "A"
    assert col_index_to_letter(25) == "Z"
    assert col_index_to_letter(26) == "AA"
    assert col_index_to_letter(51) == "AZ"
    assert col_index_to_letter(52) == "BA"
    assert col_index_to_letter(701) == "ZZ"
    assert col_index_to_letter(702) == "AAA"

    with pytest.raises(PackagingError):
        col_index_to_letter(-1)

    assert cell_ref(0, 0) == "A1"
    assert cell_ref(9, 2) == "C10"
    assert merge_range_ref(0, 0, 0, 1) == "A1:B1"
    assert merge_range_ref(1, 0, 2, 0) == "A2:A3"

    with pytest.raises(PackagingError):
        merge_range_ref(0, 0, 0, 0)

    used: Set[str] = set()
    assert sanitize_sheet_name("  'Sales: Q1/Q2* [2026]?'  ", used) == "Sales Q1 Q2 2026"
    assert sanitize_sheet_name("Sales: Q1/Q2* [2026]?", used) == "Sales Q1 Q2 2026 (2)"
    long_title = "A" * 45
    assert len(sanitize_sheet_name(long_title, used)) == 31
    assert len(sanitize_sheet_name(long_title, used)) <= 31

    # Illegal C0 control chars stripped while preserving tab/newline and escaping entities
    assert sanitize_xlsx_text("A\x00\x07&B<C>\nD") == "A&amp;B&lt;C&gt;\nD"

    # Zero-sheet workbook raises PackagingError
    with pytest.raises(PackagingError, match="zero worksheets"):
        XLSXPackage().to_bytes()


def test_xlsx_emitter_structure_merges_shared_strings_and_types() -> None:
    """Verify ISO/IEC 29500-2 XLSX archive structure, sharedStrings, numeric cells, and <mergeCell>."""
    tbl1 = Table(
        rows=[
            TableRow(
                cells=[
                    _cell("Region", col_span=2),
                    _cell("Revenue"),
                    _cell("Code"),
                ],
                is_header=True,
            ),
            TableRow(
                cells=[
                    _cell("EMEA", row_span=2),
                    _cell("North"),
                    _cell("1250.5"),
                    _cell("0042"),
                ]
            ),
            TableRow(
                cells=[
                    _cell("South"),
                    _cell("-40"),
                    _cell("Line 1\nLine 2"),
                ]
            ),
        ],
        col_widths=[100.0, 100.0, 80.0, 70.0],
    )
    tbl2 = Table(
        rows=[
            TableRow(cells=[_cell("KPI"), _cell("Status")], is_header=True),
            TableRow(cells=[_cell("Margin"), _cell("Healthy")]),
        ],
        col_widths=[140.0, 100.0],
    )

    doc = DocumentIR(
        pages=[
            DocumentPage(1, 612.0, 792.0, blocks=[tbl1]),
            DocumentPage(
                2,
                612.0,
                792.0,
                blocks=[
                    Paragraph(runs=[TextRun("Section 2", "Helvetica", 14.0, Color.black())]),
                    tbl2,
                ],
            ),
        ],
        metadata={"Title": "Quarterly Financials", "Author": "Finance Ops"},
    )

    xlsx_bytes = XlsxEmitter().emit(doc)
    with zipfile.ZipFile(io.BytesIO(xlsx_bytes), "r") as zf:
        names = set(zf.namelist())
        assert "[Content_Types].xml" in names
        assert "_rels/.rels" in names
        assert "xl/workbook.xml" in names
        assert "xl/_rels/workbook.xml.rels" in names
        assert "xl/styles.xml" in names
        assert "xl/sharedStrings.xml" in names
        assert "xl/worksheets/sheet1.xml" in names
        assert "xl/worksheets/sheet2.xml" in names
        assert "docProps/core.xml" in names
        assert "docProps/app.xml" in names

        # Parse and verify every XML part is well-formed
        for name in names:
            if name.endswith(".xml") or name.endswith(".rels"):
                ET.fromstring(zf.read(name))

        ns = {"s": SPREADSHEETML_NS}
        wb_root = ET.fromstring(zf.read("xl/workbook.xml"))
        sheet_els = wb_root.findall("s:sheets/s:sheet", ns)
        assert [el.attrib["name"] for el in sheet_els] == ["Table 1", "Table 2"]

        # Verify shared strings table (leading zeros and multi-line text stored with xml:space="preserve")
        sst_root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
        sst_texts = [t.text or "" for t in sst_root.findall("s:si/s:t", ns)]
        assert "Region" in sst_texts
        assert "0042" in sst_texts
        assert "Line 1\nLine 2" in sst_texts

        # Verify sheet1 dimension, columns, merged cells, and numeric vs string cells
        ws1_root = ET.fromstring(zf.read("xl/worksheets/sheet1.xml"))
        dim_el = ws1_root.find("s:dimension", ns)
        assert dim_el is not None and dim_el.attrib["ref"] == "A1:D3"

        cols = ws1_root.findall("s:cols/s:col", ns)
        assert len(cols) == 4

        merges = [m.attrib["ref"] for m in ws1_root.findall("s:mergeCells/s:mergeCell", ns)]
        assert merges == ["A1:B1", "A2:A3"]

        # C2 ("1250.5") and C3 ("-40") emitted as numeric cells (no t="s"), while D2 ("0042") is t="s"
        cells_by_ref = {
            c.attrib["r"]: c
            for c in ws1_root.findall("s:sheetData/s:row/s:c", ns)
        }
        assert "t" not in cells_by_ref["C2"].attrib
        v_c2 = cells_by_ref["C2"].find("s:v", ns)
        assert v_c2 is not None and v_c2.text == "1250.5"
        assert "t" not in cells_by_ref["C3"].attrib
        v_c3 = cells_by_ref["C3"].find("s:v", ns)
        assert v_c3 is not None and v_c3.text == "-40"
        assert cells_by_ref["D2"].attrib.get("t") == "s"

    # Single-table selection via table_index=1
    single_bytes = XlsxEmitter(table_index=1).emit(doc)
    with zipfile.ZipFile(io.BytesIO(single_bytes), "r") as zf:
        wb_single = ET.fromstring(zf.read("xl/workbook.xml"))
        sheets_single = wb_single.findall(f"{{{SPREADSHEETML_NS}}}sheets/{{{SPREADSHEETML_NS}}}sheet")
        assert len(sheets_single) == 1
        assert sheets_single[0].attrib["name"] == "Table 2"

    with pytest.raises(SerializationError, match="out of range"):
        XlsxEmitter(table_index=9).emit(doc)

    # Fallback Document sheet when no tables exist (vs export_tables_only=True)
    prose_doc = DocumentIR(
        pages=[DocumentPage(1, 612.0, 792.0, blocks=[Paragraph(runs=[TextRun("Cover Page", "H", 12.0, Color.black())])])]
    )
    fallback_bytes = XlsxEmitter().emit(prose_doc)
    with zipfile.ZipFile(io.BytesIO(fallback_bytes), "r") as zf:
        wb_fb = ET.fromstring(zf.read("xl/workbook.xml"))
        fb_sheets = wb_fb.findall(f"{{{SPREADSHEETML_NS}}}sheets/{{{SPREADSHEETML_NS}}}sheet")
        assert len(fb_sheets) == 1
        assert fb_sheets[0].attrib["name"] == "Document"

    with pytest.raises(SerializationError, match="No tables found"):
        XlsxEmitter(export_tables_only=True).emit(prose_doc)
    with pytest.raises(SerializationError):
        XlsxEmitter().emit(DocumentIR(pages=[]))


def test_xlsx_api_and_cli_end_to_end(tmp_path: pathlib.Path) -> None:
    """Verify 'xlsx' format registration and end-to-end PDF-to-XLSX conversion via API and CLI."""
    assert "xlsx" in SUPPORTED_FORMATS
    assert isinstance(_get_emitter("xlsx"), XlsxEmitter)

    parser = create_parser()
    fmt_action = next(a for a in parser._actions if a.dest == "format")
    assert fmt_action.choices is not None
    assert "xlsx" in fmt_action.choices

    pdf_bytes = _build_pdf_with_statement_table()
    xlsx_bytes = convert_bytes(pdf_bytes, output_format="xlsx")
    with zipfile.ZipFile(io.BytesIO(xlsx_bytes), "r") as zf:
        assert "xl/workbook.xml" in zf.namelist()
        assert "xl/worksheets/sheet1.xml" in zf.namelist()
        sst_xml = zf.read("xl/sharedStrings.xml").decode("utf-8")
        assert "Acme, Inc. Cloud" in sst_xml
        assert "$1,250.00" in sst_xml

    in_pdf = tmp_path / "report.pdf"
    out_xlsx = tmp_path / "report_out.xlsx"
    in_pdf.write_bytes(pdf_bytes)

    assert main([str(in_pdf), "-f", "xlsx", "-o", str(out_xlsx)]) == 0
    assert out_xlsx.is_file()
    with zipfile.ZipFile(out_xlsx, "r") as zf:
        assert "xl/worksheets/sheet1.xml" in zf.namelist()

    # Default output extension produces report.xlsx
    assert main([str(in_pdf), "-f", "xlsx"]) == 0
    assert (tmp_path / "report.xlsx").is_file()

    # Direct API file-to-file
    api_xlsx = tmp_path / "api_report.xlsx"
    convert(in_pdf, output_format="xlsx", output_path=api_xlsx)
    assert api_xlsx.is_file()

