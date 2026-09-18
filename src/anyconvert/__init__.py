"""
anyconvert - Universal Lossless Document and File Conversion Library
"""

import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import pymupdf

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

__version__ = "0.1.0"
__author__ = "Barın Güzeldemirci (word-sys)"
__license__ = "GPL-3.0-or-later"


def convert(
    source: Union[str, Path],
    target: Union[str, Path],
    from_format: Optional[str] = None,
    to_format: Optional[str] = None,
    options: Optional[ConversionOptions] = None,
) -> ConversionResult:
    """
    Convert a file from source to target.

    Args:
        source: Path to the source file.
        target: Desired output file path.
        from_format: Source format override (e.g. 'pdf'). If None, detected automatically.
        to_format: Target format override (e.g. 'docx'). If None, detected from target extension.
        options: Optional ConversionOptions configuring flow mode, DPI, page ranges, callbacks, etc.

    Returns:
        ConversionResult detailing success, page counts, elapsed time, and fidelity warnings.
    """
    source_path = Path(source)
    target_path = Path(target)
    opts = options or ConversionOptions()

    if opts.cancellation_token:
        opts.cancellation_token.check_cancelled()

    # Detect source format
    src_fmt = normalize_format(from_format) if from_format else detect_format(source_path)

    # Detect target format
    tgt_fmt = normalize_format(to_format) if to_format else detect_format(target_path)

    # Lookup converter
    converter = default_registry.get_converter(src_fmt, tgt_fmt)

    # Ensure output directory exists
    target_path.parent.mkdir(parents=True, exist_ok=True)

    start_time = time.perf_counter()
    result = converter.convert_file(source_path, target_path, options=opts)
    elapsed = time.perf_counter() - start_time

    result.elapsed_seconds = elapsed
    result.source_format = src_fmt
    result.target_format = tgt_fmt
    result.output_path = str(target_path)

    return result


def convert_bytes(
    data: bytes,
    to_format: str,
    from_format: Optional[str] = None,
    options: Optional[ConversionOptions] = None,
) -> bytes:
    """
    Convert raw document bytes completely in memory.

    Args:
        data: Raw input bytes.
        to_format: Desired output format (e.g. 'docx', 'odt', 'png').
        from_format: Input format (e.g. 'pdf'). If None, detected from magic bytes.
        options: Optional ConversionOptions.

    Returns:
        Converted document as bytes.
    """
    opts = options or ConversionOptions()

    if opts.cancellation_token:
        opts.cancellation_token.check_cancelled()

    src_fmt = normalize_format(from_format) if from_format else detect_format(data)
    tgt_fmt = normalize_format(to_format)

    converter = default_registry.get_converter(src_fmt, tgt_fmt)
    return converter.convert_bytes(data, options=opts)


def batch_convert(
    sources: List[Union[str, Path]],
    output_dir: Union[str, Path],
    to_format: str,
    options: Optional[ConversionOptions] = None,
    workers: Optional[int] = None,
) -> List[ConversionResult]:
    """
    Convert multiple files in batch with parallel worker support.

    Args:
        sources: List of file paths to convert.
        output_dir: Directory where converted files will be saved.
        to_format: Target format (e.g. 'docx', 'pptx', 'odt').
        options: ConversionOptions for each conversion.
        workers: Number of parallel workers (defaults to min(len(sources), os.cpu_count() or 4)).

    Returns:
        List of ConversionResult objects.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tgt_fmt = normalize_format(to_format)
    opts = options or ConversionOptions()

    max_workers = workers or min(len(sources), os.cpu_count() or 4)
    if max_workers <= 1 or len(sources) <= 1:
        results: List[ConversionResult] = []
        for src in sources:
            src_path = Path(src)
            tgt_path = out_dir / f"{src_path.stem}.{tgt_fmt}"
            results.append(convert(src_path, tgt_path, to_format=tgt_fmt, options=opts))
        return results

    def _convert_worker(src: Union[str, Path]) -> ConversionResult:
        src_path = Path(src)
        tgt_path = out_dir / f"{src_path.stem}.{tgt_fmt}"
        return convert(src_path, tgt_path, to_format=tgt_fmt, options=opts)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        return list(executor.map(_convert_worker, sources))


def inspect_file(
    source: Union[str, Path, bytes],
    format_hint: Optional[str] = None,
) -> DocumentInfo:
    """
    Inspect a document to extract structure, page counts, and metadata.
    """
    fmt = normalize_format(format_hint) if format_hint else detect_format(source)

    if fmt == "pdf":
        try:
            if isinstance(source, bytes):
                doc = pymupdf.open(stream=source, filetype="pdf")
                file_size = len(source)
            else:
                path = Path(source)
                file_size = path.stat().st_size if path.exists() else 0
                doc = pymupdf.open(str(path))

            meta = doc.metadata or {}
            has_text = any(len(page.get_text("text").strip()) > 0 for page in doc)
            has_images = any(len(page.get_images()) > 0 for page in doc)

            info = DocumentInfo(
                format="pdf",
                page_count=doc.page_count,
                title=meta.get("title"),
                author=meta.get("author"),
                creator=meta.get("creator"),
                subject=meta.get("subject"),
                keywords=meta.get("keywords"),
                is_encrypted=doc.is_encrypted,
                has_text=has_text,
                has_images=has_images,
                file_size_bytes=file_size,
                extra={"format_version": doc.metadata.get("format")},
            )
            doc.close()
            return info
        except Exception as e:
            raise CorruptFileError(f"Failed to inspect PDF: {e}", original_error=e)

    # Generic fallback
    size = len(source) if isinstance(source, bytes) else (Path(source).stat().st_size if Path(source).exists() else 0)
    return DocumentInfo(format=fmt, page_count=0, file_size_bytes=size)


def supported_conversions() -> Dict[str, List[str]]:
    """Return dictionary of all supported conversions."""
    return default_registry.supported_conversions()


__all__ = [
    "convert",
    "convert_bytes",
    "batch_convert",
    "inspect_file",
    "detect_format",
    "supported_conversions",
    "ConversionOptions",
    "ConversionResult",
    "CancellationToken",
    "DocumentInfo",
    "AnyConvertError",
    "UnsupportedFormatError",
    "MissingDependencyError",
    "ConversionError",
    "CorruptFileError",
    "CancelledError",
    "FormatDetectionError",
    "ValidationError",
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
    "ConverterRegistry",
    "default_registry",
    "register_converter",
]
