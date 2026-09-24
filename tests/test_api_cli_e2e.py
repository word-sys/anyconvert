"""Comprehensive End-to-End integration tests for anyconvert API, CLI, and all 5 emitters."""

from __future__ import annotations

import hashlib
import io
import pathlib
import struct
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from typing import List, Tuple

from anyconvert.api import (
    ConversionMode,
    convert,
    convert_bytes,
    pdf_to_document_ir,
)
from anyconvert.cli import main
from anyconvert.emitters.base import xml_escape
from anyconvert.exceptions import (
    PDFPasswordRequiredError,
    PDFSyntaxError,
    UnsupportedFormatError,
)
from anyconvert.pdf.crypto.handler import PASSWORD_PADDING
from anyconvert.pdf.crypto.rc4 import rc4_crypt


def build_synthetic_multipage_pdf() -> bytes:
    """Generate a clean, multi-page synthetic PDF containing headings, lists, text, vectors, and metadata."""
    objs: List[bytes] = [
        # Object 1: Catalog
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        # Object 2: Page tree with 2 pages
        b"2 0 obj\n<< /Type /Pages /Count 2 /Kids [3 0 R 5 0 R] >>\nendobj\n",
        # Object 3: Page 1 (US Letter, 612x792 pt)
        (
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 << /Type /Font "
            b"/Subtype /Type1 /BaseFont /Helvetica >> >> >> >>\nendobj\n"
        ),
        # Object 4: Page 1 content stream (heading, list, paragraphs, and vector box)
        (
            b"4 0 obj\n<< /Length 285 >>\nstream\n"
            b"BT /F1 18 Tf 72 700 Td (Annual Corporate Report 2026) Tj ET\n"
            b"BT /F1 12 Tf 72 650 Td (- Global Operations Overview) Tj ET\n"
            b"BT /F1 10 Tf 72 600 Td (The company demonstrated robust financial performance across all quarters.) Tj ET\n"
            b"72 450 200 60 re S\n"
            b"BT /F1 10 Tf 80 480 Td (Quarter 1 Revenue: $4.2B) Tj ET\n"
            b"endstream\nendobj\n"
        ),
        # Object 5: Page 2 (US Letter, 612x792 pt)
        (
            b"5 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 6 0 R /Resources << /Font << /F1 << /Type /Font "
            b"/Subtype /Type1 /BaseFont /Helvetica >> >> >> >>\nendobj\n"
        ),
        # Object 6: Page 2 content stream
        (
            b"6 0 obj\n<< /Length 195 >>\nstream\n"
            b"BT /F1 16 Tf 72 700 Td (Strategic Vision & Sustainability) Tj ET\n"
            b"BT /F1 10 Tf 72 650 Td (Continued investment in renewable energy and zero-waste initiatives.) Tj ET\n"
            b"endstream\nendobj\n"
        ),
        # Object 7: Document Metadata (/Info)
        (
            b"7 0 obj\n<< /Title (Annual Corporate Report) /Author (AnyConvert Test Suite) "
            b"/Subject (End-to-End Verification) /Creator (anyconvert engine) >>\nendobj\n"
        ),
    ]

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets: List[int] = [0]
    for obj in objs:
        offsets.append(out.tell())
        out.write(obj)

    xref_pos = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f\r\n".encode("ascii"))
    for off in offsets[1:]:
        out.write(f"{off:010d} 00000 n\r\n".encode("ascii"))

    trailer = f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R /Info 7 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n"
    out.write(trailer.encode("ascii"))
    return out.getvalue()


