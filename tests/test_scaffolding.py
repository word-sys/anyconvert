"""Test suite for Phase 1 scaffolding, packaging, typing, and exceptions."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import unittest

import anyconvert
from anyconvert.cli import create_parser, main
from anyconvert.exceptions import (
    AnyConvertError,
    ConversionError,
    DOCXEmitterError,
    EmitterError,
    IRError,
    IRValidationError,
    LayoutError,
    ODFPackagingError,
    ODPEmitterError,
    ODTEmitterError,
    OPCPackagingError,
    PackagingError,
    PDFCorruptStreamError,
    PDFCryptoError,
    PDFError,
    PDFFilterError,
    PDFFontError,
    PDFGraphicsError,
    PDFInvalidPasswordError,
    PDFPasswordRequiredError,
    PDFSecurityError,
    PDFSyntaxError,
    PDFTrailerNotFoundError,
    PDFUnsupportedFilterError,
    PDFUnsupportedSecurityHandlerError,
    PDFXRefError,
    PPTXEmitterError,
    TableReconstructionError,
    TXTEmitterError,
    UnsupportedFormatError,
)


class TestScaffolding(unittest.TestCase):
    """Verifies packaging metadata, typed marker, and module entrypoint."""

    def test_version_string(self) -> None:
        """Version string must be a valid semver string."""
        self.assertIsInstance(anyconvert.__version__, str)
        self.assertTrue(len(anyconvert.__version__.split(".")) >= 2)

    def test_py_typed_marker_exists(self) -> None:
        """PEP 561 py.typed marker file must exist in package root."""
        pkg_dir = Path(anyconvert.__file__).parent
        py_typed = pkg_dir / "py.typed"
        self.assertTrue(py_typed.is_file(), f"Missing py.typed in {pkg_dir}")

    def test_all_exports_present(self) -> None:
        """All symbols declared in __all__ must be resolvable attributes."""
        for sym in anyconvert.__all__:
            self.assertTrue(hasattr(anyconvert, sym), f"Missing export: {sym}")


class TestExceptionHierarchy(unittest.TestCase):
    """Verifies exception inheritance, attributes, and string representations."""

    def test_root_exception(self) -> None:
        err = AnyConvertError("Root test failure")
        self.assertIsInstance(err, Exception)
        self.assertEqual(str(err), "Root test failure")
        self.assertEqual(err.message, "Root test failure")

    def test_pdf_syntax_error_with_offset(self) -> None:
        err = PDFSyntaxError("Malformed token", offset=1024)
        self.assertIsInstance(err, PDFError)
        self.assertIsInstance(err, AnyConvertError)
        self.assertEqual(err.offset, 1024)
        self.assertIn("at byte offset 1024", str(err))

    def test_pdf_filter_error_attributes(self) -> None:
        err = PDFUnsupportedFilterError("/JBIG2Decode")
        self.assertIsInstance(err, PDFFilterError)
        self.assertEqual(err.filter_name, "/JBIG2Decode")
        self.assertIn("/JBIG2Decode", str(err))

    def test_unsupported_format_error(self) -> None:
        err = UnsupportedFormatError("Format not supported", format_name="epub")
        self.assertIsInstance(err, AnyConvertError)
        self.assertEqual(err.format_name, "epub")

    def test_hierarchy_branches(self) -> None:
        # PDF branches
        self.assertTrue(issubclass(PDFSyntaxError, PDFError))
        self.assertTrue(issubclass(PDFXRefError, PDFError))
        self.assertTrue(issubclass(PDFTrailerNotFoundError, PDFXRefError))
        self.assertTrue(issubclass(PDFSecurityError, PDFError))
        self.assertTrue(issubclass(PDFPasswordRequiredError, PDFSecurityError))
        self.assertTrue(issubclass(PDFInvalidPasswordError, PDFSecurityError))
        self.assertTrue(issubclass(PDFUnsupportedSecurityHandlerError, PDFSecurityError))
        self.assertTrue(issubclass(PDFCryptoError, PDFSecurityError))
        self.assertTrue(issubclass(PDFFilterError, PDFError))
        self.assertTrue(issubclass(PDFCorruptStreamError, PDFFilterError))
        self.assertTrue(issubclass(PDFFontError, PDFError))
        self.assertTrue(issubclass(PDFGraphicsError, PDFError))

        # Layout, IR, Packaging, Emitters
        self.assertTrue(issubclass(TableReconstructionError, LayoutError))
        self.assertTrue(issubclass(LayoutError, AnyConvertError))
        self.assertTrue(issubclass(IRValidationError, IRError))
        self.assertTrue(issubclass(IRError, AnyConvertError))
        self.assertTrue(issubclass(OPCPackagingError, PackagingError))
        self.assertTrue(issubclass(ODFPackagingError, PackagingError))
        self.assertTrue(issubclass(PackagingError, AnyConvertError))
        self.assertTrue(issubclass(DOCXEmitterError, EmitterError))
        self.assertTrue(issubclass(PPTXEmitterError, EmitterError))
        self.assertTrue(issubclass(ODTEmitterError, EmitterError))
        self.assertTrue(issubclass(ODPEmitterError, EmitterError))
        self.assertTrue(issubclass(TXTEmitterError, EmitterError))
        self.assertTrue(issubclass(EmitterError, AnyConvertError))
        self.assertTrue(issubclass(ConversionError, AnyConvertError))


class TestCLI(unittest.TestCase):
    """Verifies command line interface argument parser and invocation."""

    def test_parser_defaults(self) -> None:
        parser = create_parser()
        args = parser.parse_args(["sample.pdf"])
        self.assertEqual(args.input, "sample.pdf")
        self.assertEqual(args.mode, "flow")
        self.assertIsNone(args.format)
        self.assertFalse(args.verbose)

    def test_parser_options(self) -> None:
        parser = create_parser()
        args = parser.parse_args([
            "doc.pdf",
            "-f", "pptx",
            "-o", "out.pptx",
            "-m", "canvas",
            "-p", "secret",
            "--verbose",
        ])
        self.assertEqual(args.input, "doc.pdf")
        self.assertEqual(args.format, "pptx")
        self.assertEqual(args.output, "out.pptx")
        self.assertEqual(args.mode, "canvas")
        self.assertEqual(args.password, "secret")
        self.assertTrue(args.verbose)

    def test_main_without_args_returns_code_1(self) -> None:
        code = main([])
        self.assertEqual(code, 1)

    def test_cli_execution_via_subprocess(self) -> None:
        res = subprocess.run(
            [sys.executable, "-m", "anyconvert", "--version"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn(f"anyconvert {anyconvert.__version__}", res.stdout)


if __name__ == "__main__":
    unittest.main()
