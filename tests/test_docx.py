"""
Unit and integration tests for Part 4: Native DOCX Synthesizer.
"""

from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile
import pytest

import anyconvert


def test_pdf_to_docx_file_conversion(sample_pdf: Path, tmp_path: Path):
    out_docx = tmp_path / "report.docx"
    res = anyconvert.convert(sample_pdf, out_docx)

    assert res.success
    assert res.page_count == 2
    assert out_docx.exists()
    assert zipfile.is_zipfile(out_docx)

    # Inspect the OpenXML package
    with zipfile.ZipFile(out_docx, "r") as zf:
        file_list = zf.namelist()
        assert "[Content_Types].xml" in file_list
        assert "_rels/.rels" in file_list
        assert "word/document.xml" in file_list
        assert "word/styles.xml" in file_list
        assert "word/_rels/document.xml.rels" in file_list
        assert any(f.startswith("word/media/") for f in file_list)

        doc_xml_bytes = zf.read("word/document.xml")
        root = ET.fromstring(doc_xml_bytes)
        assert root.tag.endswith("document")

        doc_text = doc_xml_bytes.decode("utf-8")
        assert "Annual Tech Report" in doc_text
        assert "Executive Overview" in doc_text
        assert "Lossless layout preservation" in doc_text
        assert "Architecture Details" in doc_text


def test_pdf_to_docx_tables(table_pdf: Path, tmp_path: Path):
    out_docx = tmp_path / "table.docx"
    res = anyconvert.convert(table_pdf, out_docx)

    assert res.success
    assert res.tables_count >= 1
    assert out_docx.exists()

    with zipfile.ZipFile(out_docx, "r") as zf:
        doc_text = zf.read("word/document.xml").decode("utf-8")
        assert "<w:tbl>" in doc_text or "<w:tbl " in doc_text
        assert "Item" in doc_text
        assert "Widget" in doc_text
        assert "$10.00" in doc_text
        assert "Gadget" in doc_text


def test_pdf_to_docx_bytes(sample_pdf: Path):
    pdf_bytes = sample_pdf.read_bytes()
    docx_bytes = anyconvert.convert_bytes(pdf_bytes, to_format="docx")

    assert docx_bytes.startswith(b"PK\x03\x04")

    # Read the in-memory bytes using ZipFile
    import io
    with zipfile.ZipFile(io.BytesIO(docx_bytes), "r") as zf:
        assert "word/document.xml" in zf.namelist()
        doc_xml = zf.read("word/document.xml").decode("utf-8")
        assert "Annual Tech Report" in doc_xml