def build_encrypted_pdf(password: bytes = b"topsecret") -> bytes:
    """Generate an encrypted PDF adhering to standard revision 2 security."""
    pwd_padded = password + PASSWORD_PADDING[: 32 - len(password)]
    o_val = b"0" * 32
    p_val = -64
    doc_id = b"TestDocumentId12"

    m = hashlib.md5()
    m.update(pwd_padded)
    m.update(o_val)
    m.update(struct.pack("<i", p_val))
    m.update(doc_id)
    doc_key = m.digest()[:5]
    u_val = rc4_crypt(doc_key, PASSWORD_PADDING)

    # Object 4 is content stream, encrypt its data
    obj_key_hash = hashlib.md5(doc_key + b"\x04\x00\x00\x00\x00").digest()[:10]
    plain_stream = b"BT /F1 12 Tf 72 500 Td (Confidential Financial Data) Tj ET\n"
    enc_stream = rc4_crypt(obj_key_hash, plain_stream)

    o_val_hex = o_val.hex()
    u_val_hex = u_val.hex()
    doc_id_hex = doc_id.hex()

    objs: List[bytes] = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Count 1 /Kids [3 0 R] >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>\nendobj\n",
        f"4 0 obj\n<< /Length {len(enc_stream)} >>\nstream\n".encode("ascii") + enc_stream + b"\nendstream\nendobj\n",
        f"5 0 obj\n<< /Filter /Standard /V 1 /R 2 /O <{o_val_hex}> /U <{u_val_hex}> /P {p_val} /Length 40 >>\nendobj\n".encode("ascii"),
    ]

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets: List[int] = [0]
    for obj in objs:
        offsets.append(out.tell())
        out.write(obj)

    xref_pos = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f\r\n".encode("ascii"))
    for off in offsets[1:]:
        out.write(f"{off:010d} 00000 n\r\n".encode("ascii"))

    trailer = (
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R /Encrypt 5 0 R "
        f"/ID [<{doc_id_hex}> <{doc_id_hex}>] >>\nstartxref\n{xref_pos}\n%%EOF\n"
    )
    out.write(trailer.encode("ascii"))
    return out.getvalue()


