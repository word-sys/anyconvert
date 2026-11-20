"""High-level conversion API for anyconvert.

Provides zero-dependency unified conversion functions:
- convert(): Convert from file path, Path, or bytes to target format file or bytes.
- convert_bytes(): Convert from in-memory PDF bytes to target format bytes.
- pdf_to_document_ir(): Parse a PDF into a validated DocumentIR hierarchy.
"""

from __future__ import annotations

import os
import pathlib
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from anyconvert.common.reader import ByteReader
from anyconvert.emitters.base import BaseEmitter, ConversionMode
from anyconvert.emitters.docx import DocxEmitter
from anyconvert.emitters.epub import EpubEmitter
from anyconvert.emitters.html import HTMLEmitter
from anyconvert.emitters.md import MarkdownEmitter
from anyconvert.emitters.odp import OdpEmitter
from anyconvert.emitters.odt import OdtEmitter
from anyconvert.emitters.pptx import PptxEmitter
from anyconvert.emitters.rtf import RtfEmitter
from anyconvert.emitters.svg import SvgEmitter
from anyconvert.emitters.txt import TxtEmitter
from anyconvert.exceptions import (
    AnyConvertError,
    PDFSyntaxError,
    UnsupportedFormatError,
)
from anyconvert.ir.builder import DocumentIRBuilder
from anyconvert.ir.model import DocumentIR, DocumentPage
from anyconvert.layout.cluster import cluster_characters_to_words, cluster_words_to_lines
from anyconvert.layout.flow import detect_repeating_headers_footers
from anyconvert.pdf.content.interpreter import ContentInterpreter, InterpreterOutput
from anyconvert.pdf.document import PDFDocument
from anyconvert.pdf.parser import PDFArray, PDFDict, PDFIndirectRef

SUPPORTED_FORMATS: Set[str] = {
    "docx",
    "pptx",
    "odt",
    "odp",
    "txt",
    "svg",
    "html",
    "md",
    "epub",
    "rtf",
}


def _resolve_conversion_mode(mode: Union[ConversionMode, str]) -> ConversionMode:
    """Normalize and validate ConversionMode from string or enum."""
    if isinstance(mode, ConversionMode):
        return mode
    if isinstance(mode, str):
        normalized = mode.lower().strip()
        if normalized == "flow":
            return ConversionMode.FLOW
        elif normalized == "canvas":
            return ConversionMode.CANVAS
        raise ValueError(
            f"Invalid conversion mode: '{mode}'. Must be 'flow' or 'canvas'."
        )
    raise TypeError(f"Invalid mode type: {type(mode).__name__}. Must be ConversionMode or str.")


def _resolve_image_extraction(
    extract_images: Optional[Union[bool, str, pathlib.Path]],
    output_path: Optional[Union[str, pathlib.Path]],
) -> Tuple[Optional[pathlib.Path], Optional[str]]:
    """Resolve target directory and Markdown link prefix for image extraction."""
    if extract_images is None or extract_images is False:
        return None, None

    if extract_images is True or (isinstance(extract_images, str) and not extract_images.strip()):
        if output_path is not None:
            img_dir = pathlib.Path(output_path).parent / "images"
        else:
            img_dir = pathlib.Path("images")
        return img_dir, "images"

    if isinstance(extract_images, (str, pathlib.Path)):
        img_dir = pathlib.Path(extract_images)
        if output_path is not None:
            base_dir = pathlib.Path(output_path).resolve().parent
            target_dir = img_dir.resolve()
            try:
                rel = os.path.relpath(target_dir, start=base_dir)
                link_prefix = pathlib.Path(rel).as_posix()
            except ValueError:
                link_prefix = img_dir.as_posix()
            return img_dir, link_prefix

        if not img_dir.is_absolute():
            return img_dir, img_dir.as_posix()
        try:
            rel = os.path.relpath(img_dir, start=pathlib.Path.cwd())
            link_prefix = pathlib.Path(rel).as_posix()
        except ValueError:
            link_prefix = img_dir.as_posix()
        return img_dir, link_prefix

    raise TypeError(
        f"Invalid extract_images type: {type(extract_images).__name__}. Must be bool, str, Path, or None."
    )


