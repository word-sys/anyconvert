"""Comprehensive exception hierarchy for the anyconvert document conversion engine.

This module defines all custom exceptions raised throughout the PDF parsing,
cryptographic decryption, font analysis, layout reconstruction, packaging,
and target emission pipelines.
"""

from __future__ import annotations

from typing import Optional


class AnyConvertError(Exception):
    """Base exception class for all errors originating within anyconvert."""

    def __init__(self, message: str = "", *args: object) -> None:
        super().__init__(message, *args)
        self.message: str = message

    def __str__(self) -> str:
        return self.message or self.__class__.__name__


# ==============================================================================
# Top-Level Conversion & Configuration Errors
# ==============================================================================


class ConversionError(AnyConvertError):
    """Raised when an end-to-end conversion process fails to complete."""


class UnsupportedFormatError(AnyConvertError):
    """Raised when an unsupported input or output format is requested.

    Attributes:
        format_name: The format string or identifier that was rejected.
    """

    def __init__(self, message: str, format_name: Optional[str] = None) -> None:
        super().__init__(message)
        self.format_name: Optional[str] = format_name


# ==============================================================================
# PDF Parsing & Interpretation Errors
# ==============================================================================


class PDFError(AnyConvertError):
    """Base exception for all PDF-specific parsing, decoding, and processing errors."""


class PDFSyntaxError(PDFError):
    """Raised when the PDF lexical scanner or parser encounters invalid syntax.

    Attributes:
        offset: The approximate byte offset where the syntax error occurred.
    """

    def __init__(self, message: str, offset: Optional[int] = None) -> None:
        super().__init__(message)
        self.offset: Optional[int] = offset

    def __str__(self) -> str:
        if self.offset is not None:
            return f"{self.message} (at byte offset {self.offset})"
        return self.message


class PDFMalformedStreamError(PDFSyntaxError):
    """Raised when a stream object boundary or dictionary length is malformed."""


class PDFXRefError(PDFError):
    """Raised when cross-reference (xref) table or stream resolution fails."""


class PDFTrailerNotFoundError(PDFXRefError):
    """Raised when the PDF file trailer or startxref token cannot be located."""


class PDFObjectStreamError(PDFXRefError):
    """Raised when unpacking a compressed object stream (/Type /ObjStm) fails."""


# ==============================================================================
# PDF Cryptography & Security Errors
# ==============================================================================


class PDFSecurityError(PDFError):
    """Base exception for PDF encryption, authentication, and security handler errors."""


class PDFPasswordRequiredError(PDFSecurityError):
    """Raised when attempting to access an encrypted document without a password."""


class PDFInvalidPasswordError(PDFSecurityError):
    """Raised when the supplied user or owner password fails authentication."""


class PDFUnsupportedSecurityHandlerError(PDFSecurityError):
    """Raised when the document uses an unsupported encryption handler or revision."""


class PDFCryptoError(PDFSecurityError):
    """Raised when a cryptographic operation (RC4, AES, padding) fails."""


# ==============================================================================
# PDF Stream Filter Errors
# ==============================================================================


class PDFFilterError(PDFError):
    """Base exception for stream decompression filter failures."""


class PDFUnsupportedFilterError(PDFFilterError):
    """Raised when an unknown or unsupported stream filter is encountered."""

    def __init__(self, filter_name: str, message: Optional[str] = None) -> None:
        msg = message or f"Unsupported stream filter: {filter_name}"
        super().__init__(msg)
        self.filter_name: str = filter_name


class PDFCorruptStreamError(PDFFilterError):
    """Raised when decompressed stream data fails validation or predictor decoding."""


# ==============================================================================
# PDF Font & Typography Errors
# ==============================================================================


class PDFFontError(PDFError):
    """Base exception for font metric, CMap, and glyph decoding errors."""


class PDFCMapParseError(PDFFontError):
    """Raised when a /ToUnicode CMap or encoding stream is malformed."""


