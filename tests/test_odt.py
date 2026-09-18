"""
Unit and integration tests for Part 5: Native ODT Synthesizer.
"""

from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile
import pytest

import anyconvert


def test_pdf_to_odt_file_conversion(sample_pdf: Path, tmp_path: Path):
    out_odt = tmp_path / "report.odt"
    res = anyconvert.convert(sample_pdf, out_odt)

    assert res.success
    assert res.page_count == 2
    assert out_odt.exists()
    assert zipfile.is_zipfile(out_odt)

    # Inspect the OASIS OpenDocument package
    with zipfile.ZipFile(out_odt, "r") as zf:
        file_list = zf.namelist()

        # mimetype must be the very first file entry
        assert file_list[0] == "mimetype"
        mimetype_bytes = zf.read("mimetype")
        assert mimetype_bytes == b"application/vnd.oasis.opendocument.text"

        # Required ODF files
        assert "META-INF/manifest.xml" in file_list
        assert "styles.xml" in file_list
        assert "meta.xml" in file_list
        assert "content.xml" in file_list
        assert any(f.startswith("Pictures/") for f in file_list)

        content_xml_bytes = zf.read("content.xml")
        root = ET.fromstring(content_xml_bytes)
        assert root.tag.endswith("document-content")

        content_text = content_xml_bytes.decode("utf-8")
        assert "Annual Tech Report" in content_text
        assert "Executive Overview" in content_text
        assert "Lossless layout preservation" in content_text
        assert "Architecture Details" in content_text


def test_pdf_to_odt_tables(table_pdf: Path, tmp_path: Path):
    out_odt = tmp_path / "table.odt"
    res = anyconvert.convert(table_pdf, out_odt)

    assert res.success
    assert res.tables_count >= 1
    assert out_odt.exists()

    with zipfile.ZipFile(out_odt, "r") as zf:
        content_text = zf.read("content.xml").decode("utf-8")
        assert "<table:table" in content_text
        assert "Item" in content_text
        assert "Widget" in content_text
        assert "$10.00" in content_text
        assert "Gadget" in content_text


def test_pdf_to_odt_bytes(sample_pdf: Path):
    pdf_bytes = sample_pdf.read_bytes()
    odt_bytes = anyconvert.convert_bytes(pdf_bytes, to_format="odt")

    assert odt_bytes.startswith(b"PK\x03\x04")
    assert b"application/vnd.oasis.opendocument.text" in odt_bytes

    import io
    with zipfile.ZipFile(io.BytesIO(odt_bytes), "r") as zf:
        assert "content.xml" in zf.namelist()
        content_xml = zf.read("content.xml").decode("utf-8")
        assert "Annual Tech Report" in content_xml