def _get_emitter(
    output_format: str,
    image_dir: Optional[Union[str, pathlib.Path]] = None,
    image_link_prefix: Optional[str] = None,
) -> BaseEmitter:
    """Instantiate and return the appropriate emitter for the requested format."""
    fmt = output_format.lower().strip().lstrip(".")
    if fmt == "docx":
        return DocxEmitter()
    elif fmt == "pptx":
        return PptxEmitter()
    elif fmt == "odt":
        return OdtEmitter()
    elif fmt == "odp":
        return OdpEmitter()
    elif fmt == "txt":
        return TxtEmitter()
    elif fmt == "svg":
        return SvgEmitter()
    elif fmt == "html":
        return HTMLEmitter()
    elif fmt in ("md", "markdown"):
        return MarkdownEmitter(
            image_dir=image_dir,
            image_link_prefix=image_link_prefix,
        )
    elif fmt == "epub":
        return EpubEmitter()
    elif fmt == "rtf":
        return RtfEmitter()
    raise UnsupportedFormatError(
        format_name=output_format,
        supported_formats=sorted(list(SUPPORTED_FORMATS)),
    )


def pdf_to_document_ir(
    source: Union[str, pathlib.Path, bytes, bytearray, memoryview, ByteReader, DocumentIR],
    password: str = "",
    mode: Union[ConversionMode, str] = ConversionMode.FLOW,
) -> DocumentIR:
    """Parse a PDF document source into a fully validated DocumentIR hierarchy.

    Args:
        source: File path, Path, raw bytes, ByteReader, or existing DocumentIR.
        password: Optional decryption password for encrypted PDFs.
        mode: Layout conversion mode (ConversionMode.FLOW or ConversionMode.CANVAS).

    Returns:
        DocumentIR: Validated intermediate representation of the document.

    Raises:
        PDFSyntaxError: If the PDF structure is corrupted or contains no pages.
        PDFPasswordRequiredError: If the document is password-protected and an incorrect or empty password was given.
    """
    if isinstance(source, DocumentIR):
        return source

    conv_mode = _resolve_conversion_mode(mode)
    reader: ByteReader
    if isinstance(source, (str, pathlib.Path)):
        raw_bytes = pathlib.Path(source).read_bytes()
        reader = ByteReader(raw_bytes)
    elif isinstance(source, ByteReader):
        reader = source
    elif isinstance(source, (bytes, bytearray, memoryview)):
        reader = ByteReader(source)
    else:
        raise TypeError(f"Unsupported source type: {type(source).__name__}")

    doc = PDFDocument(reader, auth_key=password)

    if doc.page_count == 0:
        raise PDFSyntaxError("PDF contains no valid pages")

    ir_builder = DocumentIRBuilder(resolver=doc.resolver)
    pages: List[DocumentPage] = []

    interpreted_pages: List[Tuple[InterpreterOutput, float, float]] = []
    pages_lines: List[List[Any]] = []

    for page_idx in range(doc.page_count):
        page_dict = doc.get_page(page_idx)
        x0, y0, x1, y1 = doc.get_page_box(page_dict)
        page_w = max(1.0, abs(x1 - x0))
        page_h = max(1.0, abs(y1 - y0))

        # Resolve resources dictionary
        raw_res = page_dict.get("Resources")
        if isinstance(raw_res, PDFIndirectRef):
            raw_res = doc.resolver.dereference(raw_res)
        page_res = raw_res if isinstance(raw_res, PDFDict) else PDFDict()

        # Decompress / decrypt content streams
        content_bytes = doc.get_page_content_bytes(page_dict)

        # Interpret content streams
        interpreter = ContentInterpreter(resources=page_res, resolver=doc.resolver)
        output = interpreter.interpret(content_bytes)
        interpreted_pages.append((output, page_w, page_h))

        words = cluster_characters_to_words(output.text_elements, page_height=page_h)
        lines = cluster_words_to_lines(words)
        pages_lines.append(lines)

    known_headers: Set[str] = set()
    known_footers: Set[str] = set()
    if len(pages_lines) > 1:
        known_headers, known_footers = detect_repeating_headers_footers(pages_lines)

    for page_idx, (output, page_w, page_h) in enumerate(interpreted_pages):
        built_page = ir_builder.build_page(
            output=output,
            page_width=page_w,
            page_height=page_h,
            page_number=page_idx + 1,
            known_headers=known_headers,
            known_footers=known_footers,
            mode=conv_mode,
        )
        pages.append(built_page)

    metadata = doc.get_metadata()
    return ir_builder.build_document(pages, metadata=metadata)


