"""Advanced Markdown and GitHub Flavored Markdown (GFM) document emitter.

Converts DocumentIR hierarchies into standards-compliant Markdown documents supporting:
- Configurable dialects: CommonMark and GitHub Flavored Markdown (GFM).
- Hierarchical ATX headings (# through ######).
- Rich inline styling: bold (**), italic (*), bold-italic (***), strikethrough (~~),
  and monospace code spans (`code`).
- Nested bullet lists, ordered lists, and GFM task checklists (- [ ] / - [x]).
- Formatted tabular data with column alignment markers (:---, :---:, ---:) and pipe escaping.
- Inline images and figure tokens.
- Running marginal headers and footers formatted as blockquotes (>).
- Multi-page document boundaries using standard horizontal rules (---).
"""

from __future__ import annotations

from enum import Enum, auto
import re
from typing import List, Optional, Sequence, Union

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

# Monospace font identifiers for inline code spans
MONOSPACE_FONT_KEYWORDS = (
    "mono",
    "courier",
    "consolas",
    "menlo",
    "monaco",
    "terminal",
    "sourcecodepro",
    "liberationmono",
    "dejavusansmono",
)

# Unordered bullet glyphs commonly extracted from PDFs
UNORDERED_BULLET_CHARS = ("•", "·", "○", "●", "▪", "■", "▫", "–", "—", "*", "-", "+")

# URL pattern for autolink wrapping
URL_RE = re.compile(r"^(https?://|mailto:)[^\s]+$")


class MarkdownDialect(Enum):
    """Supported Markdown dialect specifications."""

    COMMONMARK = auto()
    GFM = auto()


def resolve_dialect(dialect: Union[MarkdownDialect, str]) -> MarkdownDialect:
    """Normalize and validate MarkdownDialect from string or enum."""
    if isinstance(dialect, MarkdownDialect):
        return dialect
    if isinstance(dialect, str):
        normalized = dialect.lower().strip()
        if normalized in ("gfm", "github"):
            return MarkdownDialect.GFM
        elif normalized in ("commonmark", "standard", "cm"):
            return MarkdownDialect.COMMONMARK
        raise ValueError(
            f"Invalid Markdown dialect: '{dialect}'. Must be 'gfm' or 'commonmark'."
        )
    raise TypeError(
        f"Invalid dialect type: {type(dialect).__name__}. Must be MarkdownDialect or str."
    )


