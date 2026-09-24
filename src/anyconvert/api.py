"""High-level conversion API for anyconvert.

Provides zero-dependency unified conversion functions:
- convert(): Convert from file path, Path, or bytes to target format file or bytes.
- convert_bytes(): Convert from in-memory PDF bytes to target format bytes.
- pdf_to_document_ir(): Parse a PDF into a validated DocumentIR hierarchy.
"""

from __future__ import annotations

import pathlib
from typing import Any, Dict, List, Optional, Sequence, Set, Union

from anyconvert.common.reader import ByteReader
from anyconvert.emitters.base import BaseEmitter, ConversionMode
from anyconvert.emitters.docx import DocxEmitter
from anyconvert.emitters.odp import OdpEmitter
from anyconvert.emitters.odt import OdtEmitter
from anyconvert.emitters.pptx import PptxEmitter
from anyconvert.emitters.txt import TxtEmitter
from anyconvert.exceptions import (
    AnyConvertError,
    PDFSyntaxError,
    UnsupportedFormatError,
)
from anyconvert.ir.builder import DocumentIRBuilder
from anyconvert.ir.model import DocumentIR, DocumentPage
from anyconvert.pdf.content.interpreter import ContentInterpreter
from anyconvert.pdf.document import PDFDocument
from anyconvert.pdf.parser import PDFArray, PDFDict, PDFIndirectRef

SUPPORTED_FORMATS: Set[str] = {"docx", "pptx", "odt", "odp", "txt"}


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


def _get_emitter(output_format: str) -> BaseEmitter:
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
    raise UnsupportedFormatError(
        format_name=output_format,
        supported_formats=sorted(list(SUPPORTED_FORMATS)),
    )


def pdf_to_document_ir(
    source: Union[str, pathlib.Path, bytes, bytearray, memoryview, ByteReader],
    password: str = "",
) -> DocumentIR:
    """Parse a PDF document source into a fully validated DocumentIR hierarchy.

    Args:
        source: File path, Path, raw bytes, or ByteReader.
        password: Optional decryption password for encrypted PDFs.

    Returns:
        DocumentIR: Validated intermediate representation of the document.

    Raises:
        PDFSyntaxError: If the PDF structure is corrupted or contains no pages.
        PDFPasswordRequiredError: If the document is password-protected and an incorrect or empty password was given.
    """
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

    doc = PDFDocument(reader, password=password)

    if doc.page_count == 0:
        raise PDFSyntaxError("PDF contains no valid pages")

    ir_builder = DocumentIRBuilder(resolver=doc.resolver)
    pages: List[DocumentPage] = []

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

        # Build typed DocumentPage
        built_page = ir_builder.build_page(
            output=output,
            page_width=page_w,
            page_height=page_h,
            page_number=page_idx + 1,
        )
        pages.append(built_page)

    metadata = doc.get_metadata()
    return ir_builder.build_document(pages, metadata=metadata)


def convert(
    input_path: Union[str, pathlib.Path, bytes, bytearray, memoryview, ByteReader],
    output_format: str = "docx",
    output_path: Optional[Union[str, pathlib.Path]] = None,
    mode: Union[ConversionMode, str] = ConversionMode.FLOW,
    password: str = "",
) -> bytes:
    """Convert a PDF document into a target document format (DOCX, PPTX, ODT, ODP, TXT).

    Args:
        input_path: File path, Path object, or raw PDF bytes.
        output_format: Target format ('docx', 'pptx', 'odt', 'odp', 'txt'). Defaults to 'docx'.
        output_path: Optional file path to write output. If None, output is only returned as bytes.
        mode: Layout mode, either ConversionMode.FLOW / 'flow' or ConversionMode.CANVAS / 'canvas'.
        password: Optional password if the PDF document is encrypted.

    Returns:
        bytes: Converted document binary payload (ZIP archive for DOCX/PPTX/ODT/ODP, UTF-8 for TXT).

    Raises:
        UnsupportedFormatError: If the requested output format is not supported.
        ValueError: If mode is not 'flow' or 'canvas'.
        AnyConvertError: If parsing, layout, or serialization fails.
    """
    conv_mode = _resolve_conversion_mode(mode)
    emitter = _get_emitter(output_format)

    doc_ir = pdf_to_document_ir(input_path, password=password)
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
) -> bytes:
    """Convert raw in-memory PDF bytes into target format bytes.

    Args:
        pdf_bytes: Raw bytes of the PDF file.
        output_format: Target format ('docx', 'pptx', 'odt', 'odp', 'txt').
        mode: Layout mode ('flow' or 'canvas').
        password: Optional password if the PDF document is encrypted.

    Returns:
        bytes: Converted document binary payload.
    """
    return convert(
        input_path=pdf_bytes,
        output_format=output_format,
        output_path=None,
        mode=mode,
        password=password,
    )


__all__ = [
    "SUPPORTED_FORMATS",
    "ConversionMode",
    "convert",
    "convert_bytes",
    "pdf_to_document_ir",
]
