"""Unit tests for Phase 1 scaffolding, packaging configuration, and exceptions."""

from __future__ import annotations

import pathlib
import subprocess
import sys
import unittest

import anyconvert
from anyconvert.exceptions import (
    AnyConvertError,
    EmitterError,
    IRBuilderError,
    IRError,
    IRValidationError,
    LayoutError,
    PackagingError,
    PDFFontError,
    PDFError,
    PDFObjectError,
    PDFPasswordRequiredError,
    PDFSecurityError,
    PDFStreamError,
    PDFSyntaxError,
    PDFUnsupportedFilterError,
    SerializationError,
    SpatialIndexError,
    TableReconstructionError,
    UnsupportedFormatError,
    XYCutError,
)
from anyconvert.cli import create_parser, main


class TestScaffoldingAndPackaging(unittest.TestCase):
    """Tests package metadata and packaging configuration."""

    def test_package_metadata(self) -> None:
        """Verify top-level package metadata."""
        self.assertEqual(anyconvert.__version__, "0.1.0")
        self.assertTrue(isinstance(anyconvert.__author__, str))
        self.assertTrue(isinstance(anyconvert.__license__, str))

    def test_py_typed_exists(self) -> None:
        """Verify PEP 561 marker file exists."""
        pkg_dir = pathlib.Path(anyconvert.__file__).parent
        py_typed = pkg_dir / "py.typed"
        self.assertTrue(py_typed.exists(), "py.typed marker file must exist in package root")

    def test_cli_version_flag(self) -> None:
        """Verify that invoking CLI with --version returns the correct version string."""
        cmd = [sys.executable, "-m", "anyconvert", "--version"]
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(pathlib.Path(__file__).parent.parent),
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn(anyconvert.__version__, result.stdout)

    def test_cli_argument_parsing(self) -> None:
        """Verify argument parser accepts all documented flags."""
        parser = create_parser()

        # Test defaults
        args = parser.parse_args(["sample.pdf"])
        self.assertEqual(args.input, "sample.pdf")
        self.assertEqual(args.format, "docx")
        self.assertEqual(args.mode, "flow")
        self.assertEqual(args.password, "")
        self.assertFalse(args.verbose)

        # Test custom options
        args_custom = parser.parse_args(
            ["sample.pdf", "-f", "pptx", "-o", "out.pptx", "-m", "canvas", "-p", "secret", "-v"]
        )
        self.assertEqual(args_custom.input, "sample.pdf")
        self.assertEqual(args_custom.format, "pptx")
        self.assertEqual(args_custom.output, "out.pptx")
        self.assertEqual(args_custom.mode, "canvas")
        self.assertEqual(args_custom.password, "secret")
        self.assertTrue(args_custom.verbose)

    def test_cli_main_entrypoint(self) -> None:
        """Verify main() function handles arguments."""
        # No input should return 1 (failure)
        exit_code = main([])
        self.assertEqual(exit_code, 1)

        # Missing input should return 1
        exit_code_missing = main(["nonexistent_file.pdf", "-f", "odt"])
        self.assertEqual(exit_code_missing, 1)

        # Valid input should return 0
        import tempfile
        pdf_bytes = (
            b"%PDF-1.4\n"
            b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
            b"2 0 obj\n<< /Type /Pages /Count 1 /Kids [3 0 R] >>\nendobj\n"
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>\nendobj\n"
            b"4 0 obj\n<< /Length 44 >>\nstream\n"
            b"BT /F1 12 Tf 72 400 Td (Hello World) Tj ET\n"
            b"endstream\nendobj\n"
        )
        off1 = pdf_bytes.find(b"1 0 obj")
        off2 = pdf_bytes.find(b"2 0 obj")
        off3 = pdf_bytes.find(b"3 0 obj")
        off4 = pdf_bytes.find(b"4 0 obj")
        xref_pos = len(pdf_bytes)
        xref_bytes = (
            b"xref\n"
            b"0 5\n"
            b"0000000000 65535 f\r\n"
            + f"{off1:010d} 00000 n\r\n".encode("ascii")
            + f"{off2:010d} 00000 n\r\n".encode("ascii")
            + f"{off3:010d} 00000 n\r\n".encode("ascii")
            + f"{off4:010d} 00000 n\r\n".encode("ascii")
            + b"trailer\n"
            b"<< /Size 5 /Root 1 0 R >>\n"
            b"startxref\n"
            + f"{xref_pos}\n".encode("ascii")
            + b"%%EOF\n"
        )
        full_pdf = pdf_bytes + xref_bytes
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_pdf = pathlib.Path(tmp_dir) / "test.pdf"
            test_pdf.write_bytes(full_pdf)
            exit_code = main([str(test_pdf), "-f", "odt"])
            self.assertEqual(exit_code, 0)


