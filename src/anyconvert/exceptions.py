"""anyconvert exception hierarchy.

This module defines the structured hierarchy of exceptions raised across the
anyconvert PDF parsing, layout reconstruction, intermediate representation,
and document emission pipelines.
"""

from typing import Any, Dict, Optional


class AnyConvertError(Exception):
    """Base exception class for all errors raised by anyconvert."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        """Initialize the base AnyConvert error.

        Args:
            message: Human-readable explanation of the error.
            details: Optional dictionary containing machine-readable contextual details.
        """
        super().__init__(message)
        self.message: str = message
        self.details: Dict[str, Any] = details if details is not None else {}

    def __str__(self) -> str:
        """Return the string representation of the error."""
        if self.details:
            details_str = ", ".join(f"{k}={v!r}" for k, v in self.details.items())
            return f"{self.message} ({details_str})"
        return self.message

    def __repr__(self) -> str:
        """Return a debug representation of the error."""
        return f"{self.__class__.__name__}(message={self.message!r}, details={self.details!r})"


# =====================================================================
# PDF Parsing & Low-Level Processing Exceptions
# =====================================================================


class PDFError(AnyConvertError):
    """Base exception for all PDF parsing, indexing, and decoding errors."""


class PDFSyntaxError(PDFError):
    """Raised when the raw byte stream violates PDF grammar or lexical rules.

    Attributes:
        offset: Byte offset in the file where the syntax error occurred.
    """

    def __init__(
        self,
        message: str,
        offset: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, details=details)
        self.offset: Optional[int] = offset
        if offset is not None:
            self.details["offset"] = offset


class PDFObjectError(PDFError):
    """Raised when an indirect object or cross-reference cannot be resolved."""

    def __init__(
        self,
        message: str,
        obj_id: Optional[int] = None,
        generation: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, details=details)
        self.obj_id: Optional[int] = obj_id
        self.generation: Optional[int] = generation
        if obj_id is not None:
            self.details["obj_id"] = obj_id
        if generation is not None:
            self.details["generation"] = generation


class PDFSecurityError(PDFError):
    """Base exception for PDF cryptographic or permissions errors."""


class PDFPasswordRequiredError(PDFSecurityError):
    """Raised when a document is encrypted and a valid password was not provided."""


class PDFUnsupportedFilterError(PDFError):
    """Raised when a stream filter is unknown or not supported."""

    def __init__(
        self,
        filter_name: str,
        message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        msg = message or f"Unsupported stream filter: {filter_name}"
        super().__init__(msg, details=details)
        self.filter_name: str = filter_name
        self.details["filter_name"] = filter_name


class PDFFontError(PDFError):
    """Raised when font metrics, cmap, or glyph table extraction fails."""

    def __init__(
        self,
        message: str,
        font_name: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, details=details)
        self.font_name: Optional[str] = font_name
        if font_name is not None:
            self.details["font_name"] = font_name


class PDFStreamError(PDFError):
    """Raised when stream lengths or data streams are malformed or corrupted."""


# =====================================================================
# Layout Reconstruction Exceptions
# =====================================================================


class LayoutError(AnyConvertError):
    """Base exception for spatial layout analysis and reconstruction errors."""


class SpatialIndexError(LayoutError):
    """Raised when spatial indexing or bounding box geometric operations fail."""


class XYCutError(LayoutError):
    """Raised when recursive XY-cut projection analysis fails."""


class TableReconstructionError(LayoutError):
    """Raised when table grid cell topology or span reconstruction fails."""


# =====================================================================
# Intermediate Representation (IR) Exceptions
# =====================================================================


class IRError(AnyConvertError):
    """Base exception for Document Intermediate Representation (DIR) errors."""


class IRValidationError(IRError):
    """Raised when DocumentIR fails structural integrity or invariant validation."""


class IRBuilderError(IRError):
    """Raised when building DocumentIR from extracted layout structures fails."""


# =====================================================================
# Emitter & Packaging Exceptions
# =====================================================================


class EmitterError(AnyConvertError):
    """Base exception for document serialization and file emission errors."""


class PackagingError(EmitterError):
    """Raised when OPC or ODF container generation fails."""


class SerializationError(EmitterError):
    """Raised when generating format-specific document content fails."""


class UnsupportedFormatError(EmitterError):
    """Raised when an unsupported target format is requested."""

    def __init__(
        self,
        format_name: str,
        supported_formats: Optional[list[str]] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        msg = f"Unsupported target format: {format_name!r}."
        if supported_formats:
            msg += f" Supported formats: {', '.join(supported_formats)}"
        super().__init__(msg, details=details)
        self.format_name: str = format_name
        self.supported_formats: list[str] = supported_formats or []
        self.details["format_name"] = format_name
        if supported_formats:
            self.details["supported_formats"] = supported_formats