class TestEndToEndConversion(unittest.TestCase):
    """End-to-End tests for document conversion across all 5 target formats."""

    pdf_bytes: bytes

    @classmethod
    def setUpClass(cls) -> None:
        cls.pdf_bytes = build_synthetic_multipage_pdf()

    def test_docx_conversion_flow_mode(self) -> None:
        """Verify end-to-end PDF to DOCX Flow Mode conversion."""
        docx_data = convert(self.pdf_bytes, output_format="docx", mode=ConversionMode.FLOW)
        self.assertIsInstance(docx_data, bytes)
        self.assertGreater(len(docx_data), 1000)

        with zipfile.ZipFile(io.BytesIO(docx_data)) as z:
            names = z.namelist()
            self.assertIn("[Content_Types].xml", names)
            self.assertIn("_rels/.rels", names)
            self.assertIn("word/document.xml", names)
            self.assertIn("word/styles.xml", names)
            doc_xml = z.read("word/document.xml").decode("utf-8")
            self.assertIn("Annual Corporate Report", doc_xml)
            self.assertIn("Strategic Vision", doc_xml)

    def test_docx_conversion_canvas_mode(self) -> None:
        """Verify end-to-end PDF to DOCX Canvas Mode conversion."""
        docx_data = convert(self.pdf_bytes, output_format="docx", mode=ConversionMode.CANVAS)
        self.assertIsInstance(docx_data, bytes)
        with zipfile.ZipFile(io.BytesIO(docx_data)) as z:
            names = z.namelist()
            self.assertIn("word/document.xml", names)
            doc_xml = z.read("word/document.xml").decode("utf-8")
            self.assertIn("Annual Corporate Report", doc_xml)

    def test_pptx_conversion_flow_mode(self) -> None:
        """Verify end-to-end PDF to PPTX Flow Mode conversion."""
        pptx_data = convert(self.pdf_bytes, output_format="pptx", mode=ConversionMode.FLOW)
        self.assertIsInstance(pptx_data, bytes)
        with zipfile.ZipFile(io.BytesIO(pptx_data)) as z:
            names = z.namelist()
            self.assertIn("[Content_Types].xml", names)
            self.assertIn("ppt/presentation.xml", names)
            self.assertIn("ppt/slides/slide1.xml", names)
            self.assertIn("ppt/slides/slide2.xml", names)
            slide1_xml = z.read("ppt/slides/slide1.xml").decode("utf-8")
            self.assertIn("Annual Corporate Report", slide1_xml)
            slide2_xml = z.read("ppt/slides/slide2.xml").decode("utf-8")
            self.assertIn("Strategic Vision", slide2_xml)

    def test_pptx_conversion_canvas_mode(self) -> None:
        """Verify end-to-end PDF to PPTX Canvas Mode conversion."""
        pptx_data = convert(self.pdf_bytes, output_format="pptx", mode=ConversionMode.CANVAS)
        self.assertIsInstance(pptx_data, bytes)
        with zipfile.ZipFile(io.BytesIO(pptx_data)) as z:
            names = z.namelist()
            self.assertIn("ppt/slides/slide1.xml", names)
            self.assertIn("ppt/slides/slide2.xml", names)

    def test_odt_conversion_flow_mode(self) -> None:
        """Verify end-to-end PDF to ODT Flow Mode conversion and ISO/IEC 26300 packaging."""
        odt_data = convert(self.pdf_bytes, output_format="odt", mode=ConversionMode.FLOW)
        self.assertIsInstance(odt_data, bytes)

        # In ODF, mimetype must be stored uncompressed at offset 0
        with zipfile.ZipFile(io.BytesIO(odt_data)) as z:
            infolist = z.infolist()
            self.assertEqual(infolist[0].filename, "mimetype")
            self.assertEqual(infolist[0].compress_type, zipfile.ZIP_STORED)
            mimetype_content = z.read("mimetype")
            self.assertEqual(mimetype_content, b"application/vnd.oasis.opendocument.text")
            self.assertIn("content.xml", z.namelist())
            self.assertIn("META-INF/manifest.xml", z.namelist())
            content_xml = z.read("content.xml").decode("utf-8")
            self.assertIn("Annual Corporate Report", content_xml)

    def test_odt_conversion_canvas_mode(self) -> None:
        """Verify end-to-end PDF to ODT Canvas Mode conversion."""
        odt_data = convert(self.pdf_bytes, output_format="odt", mode=ConversionMode.CANVAS)
        self.assertIsInstance(odt_data, bytes)
        with zipfile.ZipFile(io.BytesIO(odt_data)) as z:
            self.assertEqual(z.read("mimetype"), b"application/vnd.oasis.opendocument.text")
            content_xml = z.read("content.xml").decode("utf-8")
            self.assertIn("Annual Corporate Report", content_xml)

    def test_odp_conversion_flow_mode(self) -> None:
        """Verify end-to-end PDF to ODP Flow Mode conversion."""
        odp_data = convert(self.pdf_bytes, output_format="odp", mode=ConversionMode.FLOW)
        self.assertIsInstance(odp_data, bytes)
        with zipfile.ZipFile(io.BytesIO(odp_data)) as z:
            self.assertEqual(z.infolist()[0].filename, "mimetype")
            self.assertEqual(z.infolist()[0].compress_type, zipfile.ZIP_STORED)
            self.assertEqual(z.read("mimetype"), b"application/vnd.oasis.opendocument.presentation")
            self.assertIn("content.xml", z.namelist())
            content_xml = z.read("content.xml").decode("utf-8")
            self.assertIn("Annual Corporate Report", content_xml)

    def test_odp_conversion_canvas_mode(self) -> None:
        """Verify end-to-end PDF to ODP Canvas Mode conversion."""
        odp_data = convert(self.pdf_bytes, output_format="odp", mode=ConversionMode.CANVAS)
        self.assertIsInstance(odp_data, bytes)
        with zipfile.ZipFile(io.BytesIO(odp_data)) as z:
            self.assertEqual(z.read("mimetype"), b"application/vnd.oasis.opendocument.presentation")

    def test_txt_conversion_flow_and_canvas(self) -> None:
        """Verify end-to-end PDF to Plaintext (Markdown Flow and Spatial Canvas)."""
        # Flow mode: Markdown headings and page break
        txt_flow = convert(self.pdf_bytes, output_format="txt", mode="flow").decode("utf-8")
        self.assertIn("# Annual Corporate Report 2026", txt_flow)
        self.assertIn("Global Operations Overview", txt_flow)
        self.assertIn("---", txt_flow)
        self.assertIn("Strategic Vision", txt_flow)

        # Canvas mode: 2D character positioning and form feed
        txt_canvas = convert(self.pdf_bytes, output_format="txt", mode="canvas").decode("utf-8")
        self.assertIn("Annual", txt_canvas)
        self.assertIn("Corporate", txt_canvas)
        self.assertIn("Report", txt_canvas)
        self.assertIn("\x0c", txt_canvas)
        self.assertIn("Strategic Vision", txt_canvas)