class PDFEncodingError(PDFFontError):
    """Raised when glyph name or character code mapping fails."""


class PDFUnsupportedFontFormatError(PDFFontError):
    """Raised when a font program format is unrecognized or cannot be parsed."""


# ==============================================================================
# PDF Graphics & Content Stream Errors
# ==============================================================================


class PDFGraphicsError(PDFError):
    """Base exception for PDF graphics state and content stream evaluation errors."""


class PDFContentStreamError(PDFGraphicsError):
    """Raised when evaluating page content operators encounters invalid state or args."""


class PDFUnsupportedColorSpaceError(PDFGraphicsError):
    """Raised when an unrecognized or unsupported color space family is encountered."""


class PDFImageExtractionError(PDFGraphicsError):
    """Raised when extracting or reconstructing an XObject image fails."""


# ==============================================================================
# Spatial Analysis & Semantic Layout Reconstruction Errors
# ==============================================================================


class LayoutError(AnyConvertError):
    """Base exception for spatial indexing and layout analysis errors."""


class SpatialIndexError(LayoutError):
    """Raised when 2D spatial queries or bounding box math encounters invalid bounds."""


class TableReconstructionError(LayoutError):
    """Raised when vector stroke or gutter cell matrix reconstruction fails."""


class ReadingOrderError(LayoutError):
    """Raised when topological ordering of layout blocks encounters a cycle or fault."""


# ==============================================================================
# Universal Document Intermediate Representation (DIR) Errors
# ==============================================================================


class IRError(AnyConvertError):
    """Base exception for Intermediate Representation construction and validation errors."""


class IRValidationError(IRError):
    """Raised when DocumentIR fails structural integrity or schema validation rules."""


class IRBuilderError(IRError):
    """Raised when synthesizing layout clusters into DocumentIR fails."""


# ==============================================================================
# Target Container Packaging Errors
# ==============================================================================


class PackagingError(AnyConvertError):
    """Base exception for container generation errors (ZIP, OPC, ODF)."""


class OPCPackagingError(PackagingError):
    """Raised when generating Open Packaging Conventions (DOCX/PPTX) structures fails."""


class ODFPackagingError(PackagingError):
    """Raised when generating OASIS OpenDocument (ODT/ODP) structures fails."""


# ==============================================================================
# Target Emitter Errors
# ==============================================================================


class EmitterError(AnyConvertError):
    """Base exception for serialization and emitter errors."""


class DOCXEmitterError(EmitterError):
    """Raised when emitting WordprocessingML documents fails."""


class PPTXEmitterError(EmitterError):
    """Raised when emitting PresentationML documents fails."""


class ODTEmitterError(EmitterError):
    """Raised when emitting OpenDocument Text documents fails."""


class ODPEmitterError(EmitterError):
    """Raised when emitting OpenDocument Presentation documents fails."""


class TXTEmitterError(EmitterError):
    """Raised when emitting Plaintext files fails."""


__all__ = [
    "AnyConvertError",
    "ConversionError",
    "UnsupportedFormatError",
    "PDFError",
    "PDFSyntaxError",
    "PDFMalformedStreamError",
    "PDFXRefError",
    "PDFTrailerNotFoundError",
    "PDFObjectStreamError",
    "PDFSecurityError",
    "PDFPasswordRequiredError",
    "PDFInvalidPasswordError",
    "PDFUnsupportedSecurityHandlerError",
    "PDFCryptoError",
    "PDFFilterError",
    "PDFUnsupportedFilterError",
    "PDFCorruptStreamError",
    "PDFFontError",
    "PDFCMapParseError",
    "PDFEncodingError",
    "PDFUnsupportedFontFormatError",
    "PDFGraphicsError",
    "PDFContentStreamError",
    "PDFUnsupportedColorSpaceError",
    "PDFImageExtractionError",
    "LayoutError",
    "SpatialIndexError",
    "TableReconstructionError",
    "ReadingOrderError",
    "IRError",
    "IRValidationError",
    "IRBuilderError",
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
