"""
Exception hierarchy for anyconvert.
"""

from typing import Optional


class AnyConvertError(Exception):
    """Base exception for all anyconvert errors."""
    pass


class UnsupportedFormatError(AnyConvertError):
    """Raised when a file format or conversion pair is not supported."""

    def __init__(self, source_format: str, target_format: Optional[str] = None, message: Optional[str] = None):
        self.source_format = source_format.lower()
        self.target_format = target_format.lower() if target_format else None

        if message:
            super().__init__(message)
        elif self.target_format:
            super().__init__(
                f"Conversion from '{self.source_format}' to '{self.target_format}' is currently not supported."
            )
        else:
            super().__init__(f"Format '{self.source_format}' is not supported.")


class MissingDependencyError(UnsupportedFormatError):
    """Raised when an optional dependency required for conversion is missing."""

    def __init__(self, package_name: str, target_format: str, extra_name: Optional[str] = None):
        self.package_name = package_name
        self.target_format = target_format
        self.extra_name = extra_name or target_format
        msg = (
            f"Package '{package_name}' is required for {target_format.upper()} conversion. "
            f"Install it with: pip install 'anyconvert[{self.extra_name}]' or pip install {package_name}"
        )
        super().__init__(source_format="any", target_format=target_format, message=msg)


class ConversionError(AnyConvertError):
    """Raised when an error occurs during the conversion process."""

    def __init__(self, message: str, original_error: Optional[Exception] = None):
        self.original_error = original_error
        full_msg = f"{message} (Caused by: {original_error})" if original_error else message
        super().__init__(full_msg)


class CorruptFileError(ConversionError):
    """Raised when the input file is corrupted, encrypted, or cannot be read."""
    pass


class CancelledError(AnyConvertError):
    """Raised when conversion is cancelled by a CancellationToken."""

    def __init__(self, message: str = "Conversion was cancelled by user or process."):
        super().__init__(message)


class FormatDetectionError(AnyConvertError):
    """Raised when the format of a file or byte stream cannot be determined."""
    pass


class ValidationError(AnyConvertError):
    """Raised when conversion options or parameters are invalid."""
    pass
