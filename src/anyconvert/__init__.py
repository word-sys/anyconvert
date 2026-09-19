"""anyconvert: Enterprise document conversion engine in pure Python.

High-performance, zero-dependency PDF document conversion to DOCX, PPTX, ODT, ODP,
and TXT with mathematical precision and dual-mode layout reconstruction.
"""

from __future__ import annotations

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

__version__ = "0.1.0"
__author__ = "anyconvert contributors"
__license__ = "GPL-3.0-or-later"

__all__ = [
    "__version__",
    "__author__",
    "__license__",
    "AnyConvertError",
    "PDFError",
    "PDFSyntaxError",
    "PDFObjectError",
    "PDFSecurityError",
    "PDFPasswordRequiredError",
    "PDFUnsupportedFilterError",
    "PDFFontError",
    "PDFStreamError",
    "LayoutError",
    "SpatialIndexError",
    "XYCutError",
    "TableReconstructionError",
    "IRError",
    "IRValidationError",
    "IRBuilderError",
    "EmitterError",
    "PackagingError",
    "SerializationError",
    "UnsupportedFormatError",
]
