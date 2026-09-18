"""
Converters for PDF to Plain Text (.txt) and Structured Markdown (.md).
"""

import io
from pathlib import Path
from typing import Optional

import pymupdf

from anyconvert.analysis.layout import extract_document_layout
from anyconvert.converters.base import BaseConverter
from anyconvert.core.models import Document, ParagraphBlock, TableBlock, TextRun
from anyconvert.core.options import ConversionOptions, ConversionResult
from anyconvert.core.registry import register_converter


@register_converter
class PdfToTextConverter(BaseConverter):
    """Converts PDF documents to clean, reading-order plain text."""

    source_format = "pdf"
    target_format = "txt"

    def convert_file(
        self,
        source_path: Path,
        target_path: Path,
        options: Optional[ConversionOptions] = None,
    ) -> ConversionResult:
        opts = options or ConversionOptions()
        ir_doc = extract_document_layout(source_path, opts)

        text_content = self._render_doc_to_text(ir_doc)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(text_content, encoding="utf-8")

        return ConversionResult(
            success=True,
            output_path=str(target_path),
            page_count=ir_doc.page_count,
        )

    def convert_bytes(
        self,
        data: bytes,
        options: Optional[ConversionOptions] = None,
    ) -> bytes:
        opts = options or ConversionOptions()
        ir_doc = extract_document_layout(data, opts)
        text_content = self._render_doc_to_text(ir_doc)
        return text_content.encode("utf-8")

    def _render_doc_to_text(self, doc: Document) -> str:
        lines: list[str] = []
        for i, page in enumerate(doc.pages):
            if i > 0:
                lines.append(f"\n--- Page {page.page_number + 1} ---\n")
            for block in page.blocks:
                if isinstance(block, ParagraphBlock):
                    lines.append(block.text)
                    lines.append("")
                elif isinstance(block, TableBlock):
                    matrix = block.as_matrix()
                    for row in matrix:
                        lines.append("\t".join(c.replace("\n", " ").strip() for c in row))
                    lines.append("")
        return "\n".join(lines).strip() + "\n"


@register_converter
class PdfToMarkdownConverter(BaseConverter):
    """Converts PDF documents to structured, high-fidelity Markdown."""

    source_format = "pdf"
    target_format = "md"

    def convert_file(
        self,
        source_path: Path,
        target_path: Path,
        options: Optional[ConversionOptions] = None,
    ) -> ConversionResult:
        opts = options or ConversionOptions()
        ir_doc = extract_document_layout(source_path, opts)

        md_content = self._render_doc_to_markdown(ir_doc, opts)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(md_content, encoding="utf-8")

        return ConversionResult(
            success=True,
            output_path=str(target_path),
            page_count=ir_doc.page_count,
        )

    def convert_bytes(
        self,
        data: bytes,
        options: Optional[ConversionOptions] = None,
    ) -> bytes:
        opts = options or ConversionOptions()
        ir_doc = extract_document_layout(data, opts)
        md_content = self._render_doc_to_markdown(ir_doc, opts)
        return md_content.encode("utf-8")

    def _format_run(self, run: TextRun) -> str:
        text = run.text
        if not text.strip():
            return text

        l_ws = len(text) - len(text.lstrip())
        r_ws = len(text) - len(text.rstrip())
        leading = text[:l_ws]
        core = text[l_ws : len(text) - r_ws] if r_ws > 0 else text[l_ws:]
        trailing = text[len(text) - r_ws :] if r_ws > 0 else ""

        if not core:
            return text

        if run.is_bold and run.is_italic:
            formatted = f"***{core}***"
        elif run.is_bold:
            formatted = f"**{core}**"
        elif run.is_italic:
            formatted = f"*{core}*"
        else:
            formatted = core

        if run.hyperlink_uri:
            formatted = f"[{formatted}]({run.hyperlink_uri})"

        return f"{leading}{formatted}{trailing}"

    def _render_doc_to_markdown(self, doc: Document, options: ConversionOptions) -> str:
        md_lines: list[str] = []

        for i, page in enumerate(doc.pages):
            if i > 0:
                md_lines.append("\n---\n")

            for block in page.blocks:
                if isinstance(block, ParagraphBlock):
                    formatted_line_parts = []
                    for line in block.lines:
                        line_str = "".join(self._format_run(run) for run in line.runs).strip()
                        if line_str:
                            formatted_line_parts.append(line_str)

                    paragraph_text = " ".join(formatted_line_parts).strip()
                    if not paragraph_text:
                        continue

                    if block.heading_level and block.heading_level in (1, 2, 3, 4, 5, 6):
                        prefix = "#" * block.heading_level
                        clean_heading = paragraph_text.lstrip("#").strip()
                        md_lines.append(f"{prefix} {clean_heading}\n")
                    elif block.is_list_item:
                        bullet = block.list_bullet or "-"
                        content = paragraph_text
                        if content.startswith(bullet):
                            content = content[len(bullet) :].strip()
                        md_lines.append(f"- {content}")
                    else:
                        md_lines.append(f"{paragraph_text}\n")
                elif isinstance(block, TableBlock):
                    matrix = block.as_matrix()
                    if matrix and len(matrix) >= 1:
                        header = matrix[0]
                        md_lines.append("| " + " | ".join(c.replace("\n", " ").strip() for c in header) + " |")
                        md_lines.append("| " + " | ".join("---" for _ in header) + " |")
                        for row in matrix[1:]:
                            md_lines.append("| " + " | ".join(c.replace("\n", " ").strip() for c in row) + " |")
                        md_lines.append("")

        return "\n".join(md_lines).strip() + "\n"
