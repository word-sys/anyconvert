from __future__ import annotations

"""
Converter registry and format resolution for anyconvert.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Set, Tuple, Type, Union

from anyconvert.core.exceptions import FormatDetectionError, UnsupportedFormatError

if TYPE_CHECKING:
    from anyconvert.converters.base import BaseConverter


# Common format aliases
FORMAT_ALIASES: Dict[str, str] = {
    "jpg": "jpeg",
    "word": "docx",
    "doc": "docx",
    "excel": "xlsx",
    "xls": "xlsx",
    "powerpoint": "pptx",
    "ppt": "pptx",
    "text": "txt",
    "markdown": "md",
    "svgz": "svg",
    "tif": "tiff",
}

# Magic bytes signature mapping
MAGIC_SIGNATURES: List[Tuple[bytes, str]] = [
    (b"%PDF-", "pdf"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpeg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
    (b"II*\x00", "tiff"),
    (b"MM\x00*", "tiff"),
    (b"BM", "bmp"),
]


def normalize_format(fmt: str) -> str:
    """Normalize a format string to its canonical lowercase form."""
    cleaned = fmt.lower().strip().lstrip(".")
    return FORMAT_ALIASES.get(cleaned, cleaned)


def detect_format_from_bytes(data: bytes) -> Optional[str]:
    """Detect file format using magic bytes."""
    if not data:
        return None

    for signature, fmt in MAGIC_SIGNATURES:
        if data.startswith(signature):
            return fmt

    # WebP: RIFF....WEBP
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"

    # SVG text check
    prefix = data[:1024].lstrip()
    if prefix.startswith(b"<?xml") or prefix.startswith(b"<svg") or b"<svg" in prefix:
        return "svg"

    # Zip-based OpenXML / OpenDocument signatures
    if data.startswith(b"PK\x03\x04"):
        # Could be docx, pptx, xlsx, odt, odp. Search for content indicators in header
        header_sample = data[:4096]
        if b"word/" in header_sample:
            return "docx"
        elif b"ppt/" in header_sample:
            return "pptx"
        elif b"xl/" in header_sample:
            return "xlsx"
        elif b"mimetypeapplication/vnd.oasis.opendocument.text" in header_sample:
            return "odt"
        elif b"mimetypeapplication/vnd.oasis.opendocument.presentation" in header_sample:
            return "odp"
        elif b"mimetypeapplication/vnd.oasis.opendocument.spreadsheet" in header_sample:
            return "ods"
        return "zip"

    # Check if plain text / markdown
    try:
        sample_text = data[:2048].decode("utf-8")
        if sample_text.startswith("# ") or sample_text.startswith("## ") or "```" in sample_text:
            return "md"
        # Check printable ASCII / UTF-8
        if all(c.isprintable() or c in "\r\n\t" for c in sample_text):
            return "txt"
    except UnicodeDecodeError:
        pass

    return None


def detect_format(source: Union[str, Path, bytes]) -> str:
    """
    Detect the format of a file path or raw bytes.
    Raises FormatDetectionError if format cannot be determined.
    """
    if isinstance(source, bytes):
        fmt = detect_format_from_bytes(source)
        if fmt:
            return fmt
        raise FormatDetectionError("Could not determine format from byte content.")

    path = Path(source)
    # First, try file extension
    ext = path.suffix.lower().lstrip(".")
    if ext:
        return normalize_format(ext)

    # If no extension or file exists, inspect bytes
    if path.exists() and path.is_file():
        try:
            with open(path, "rb") as f:
                header = f.read(4096)
            fmt = detect_format_from_bytes(header)
            if fmt:
                return fmt
        except OSError as e:
            raise FormatDetectionError(f"Error reading file '{path}': {e}") from e

    raise FormatDetectionError(f"Could not determine format of file '{path}'.")


class ConverterRegistry:
    """Central registry holding all format converters."""

    def __init__(self) -> None:
        self._converters: Dict[Tuple[str, str], Type[BaseConverter]] = {}

    def register(self, converter_cls: Type[BaseConverter]) -> None:
        """Register a converter class for its source and target formats."""
        src = normalize_format(converter_cls.source_format)
        tgt = normalize_format(converter_cls.target_format)
        if not src or not tgt:
            raise ValueError(
                f"Converter {converter_cls.__name__} must define source_format and target_format."
            )
        self._converters[(src, tgt)] = converter_cls

    def get_converter(self, source_format: str, target_format: str) -> BaseConverter:
        """
        Retrieve and instantiate the converter registered for (source_format, target_format).
        Raises UnsupportedFormatError if no converter is registered.
        """
        src = normalize_format(source_format)
        tgt = normalize_format(target_format)

        converter_cls = self._converters.get((src, tgt))
        if not converter_cls:
            raise UnsupportedFormatError(source_format=src, target_format=tgt)

        return converter_cls()

    def has_converter(self, source_format: str, target_format: str) -> bool:
        """Check if a direct converter exists for the given pair."""
        src = normalize_format(source_format)
        tgt = normalize_format(target_format)
        return (src, tgt) in self._converters

    def supported_conversions(self) -> Dict[str, List[str]]:
        """Return a mapping of all source formats to their supported target formats."""
        mapping: Dict[str, Set[str]] = {}
        for src, tgt in self._converters.keys():
            if src not in mapping:
                mapping[src] = set()
            mapping[src].add(tgt)
        return {src: sorted(tgts) for src, tgts in sorted(mapping.items())}

    def clear(self) -> None:
        """Clear all registered converters (useful for testing)."""
        self._converters.clear()


# Global default registry
default_registry = ConverterRegistry()


def register_converter(cls: Type[BaseConverter]) -> Type[BaseConverter]:
    """Class decorator to register a converter in the default global registry."""
    default_registry.register(cls)
    return cls