class MarkdownEmitter(BaseEmitter):
    """Pure-Python high-fidelity Markdown document emitter."""

    def __init__(
        self,
        dialect: Union[MarkdownDialect, str] = MarkdownDialect.GFM,
        page_separator: str = "\n\n---\n\n",
        render_headers_footers: bool = True,
    ) -> None:
        self.dialect = resolve_dialect(dialect)
        self.page_separator = page_separator
        self.render_headers_footers = render_headers_footers

    def emit(
        self,
        doc_ir: DocumentIR,
        mode: ConversionMode = ConversionMode.FLOW,
    ) -> bytes:
        """Serialize DocumentIR into UTF-8 encoded Markdown bytes.

        Args:
            doc_ir: Validated DocumentIR structure.
            mode: Layout mode (informational; Markdown is inherently flow-based).

        Returns:
            UTF-8 encoded bytes of the Markdown document.

        Raises:
            SerializationError: If doc_ir contains no pages.
        """
        if not doc_ir.pages:
            raise SerializationError("Cannot emit Markdown from empty DocumentIR")

        rendered_text = self.render(doc_ir)
        return rendered_text.encode("utf-8")

    def emit_page(
        self,
        page: DocumentPage,
        page_num: int = 1,
    ) -> bytes:
        """Serialize a single DocumentPage directly into Markdown bytes."""
        text = self.render_page(page, page_num=page_num, image_counter=[1])
        return text.strip().encode("utf-8")

    def render(self, doc_ir: DocumentIR) -> str:
        """Render DocumentIR into a formatted Markdown string.

        Args:
            doc_ir: Validated DocumentIR structure.

        Returns:
            Formatted Markdown document string.
        """
        if not doc_ir.pages:
            raise SerializationError("Cannot emit Markdown from empty DocumentIR")

        page_strings: List[str] = []
        image_counter = [1]

        for page_idx, page in enumerate(doc_ir.pages):
            page_num = page_idx + 1
            page_text = self.render_page(page, page_num=page_num, image_counter=image_counter)
            if page_text:
                page_strings.append(page_text)

        full_text = self.page_separator.join(page_strings)
        return full_text.strip() + "\n"

    def render_page(
        self,
        page: DocumentPage,
        page_num: int = 1,
        image_counter: Optional[List[int]] = None,
    ) -> str:
        """Render a single DocumentPage into Markdown blocks."""
        counter = image_counter if image_counter is not None else [1]
        block_strings: List[str] = []

        # Running marginal header
        if self.render_headers_footers and page.header and page.header.content:
            hdr_lines = [self.render_paragraph(p).strip() for p in page.header.content]
            non_empty_hdr = [h for h in hdr_lines if h]
            if non_empty_hdr:
                block_strings.append("> " + " ".join(non_empty_hdr))

        # Main body content blocks
        for block in page.blocks:
            b_str = self.render_block(block, counter)
            if b_str:
                block_strings.append(b_str)

        # Running marginal footer
        if self.render_headers_footers and page.footer and page.footer.content:
            ftr_lines = [self.render_paragraph(p).strip() for p in page.footer.content]
            non_empty_ftr = [f for f in ftr_lines if f]
            if non_empty_ftr:
                block_strings.append("> " + " ".join(non_empty_ftr))

        return "\n\n".join(block_strings)

    def render_block(self, block: BlockNode, image_counter: List[int]) -> str:
        """Render a single intermediate representation block to Markdown text."""
        if isinstance(block, Paragraph):
            return self.render_paragraph(block)
        elif isinstance(block, Table):
            return self.render_table(block)
        elif isinstance(block, ImageBlock):
            return self.render_image(block, image_counter)
        elif isinstance(block, VectorBlock):
            return ""
        return ""

    def render_paragraph(self, p: Paragraph) -> str:
        """Render a Paragraph node with heading, list markers, and run formatting."""
        runs_text: List[str] = [self.render_run(r) for r in p.runs]
        para_text = "".join(runs_text).strip()

        if not para_text:
            return ""

        # Headings: H1 through H6
        if p.heading_level is not None:
            level_num = p.heading_level.value
            level_num = max(1, min(6, level_num))
            prefix = "#" * level_num
            return f"{prefix} {para_text}"

        # List items: bullet lists, numbered lists, task lists
        if p.list_marker:
            return self._format_list_item(p, para_text)

        return para_text

    def _format_list_item(self, p: Paragraph, para_text: str) -> str:
        """Format paragraph as an unordered, ordered, or GFM task checklist item."""
        indent = "  " * max(0, p.list_level)
        marker = p.list_marker.strip() if p.list_marker else "-"

        # Check for task checklist in GFM mode
        if self.dialect == MarkdownDialect.GFM:
            marker_nospace = marker.replace(" ", "")
            if marker_nospace in ("[]", "[_]") or marker in ("[ ]", "☐"):
                return f"{indent}- [ ] {para_text}"
            elif marker_nospace in ("[x]", "[X]") or marker in ("☑", "☒"):
                return f"{indent}- [x] {para_text}"

        # Check for ordered numbering (e.g. "1.", "1)", "(1)", "a.")
        if marker.endswith(".") or marker.endswith(")") or marker.isdigit():
            clean_num = marker.rstrip(".)").lstrip("(")
            num_suffix = f"{clean_num}." if clean_num.isdigit() else marker
            return f"{indent}{num_suffix} {para_text}"

        # Normalize bullet markers to standard hyphen
        if marker in UNORDERED_BULLET_CHARS or len(marker) == 1:
            marker = "-"

        return f"{indent}{marker} {para_text}"

    def render_run(self, r: TextRun) -> str:
        """Render an individual TextRun with inline formatting."""
        txt = r.text
        if not txt:
            return ""

        # Monospace code detection
        is_code = self._is_monospace(r.font_name)
        if is_code:
            txt = self._format_code_span(txt)

        # Bold & Italic emphasis
        if r.is_bold and r.is_italic:
            txt = f"***{txt}***"
        elif r.is_bold:
            txt = f"**{txt}**"
        elif r.is_italic:
            txt = f"*{txt}*"

        # Strikethrough
        if r.is_strikethrough:
            if self.dialect == MarkdownDialect.GFM:
                txt = f"~~{txt}~~"
            else:
                txt = f"<s>{txt}</s>"

        # Underline (CommonMark & GFM do not have native underline, use HTML tag)
        if r.is_underline:
            txt = f"<u>{txt}</u>"

        # Baseline vertical offset (subscript / superscript)
        if r.baseline_offset > 0.5:
            txt = f"<sup>{txt}</sup>"
        elif r.baseline_offset < -0.5:
            txt = f"<sub>{txt}</sub>"

        # Autolink detection
        stripped = r.text.strip()
        if URL_RE.match(stripped) and not is_code:
            txt = f"<{stripped}>"

        return txt

    def _is_monospace(self, font_name: str) -> bool:
        """Determine whether a font name indicates a monospace code face."""
        if not font_name:
            return False
        fn = font_name.lower().replace("-", "").replace("_", "").replace(" ", "")
        return any(k in fn for k in MONOSPACE_FONT_KEYWORDS)

    def _format_code_span(self, text: str) -> str:
        """Wrap text into a Markdown backtick code span, escaping backticks if needed."""
        if "`" not in text:
            return f"`{text}`"
        # If backticks exist within code text, wrap with double backticks
        return f"`` {text} ``"

    def render_table(self, table: Table) -> str:
        """Render a Table into a GFM/Markdown tabular grid."""
        if not table.rows:
            return ""

        # Build 2D matrix of cleaned cell strings
        matrix: List[List[str]] = []
        num_cols = len(table.col_widths) if table.col_widths else 0

        for row in table.rows:
            row_cells: List[str] = []
            for cell in row.cells:
                cell_parts: List[str] = []
                for b in cell.content:
                    if isinstance(b, Paragraph):
                        cell_parts.append(b.text.strip())
                # Replace newlines with <br> and escape unescaped pipe characters
                raw_cell = " ".join(cell_parts).strip()
                cell_txt = raw_cell.replace("\n", "<br>").replace("|", "\\|")
                row_cells.append(cell_txt)

                # Expand col_span in matrix
                if cell.col_span > 1:
                    row_cells.extend([""] * (cell.col_span - 1))

            num_cols = max(num_cols, len(row_cells))
            matrix.append(row_cells)

        if num_cols == 0:
            return ""

        # Ensure all rows have equal column counts
        for row_cells in matrix:
            while len(row_cells) < num_cols:
                row_cells.append("")

        # Calculate padding widths
        col_widths = [3] * num_cols
        for row_cells in matrix:
            for c_idx, cell_txt in enumerate(row_cells):
                col_widths[c_idx] = max(col_widths[c_idx], len(cell_txt))

        lines: List[str] = []

        # Header row
        header_row = matrix[0]
        hdr_line = (
            "| "
            + " | ".join(cell.ljust(col_widths[i]) for i, cell in enumerate(header_row))
            + " |"
        )
        lines.append(hdr_line)

        # Delimiter row with column alignment markers
        delims = self._build_delimiter_row(num_cols, col_widths, table.alignment)
        lines.append("| " + " | ".join(delims) + " |")

        # Body rows
        for row_cells in matrix[1:]:
            r_line = (
                "| "
                + " | ".join(cell.ljust(col_widths[i]) for i, cell in enumerate(row_cells))
                + " |"
            )
            lines.append(r_line)

        return "\n".join(lines)

    def _build_delimiter_row(
        self,
        num_cols: int,
        col_widths: Sequence[int],
        table_alignment: Alignment,
    ) -> List[str]:
        """Construct alignment delimiter strings for Markdown table header separator."""
        delims: List[str] = []
        for i in range(num_cols):
            w = max(3, col_widths[i])
            if table_alignment == Alignment.CENTER:
                delims.append(f":{'-' * (w - 2)}:")
            elif table_alignment == Alignment.RIGHT:
                delims.append(f"{'-' * (w - 1)}:")
            else:
                delims.append(f":{'-' * (w - 1)}")
        return delims

    def render_image(self, img: ImageBlock, image_counter: List[int]) -> str:
        """Render ImageBlock into a Markdown image reference."""
        idx = image_counter[0]
        image_counter[0] += 1
        alt = img.alt_text or f"Image_{idx}"
        ext = img.file_extension
        return f"![{alt}](image_{idx}{ext})"


__all__ = [
    "MarkdownEmitter",
    "MarkdownDialect",
    "resolve_dialect",
]
