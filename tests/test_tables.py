"""
Unit and integration tests for Part 3: Native Table Detection Engine.
"""

from pathlib import Path
import pytest
import pymupdf

import anyconvert
from anyconvert.analysis.layout import extract_page_layout
from anyconvert.analysis.tables import detect_page_tables, is_block_inside_table
from anyconvert.core.models import ParagraphBlock, Rect, TableBlock
from anyconvert.core.options import ConversionOptions





def test_detect_page_tables(table_pdf: Path):
    doc = pymupdf.open(str(table_pdf))
    page = doc[0]

    tables = detect_page_tables(page)
    assert len(tables) == 1

    tbl = tables[0]
    assert tbl.rows == 3
    assert tbl.cols == 3

    matrix = tbl.as_matrix()
    assert matrix[0] == ["Item", "Qty", "Price"]
    assert matrix[1] == ["Widget", "5", "$10.00"]
    assert matrix[2] == ["Gadget", "2", "$25.00"]
    doc.close()


def test_table_block_filtering_in_layout(table_pdf: Path):
    doc = pymupdf.open(str(table_pdf))
    page = doc[0]
    opts = ConversionOptions(detect_tables=True)

    page_ir = extract_page_layout(doc, page, opts)

    tables = [b for b in page_ir.blocks if isinstance(b, TableBlock)]
    paragraphs = [b for b in page_ir.blocks if isinstance(b, ParagraphBlock)]

    assert len(tables) == 1
    # Check that table contents are not duplicated in regular paragraphs
    for p in paragraphs:
        assert "Widget" not in p.text
        assert "$25.00" not in p.text

    # Preceding and trailing paragraphs still exist
    assert any("Product Inventory Table" in p.text for p in paragraphs)
    assert any("End of Inventory Report" in p.text for p in paragraphs)
    doc.close()


def test_table_to_markdown_export(table_pdf: Path, tmp_path: Path):
    out_md = tmp_path / "table.md"
    res = anyconvert.convert(table_pdf, out_md)

    assert res.success
    content = out_md.read_text(encoding="utf-8")

    assert "| Item | Qty | Price |" in content
    assert "| --- | --- | --- |" in content
    assert "| Widget | 5 | $10.00 |" in content
    assert "| Gadget | 2 | $25.00 |" in content
    assert "Product Inventory Table" in content
    assert "End of Inventory Report" in content


def test_table_to_text_export(table_pdf: Path, tmp_path: Path):
    out_txt = tmp_path / "table.txt"
    res = anyconvert.convert(table_pdf, out_txt)

    assert res.success
    content = out_txt.read_text(encoding="utf-8")

    assert "Item\tQty\tPrice" in content
    assert "Widget\t5\t$10.00" in content


def test_no_tables_page(tmp_path: Path):
    pdf_path = tmp_path / "no_tables.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=300)
    page.insert_text((50, 50), "Just plain text without any tables.", fontsize=12)
    doc.save(str(pdf_path))

    tables = detect_page_tables(page)
    assert tables == []
    doc.close()
