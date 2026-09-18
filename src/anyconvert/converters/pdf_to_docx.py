"""
Native PDF to Microsoft Word (.docx) converter.
Generates compliant OpenXML packages without third-party converters.
"""

from pathlib import Path
from typing import Optional

from anyconvert.analysis.layout import extract_document_layout
from anyconvert.converters.base import BaseConverter
from anyconvert.core.models import ImageBlock, TableBlock
from anyconvert.core.options import ConversionOptions, ConversionResult
from anyconvert.core.registry import register_converter
from anyconvert.synthesizers.docx import DocxSynthesizer


@register_converter
class PdfToDocxConverter(BaseConverter):
    """Converts PDF documents to native Microsoft Word (.docx) files."""

    source_format = "pdf"
    target_format = "docx"

    def convert_file(
        self,
        source_path: Path,
        target_path: Path,
        options: Optional[ConversionOptions] = None,
    ) -> ConversionResult:
        opts = options or ConversionOptions()
        ir_doc = extract_document_layout(source_path, opts)

        synthesizer = DocxSynthesizer(ir_doc, opts)
        synthesizer.build_file(target_path)

        tables_count = sum(
            1 for page in ir_doc.pages for block in page.blocks if isinstance(block, TableBlock)
        )
        images_count = sum(
            1 for page in ir_doc.pages for block in page.blocks if isinstance(block, ImageBlock)
        )

        return ConversionResult(
            success=True,
            output_path=str(target_path),
            page_count=ir_doc.page_count,
            tables_count=tables_count,
            images_count=images_count,
        )

    def convert_bytes(
        self,
        data: bytes,
        options: Optional[ConversionOptions] = None,
    ) -> bytes:
        opts = options or ConversionOptions()
        ir_doc = extract_document_layout(data, opts)

        synthesizer = DocxSynthesizer(ir_doc, opts)
        return synthesizer.build_bytes()