class TestAPIUsageAndEdgeCases(unittest.TestCase):
    """Tests for API convenience methods, argument validation, and error paths."""

    pdf_bytes: bytes

    @classmethod
    def setUpClass(cls) -> None:
        cls.pdf_bytes = build_synthetic_multipage_pdf()

    def test_convert_bytes(self) -> None:
        """Verify convert_bytes helper function."""
        res = convert_bytes(self.pdf_bytes, output_format="txt")
        self.assertIn(b"Annual Corporate Report", res)

    def test_convert_file_to_file(self) -> None:
        """Verify convert() reading from file path and writing to file path."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            in_file = pathlib.Path(tmp_dir) / "document.pdf"
            out_file = pathlib.Path(tmp_dir) / "output.docx"
            in_file.write_bytes(self.pdf_bytes)

            res_bytes = convert(in_file, output_format="docx", output_path=out_file)
            self.assertTrue(out_file.exists())
            self.assertEqual(out_file.stat().st_size, len(res_bytes))

    def test_pdf_to_document_ir(self) -> None:
        """Verify pdf_to_document_ir model extraction and metadata."""
        doc_ir = pdf_to_document_ir(self.pdf_bytes)
        self.assertEqual(len(doc_ir.pages), 2)
        self.assertEqual(doc_ir.pages[0].page_number, 1)
        self.assertEqual(doc_ir.pages[1].page_number, 2)
        self.assertEqual(doc_ir.metadata.get("Title"), "Annual Corporate Report")
        self.assertEqual(doc_ir.metadata.get("Author"), "AnyConvert Test Suite")

    def test_unsupported_format_raises(self) -> None:
        """Verify UnsupportedFormatError is raised for invalid target format."""
        with self.assertRaises(UnsupportedFormatError):
            convert(self.pdf_bytes, output_format="epub")

    def test_invalid_mode_raises(self) -> None:
        """Verify ValueError is raised for invalid conversion mode."""
        with self.assertRaises(ValueError):
            convert(self.pdf_bytes, output_format="docx", mode="invalid_mode")

    def test_empty_pdf_raises(self) -> None:
        """Verify PDFSyntaxError is raised when trying to convert invalid empty data."""
        with self.assertRaises(PDFSyntaxError):
            convert(b"%PDF-1.4\n%%EOF\n", output_format="docx")


class TestEncryptedPDFConversion(unittest.TestCase):
    """Tests for encrypted PDF decryption and conversion."""

    enc_pdf: bytes

    @classmethod
    def setUpClass(cls) -> None:
        cls.enc_pdf = build_encrypted_pdf(password=b"topsecret")

    def test_encrypted_pdf_success_with_password(self) -> None:
        """Verify encrypted PDF converts cleanly with valid password."""
        txt = convert(self.enc_pdf, output_format="txt", password="topsecret")
        self.assertIn(b"Confidential Financial Data", txt)

        docx = convert(self.enc_pdf, output_format="docx", password="topsecret")
        self.assertGreater(len(docx), 1000)

    def test_encrypted_pdf_fails_with_wrong_password(self) -> None:
        """Verify PDFPasswordRequiredError is raised with wrong password."""
        with self.assertRaises(PDFPasswordRequiredError):
            convert(self.enc_pdf, output_format="txt", password="wrongpassword")


class TestCLIExecution(unittest.TestCase):
    """Tests for CLI main() entrypoint."""

    pdf_bytes: bytes

    @classmethod
    def setUpClass(cls) -> None:
        cls.pdf_bytes = build_synthetic_multipage_pdf()

    def test_cli_help(self) -> None:
        """Verify CLI exits with code 1 when no arguments are provided."""
        self.assertEqual(main([]), 1)

    def test_cli_successful_file_conversion(self) -> None:
        """Verify CLI converts files successfully from command-line arguments."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            in_file = pathlib.Path(tmp_dir) / "input.pdf"
            out_file = pathlib.Path(tmp_dir) / "output.odt"
            in_file.write_bytes(self.pdf_bytes)

            exit_code = main([str(in_file), "-f", "odt", "-o", str(out_file), "-v"])
            self.assertEqual(exit_code, 0)
            self.assertTrue(out_file.exists())
            self.assertGreater(out_file.stat().st_size, 500)

    def test_cli_default_output_naming(self) -> None:
        """Verify CLI defaults output file name to input with target extension."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            in_file = pathlib.Path(tmp_dir) / "report.pdf"
            expected_out = pathlib.Path(tmp_dir) / "report.txt"
            in_file.write_bytes(self.pdf_bytes)

            exit_code = main([str(in_file), "-f", "txt"])
            self.assertEqual(exit_code, 0)
            self.assertTrue(expected_out.exists())
            self.assertIn("Annual Corporate Report", expected_out.read_text(encoding="utf-8"))

    def test_cli_missing_input_file(self) -> None:
        """Verify CLI returns error code 1 when input file is not found."""
        exit_code = main(["nonexistent_file_path.pdf", "-f", "docx"])
        self.assertEqual(exit_code, 1)


class TestRegressionFixes(unittest.TestCase):
    """Regression test suite for CMap decompression, XML sanitization, and real PDF conversions."""

    def test_xml_sanitization(self) -> None:
        """Verify xml_escape eliminates ASCII control characters prohibited by XML 1.0."""
        dirty = "Hello\x00\x03\x04\x08World\x0b\x0c\x0e\x1f!\x09\x0a\x0d"
        clean = xml_escape(dirty)
        self.assertEqual(clean, "HelloWorld!\t\n\r")
        root = ET.fromstring(f"<root>{clean}</root>")
        self.assertIn("HelloWorld!", root.text or "")

    def test_real_target_pdf_conversion_if_present(self) -> None:
        """Verify end-to-end conversion of the target PDF if present on desktop."""
        target_pdf = pathlib.Path("/home/word-sys/Desktop/edited_document1qwe.pdf")
        if not target_pdf.exists():
            self.skipTest("Target PDF not present in environment")

        # 1. DOCX Canvas conversion
        docx_bytes = convert(target_pdf, "docx", mode="canvas")
        self.assertGreater(len(docx_bytes), 50000)
        zf_docx = zipfile.ZipFile(io.BytesIO(docx_bytes))
        for name in zf_docx.namelist():
            if name.endswith(".xml"):
                ET.fromstring(zf_docx.read(name))
        doc_xml = zf_docx.read("word/document.xml").decode("utf-8")
        self.assertIn("word-sys", doc_xml)

        # 2. ODT Canvas conversion
        odt_bytes = convert(target_pdf, "odt", mode="canvas")
        self.assertGreater(len(odt_bytes), 50000)
        zf_odt = zipfile.ZipFile(io.BytesIO(odt_bytes))
        for name in zf_odt.namelist():
            if name.endswith(".xml"):
                ET.fromstring(zf_odt.read(name))
        content_xml = zf_odt.read("content.xml").decode("utf-8")
        self.assertIn("word-sys", content_xml)

        # 3. TXT Flow conversion
        txt_bytes = convert(target_pdf, "txt", mode="flow")
        txt_str = txt_bytes.decode("utf-8")
        self.assertIn("word-sys", txt_str)
        self.assertNotIn("+HOOR", txt_str)


if __name__ == "__main__":
    unittest.main()