def convert(
    input_path: Union[str, pathlib.Path, bytes, bytearray, memoryview, ByteReader, DocumentIR],
    output_format: str = "docx",
    output_path: Optional[Union[str, pathlib.Path]] = None,
    mode: Union[ConversionMode, str] = ConversionMode.FLOW,
    password: str = "",
    extract_images: Optional[Union[bool, str, pathlib.Path]] = None,
) -> bytes:
    """Convert a PDF document into a target document format (DOCX, PPTX, ODT, ODP, TXT, SVG, HTML, MD).

    Args:
        input_path: File path, Path object, or raw PDF bytes.
        output_format: Target format ('docx', 'pptx', 'odt', 'odp', 'txt', 'svg', 'html', 'md').
        output_path: Optional file path to write output. If None, output is only returned as bytes.
        mode: Layout mode, either ConversionMode.FLOW / 'flow' or ConversionMode.CANVAS / 'canvas'.
        password: Optional password if the PDF document is encrypted.
        extract_images: When truthy or a directory path, write extracted images to disk and link them (Markdown).

    Returns:
        bytes: Converted document binary payload.

    Raises:
        UnsupportedFormatError: If the requested output format is not supported.
        ValueError: If mode is not 'flow' or 'canvas'.
        AnyConvertError: If parsing, layout, or serialization fails.
    """
    conv_mode = _resolve_conversion_mode(mode)
    img_dir, img_prefix = _resolve_image_extraction(extract_images, output_path)
    emitter = _get_emitter(
        output_format,
        image_dir=img_dir,
        image_link_prefix=img_prefix,
    )

    doc_ir = pdf_to_document_ir(input_path, password=password, mode=conv_mode)
    result_bytes = emitter.emit(doc_ir, mode=conv_mode)

    if output_path is not None:
        target_path = pathlib.Path(output_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(result_bytes)

    return result_bytes


def convert_bytes(
    pdf_bytes: Union[bytes, bytearray, memoryview],
    output_format: str = "docx",
    mode: Union[ConversionMode, str] = ConversionMode.FLOW,
    password: str = "",
    extract_images: Optional[Union[bool, str, pathlib.Path]] = None,
) -> bytes:
    """Convert raw in-memory PDF bytes into target format bytes.

    Args:
        pdf_bytes: Raw bytes of the PDF file.
        output_format: Target format ('docx', 'pptx', 'odt', 'odp', 'txt', 'svg', 'html', 'md').
        mode: Layout mode ('flow' or 'canvas').
        password: Optional password if the PDF document is encrypted.
        extract_images: Optional image extraction directory path or True for default 'images/'.

    Returns:
        bytes: Converted document binary payload.
    """
    return convert(
        input_path=pdf_bytes,
        output_format=output_format,
        output_path=None,
        mode=mode,
        password=password,
        extract_images=extract_images,
    )


__all__ = [
    "SUPPORTED_FORMATS",
    "ConversionMode",
    "convert",
    "convert_bytes",
    "pdf_to_document_ir",
]
