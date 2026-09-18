"""anyconvert: Enterprise-grade document conversion engine.

Written in 100% pure Python with zero third-party runtime dependencies.
Parses arbitrary PDF documents directly from raw byte streams and converts
them into DOCX, PPTX, ODT, ODP, and TXT with mathematical precision and
deep semantic layout reconstruction.
"""

from __future__ import annotations

from anyconvert.common.color import (
    BLACK,
    BLUE,
    CYAN,
    DARK_GRAY,
    GRAY,
    GREEN,
    LIGHT_GRAY,
    MAGENTA,
    RED,
    TRANSPARENT,
    WHITE,
    YELLOW,
    Color,
)
from anyconvert.common.geometry import BoundingBox, Matrix3x3, Point, Size
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
    PDFUnsupportedFilterError,
    PDFUnsupportedSecurityHandlerError,
    PDFXRefError,
    PPTXEmitterError,
    TableReconstructionError,
    TXTEmitterError,
    UnsupportedFormatError,
)

__version__: str = "0.1.0"
__author__: str = "anyconvert contributors"
__license__: str = "GPL-3.0-or-later"

__all__: list[str] = [
    "__version__",
    "__author__",
    "__license__",
    "Point",
    "Size",
    "BoundingBox",
    "Matrix3x3",
    "Color",
    "BLACK",
    "WHITE",
    "RED",
    "GREEN",
    "BLUE",
    "YELLOW",
    "CYAN",
    "MAGENTA",
    "GRAY",
    "LIGHT_GRAY",
    "DARK_GRAY",
    "TRANSPARENT",
    "AnyConvertError",
    "ConversionError",
    "UnsupportedFormatError",
    "PDFError",
    "PDFSyntaxError",
    "PDFXRefError",
    "PDFSecurityError",
    "PDFPasswordRequiredError",
    "PDFInvalidPasswordError",
    "PDFUnsupportedSecurityHandlerError",
    "PDFCryptoError",
    "PDFFilterError",
    "PDFUnsupportedFilterError",
    "PDFCorruptStreamError",
    "PDFFontError",
    "PDFGraphicsError",
    "LayoutError",
    "TableReconstructionError",
    "IRError",
    "IRValidationError",
    "PackagingError",
    "OPCPackagingError",
    "ODFPackagingError",
    "EmitterError",
    "DOCXEmitterError",
    "PPTXEmitterError",
    "ODTEmitterError",
    "ODPEmitterError",
    "TXTEmitterError",
]

