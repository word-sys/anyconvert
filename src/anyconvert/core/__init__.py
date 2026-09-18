"""
Core package for anyconvert.
"""

from anyconvert.core.exceptions import (
    AnyConvertError,
    CancelledError,
    ConversionError,
    CorruptFileError,
    FormatDetectionError,
    MissingDependencyError,
    UnsupportedFormatError,
    ValidationError,
)
from anyconvert.core.models import (
    Block,
    Color,
    Document,
    Hyperlink,
    ImageBlock,
    Page,
    ParagraphBlock,
    Point,
    Rect,
    TableBlock,
    TableCell,
    TextLine,
    TextRun,
    TOCItem,
    VectorShapeBlock,
)
from anyconvert.core.options import (
    CancellationToken,
    ConversionOptions,
    ConversionResult,
    DocumentInfo,
)
from anyconvert.core.registry import (
    ConverterRegistry,
    default_registry,
    detect_format,
    normalize_format,
    register_converter,
)

__all__ = [
    "AnyConvertError",
    "UnsupportedFormatError",
    "MissingDependencyError",
    "ConversionError",
    "CorruptFileError",
    "CancelledError",
    "FormatDetectionError",
    "ValidationError",
    "ConversionOptions",
    "ConversionResult",
    "CancellationToken",
    "DocumentInfo",
    "ConverterRegistry",
    "default_registry",
    "detect_format",
    "normalize_format",
    "register_converter",
    "Point",
    "Rect",
    "Color",
    "TextRun",
    "TextLine",
    "ParagraphBlock",
    "TableCell",
    "TableBlock",
    "ImageBlock",
    "VectorShapeBlock",
    "Block",
    "Hyperlink",
    "Page",
    "TOCItem",
    "Document",
]
