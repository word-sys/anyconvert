"""Semantic Flow Mode Plaintext / Markdown emitter."""

from __future__ import annotations

from typing import List

from anyconvert.emitters.base import BaseEmitter, ConversionMode
from anyconvert.exceptions import SerializationError
from anyconvert.ir.model import (
    Alignment,
    BlockNode,
    DocumentIR,
    DocumentPage,
    HeadingLevel,
    ImageBlock,
    Paragraph,
    Table,
    TextRun,
    VectorBlock,
)


class TxtFlowEmitter(BaseEmitter):
    """Semantic Flow Plaintext / Markdown emitter generating clean reflowable text."""

    def emit(
        self,
        doc_ir: DocumentIR,
        mode: ConversionMode = ConversionMode.FLOW,
    ) -> bytes:
        """Serialize DocumentIR into a clean UTF-8 Markdown text document.

        Args:
            doc_ir: Validated DocumentIR structure.
            mode: Layout mode (defaults to FLOW).

        Returns:
            UTF-8 encoded bytes of the formatted Markdown document.
        """
        if not doc_ir.pages:
            raise SerializationError("Cannot emit plaintext from empty DocumentIR")

        page_strings: List[str] = []
        image_counter = [1]

        for page_idx, page in enumerate(doc_ir.pages):
            block_strings: List[str] = []

            # Page header if present
            if page.header and page.header.content:
                hdr_lines = [self._render_paragraph(p) for p in page.header.content]
                block_strings.append("> " + " ".join(hdr_lines))

            for block in page.blocks:
                b_str = self._render_block(block, image_counter)
                if b_str:
                    block_strings.append(b_str)

            # Page footer if present
            if page.footer and page.footer.content:
                ftr_lines = [self._render_paragraph(p) for p in page.footer.content]
                block_strings.append("> " + " ".join(ftr_lines))

            page_content = "\n\n".join(block_strings)
            page_strings.append(page_content)

        # Multi-page separator
        full_text = "\n\n---\n\n".join(page_strings)
        return full_text.strip().encode("utf-8")

    def _render_block(self, block: BlockNode, image_counter: List[int]) -> str:
        """Render a single BlockNode to Markdown text."""
        if isinstance(block, Paragraph):
            return self._render_paragraph(block)
        elif isinstance(block, Table):
            return self._render_table(block)
        elif isinstance(block, ImageBlock):
            return self._render_image(block, image_counter)
        elif isinstance(block, VectorBlock):
            return ""
        return ""

    def _render_paragraph(self, p: Paragraph) -> str:
        """Render a Paragraph with heading or list markers and run styling."""
        runs_text: List[str] = []
        for r in p.runs:
            txt = r.text
            if not txt:
                continue

            # Markdown emphasis
            if r.is_bold and r.is_italic:
                txt = f"***{txt}***"
            elif r.is_bold:
                txt = f"**{txt}**"
            elif r.is_italic:
                txt = f"*{txt}*"

            if r.is_strikethrough:
                txt = f"~~{txt}~~"

            runs_text.append(txt)

        para_text = "".join(runs_text).strip()
        if not para_text:
            return ""

        if p.heading_level:
            level_num = p.heading_level.value
            return f"{'#' * level_num} {para_text}"

        if p.list_marker:
            indent = "  " * max(0, p.list_level)
            # Normalize bullet to markdown hyphen if not ordered
            marker = p.list_marker.strip()
            if not (marker.endswith(".") or marker.endswith(")")):
                marker = "-"
            return f"{indent}{marker} {para_text}"

        return para_text

    def _render_table(self, table: Table) -> str:
        """Render a Table into a structured Markdown / ASCII table."""
        if not table.rows:
            return ""

        # Build 2D string matrix of cell contents
        matrix: List[List[str]] = []
        num_cols = len(table.col_widths) if table.col_widths else 0

        for row in table.rows:
            row_cells: List[str] = []
            for cell in row.cells:
                cell_parts: List[str] = []
                for b in cell.content:
                    if isinstance(b, Paragraph):
                        cell_parts.append(b.text.strip())
                cell_txt = " ".join(cell_parts).replace("|", "\\|")
                row_cells.append(cell_txt)
                # Expand col_span in text matrix
                if cell.col_span > 1:
                    row_cells.extend([""] * (cell.col_span - 1))

            num_cols = max(num_cols, len(row_cells))
            matrix.append(row_cells)

        if num_cols == 0:
            return ""

        # Pad all rows to num_cols
        for row_cells in matrix:
            while len(row_cells) < num_cols:
                row_cells.append("")

        # Calculate max width for each column
        col_widths = [3] * num_cols
        for row_cells in matrix:
            for c_idx, cell_txt in enumerate(row_cells):
                col_widths[c_idx] = max(col_widths[c_idx], len(cell_txt))

        # Format rows
        lines: List[str] = []
        header_row = matrix[0]
        hdr_line = "| " + " | ".join(cell.ljust(col_widths[i]) for i, cell in enumerate(header_row)) + " |"
        lines.append(hdr_line)

        # Delimiter row
        delims = ["-" * col_widths[i] for i in range(num_cols)]
        if table.alignment == Alignment.CENTER:
            delims = [f":{'-' * (col_widths[i] - 2)}:" for i in range(num_cols)]
        elif table.alignment == Alignment.RIGHT:
            delims = [f"{'-' * (col_widths[i] - 1)}:" for i in range(num_cols)]
        else:
            delims = [f":{'-' * (col_widths[i] - 1)}" for i in range(num_cols)]

        delim_line = "| " + " | ".join(delims) + " |"
        lines.append(delim_line)

        # Data rows
        for row_cells in matrix[1:]:
            r_line = "| " + " | ".join(cell.ljust(col_widths[i]) for i, cell in enumerate(row_cells)) + " |"
            lines.append(r_line)

        return "\n".join(lines)

    def _render_image(self, img: ImageBlock, image_counter: List[int]) -> str:
        """Render an ImageBlock as a Markdown image token."""
        idx = image_counter[0]
        image_counter[0] += 1
        alt = img.alt_text or f"Image_{idx}"
        return f"![{alt}](image_{idx}.png)"


__all__ = ["TxtFlowEmitter"]