class TestExceptionHierarchy(unittest.TestCase):
    """Tests the anyconvert exception hierarchy."""

    def test_base_exception(self) -> None:
        """Verify AnyConvertError base functionality and formatting."""
        err = AnyConvertError("Root error", details={"code": 404})
        self.assertIsInstance(err, Exception)
        self.assertEqual(err.message, "Root error")
        self.assertEqual(err.details["code"], 404)
        self.assertIn("Root error", str(err))
        self.assertIn("code=404", str(err))

    def test_pdf_syntax_error(self) -> None:
        """Verify PDFSyntaxError tracks offset."""
        err = PDFSyntaxError("Unexpected token", offset=1024)
        self.assertIsInstance(err, PDFError)
        self.assertIsInstance(err, AnyConvertError)
        self.assertEqual(err.offset, 1024)
        self.assertEqual(err.details.get("offset"), 1024)

    def test_pdf_object_error(self) -> None:
        """Verify PDFObjectError tracks obj_id and generation."""
        err = PDFObjectError("Missing object", obj_id=12, generation=0)
        self.assertIsInstance(err, PDFError)
        self.assertEqual(err.obj_id, 12)
        self.assertEqual(err.generation, 0)

    def test_pdf_security_errors(self) -> None:
        """Verify PDF security exceptions."""
        err = PDFPasswordRequiredError("Password required to decrypt document")
        self.assertIsInstance(err, PDFSecurityError)
        self.assertIsInstance(err, PDFError)

    def test_pdf_filter_error(self) -> None:
        """Verify PDFUnsupportedFilterError stores filter_name."""
        err = PDFUnsupportedFilterError("/JBIG2Decode")
        self.assertIsInstance(err, PDFError)
        self.assertEqual(err.filter_name, "/JBIG2Decode")
        self.assertIn("/JBIG2Decode", str(err))

    def test_layout_exceptions(self) -> None:
        """Verify layout analysis exceptions."""
        self.assertTrue(issubclass(SpatialIndexError, LayoutError))
        self.assertTrue(issubclass(XYCutError, LayoutError))
        self.assertTrue(issubclass(TableReconstructionError, LayoutError))
        self.assertTrue(issubclass(LayoutError, AnyConvertError))

    def test_ir_exceptions(self) -> None:
        """Verify Intermediate Representation exceptions."""
        self.assertTrue(issubclass(IRValidationError, IRError))
        self.assertTrue(issubclass(IRBuilderError, IRError))
        self.assertTrue(issubclass(IRError, AnyConvertError))

    def test_emitter_exceptions(self) -> None:
        """Verify emitter and packaging exceptions."""
        self.assertTrue(issubclass(PackagingError, EmitterError))
        self.assertTrue(issubclass(SerializationError, EmitterError))
        self.assertTrue(issubclass(UnsupportedFormatError, EmitterError))
        self.assertTrue(issubclass(EmitterError, AnyConvertError))

        unsupp = UnsupportedFormatError("xyz", supported_formats=["docx", "pptx"])
        self.assertEqual(unsupp.format_name, "xyz")
        self.assertEqual(unsupp.supported_formats, ["docx", "pptx"])
        self.assertIn("xyz", str(unsupp))


if __name__ == "__main__":
    unittest.main()
