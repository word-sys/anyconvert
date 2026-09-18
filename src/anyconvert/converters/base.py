"""
Base converter abstract class for all anyconvert converters.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Union

from anyconvert.core.options import ConversionOptions, ConversionResult


class BaseConverter(ABC):
    """Abstract base class for all file format converters."""

    # Declared formats (lowercase, e.g. "pdf", "docx")
    source_format: str = ""
    target_format: str = ""

    def __init__(self) -> None:
        self.validate_dependencies()

    def validate_dependencies(self) -> None:
        """
        Check if any third-party dependencies required by this converter are installed.
        Override in subclasses to raise MissingDependencyError if missing.
        """
        pass

    @abstractmethod
    def convert_file(
        self,
        source_path: Path,
        target_path: Path,
        options: Optional[ConversionOptions] = None,
    ) -> ConversionResult:
        """
        Convert a file from source_path to target_path on disk.
        """
        raise NotImplementedError

    @abstractmethod
    def convert_bytes(
        self,
        data: bytes,
        options: Optional[ConversionOptions] = None,
    ) -> bytes:
        """
        Convert raw bytes in memory and return the converted bytes.
        """
        raise NotImplementedError

    @classmethod
    def supports(cls, source_fmt: str, target_fmt: str) -> bool:
        """Check if this converter handles the given format pair."""
        return (
            cls.source_format.lower() == source_fmt.lower()
            and cls.target_format.lower() == target_fmt.lower()
        )
