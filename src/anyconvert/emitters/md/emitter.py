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
from anyconvert.emitters.md.tables import (
    build_delimiter_cells,
    format_table_matrix,
)
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
        idx = 0
        blocks = page.blocks
        n_blocks = len(blocks)

        while idx < n_blocks:
            block = blocks[idx]
            if isinstance(block, Paragraph) and self._is_code_paragraph(block):
                code_lines: List[str] = [block.text]
                idx += 1
                while idx < n_blocks:
                    next_block = blocks[idx]
                    if isinstance(next_block, Paragraph) and self._is_code_paragraph(next_block):
                        code_lines.append(next_block.text)
                        idx += 1
                    else:
                        break
                code_text = "\n".join(code_lines)
                block_strings.append(self._render_code_block(code_text))
            else:
                b_str = self.render_block(block, counter)
                if b_str:
                    block_strings.append(b_str)
                idx += 1

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

        # Task list prefix detection embedded in paragraph text
        if self.dialect == MarkdownDialect.GFM:
            m_task = re.match(
                r"^(\[[ xXvV_]\]|\([ xX]\)|[☐☑☒✓✔✕✖])\s+(.*)$",
                para_text,
                re.DOTALL,
            )
            if m_task:
                box = m_task.group(1).replace(" ", "")
                rest = m_task.group(2)
                is_checked = box in (
                    "[x]",
                    "[X]",
                    "[v]",
                    "[V]",
                    "(x)",
                    "(X)",
                    "☑",
                    "☒",
                    "✓",
                    "✔",
                )
                task_token = "- [x]" if is_checked else "- [ ]"
                indent = "  " * max(0, p.list_level)
                return f"{indent}{task_token} {rest}"

        # List items: bullet lists, numbered lists, task lists
        if p.list_marker:
            return self._format_list_item(p, para_text)

        # Standalone monospace paragraph formatted as code fence
        if self._is_code_paragraph(p):
            return self._render_code_block(p.text)

        return para_text

    def _format_list_item(self, p: Paragraph, para_text: str) -> str:
        """Format paragraph as an unordered, ordered, or GFM task checklist item."""
        indent = "  " * max(0, p.list_level)
        marker = p.list_marker.strip() if p.list_marker else "-"

        # Check for task checklist in GFM mode
        if self.dialect == MarkdownDialect.GFM:
            marker_nospace = marker.replace(" ", "")
            if marker_nospace in ("[]", "[_]", "()") or marker in (
                "[ ]",
                "☐",
                "✕",
                "✖",
            ):
                return f"{indent}- [ ] {para_text}"
            elif marker_nospace in (
                "[x]",
                "[X]",
                "[v]",
                "[V]",
                "[*]",
                "(x)",
                "(X)",
            ) or marker in ("☑", "☒", "✓", "✔", "√"):
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

    def _is_code_paragraph(self, p: Paragraph) -> bool:
        """Determine if a Paragraph is a code block consisting of monospace runs."""
        if p.heading_level is not None or p.list_marker:
            return False
        non_empty_runs = [r for r in p.runs if r.text.strip()]
        if not non_empty_runs:
            return False
        return all(self._is_monospace(r.font_name) for r in non_empty_runs)

    def _detect_code_language(self, code: str) -> str:
        """Detect language identifier for Markdown fenced code block."""
        stripped = code.strip()
        if not stripped:
            return ""
        lines = [ln.strip() for ln in stripped.splitlines() if ln.strip()]
        if not lines:
            return ""
        first_line = lines[0]

        # Python
        if any(
            first_line.startswith(kw)
            for kw in ("import ", "from ", "def ", "class ", "#!/usr/bin/env python")
        ):
            return "python"
        if any(
            re.search(r"\b(def|elif|import|raise|except)\b", line)
            for line in lines[:5]
        ):
            return "python"

        # Shell / Bash
        if first_line.startswith(("#!/bin/bash", "#!/bin/sh", "$ ", "> ")):
            return "bash"
        if any(
            re.match(
                r"^(?:sudo\s+|apt\s+|npm\s+|pip\s+|git\s+|docker\s+|cargo\s+)", line
            )
            for line in lines[:3]
        ):
            return "bash"

        # JSON
        if (
            (stripped.startswith("{") and stripped.endswith("}"))
            or (stripped.startswith("[") and stripped.endswith("]"))
        ):
            if ":" in stripped:
                return "json"

        # XML / HTML
        if (
            stripped.startswith("<!DOCTYPE")
            or stripped.startswith("<html")
            or (stripped.startswith("<") and stripped.endswith(">"))
        ):
            return "xml"

        # SQL
        if any(
            re.match(
                r"^(?:SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP)\s+",
                line,
                re.IGNORECASE,
            )
            for line in lines[:3]
        ):
            return "sql"

        # Rust
        if any(
            line.startswith(("fn ", "pub fn ", "let mut ", "impl "))
            for line in lines[:3]
        ):
            return "rust"

        # C / C++
        if any(
            line.startswith(("#include", "int main(")) for line in lines[:3]
        ):
            return "c"

        return ""

    def _render_code_block(self, code_text: str) -> str:
        """Wrap code text in a Markdown fenced code block with appropriate fences."""
        lang = self._detect_code_language(code_text)
        fence = "```"
        if "```" in code_text:
            matches = list(re.finditer(r"`+", code_text))
            max_bt = max(len(m.group(0)) for m in matches) if matches else 3
            fence = "`" * max(3, max_bt + 1)
        return f"{fence}{lang}\n{code_text}\n{fence}"

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
        return format_table_matrix(table, run_renderer=self.render_run)

    def _build_delimiter_row(
        self,
        num_cols: int,
        col_widths: Sequence[int],
        table_alignment: Alignment,
    ) -> List[str]:
        """Construct alignment delimiter strings for Markdown table header separator."""
        return build_delimiter_cells(col_widths, [table_alignment] * num_cols)

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
