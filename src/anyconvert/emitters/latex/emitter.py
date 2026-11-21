r"""Pure-Python LaTeX (.tex) document emitter architecture.

Generates clean, compilable LaTeX source with standard academic preamble:
- Document class & modal base font size (\documentclass[11pt]{article}).
- UTF-8 input/font encoding (\usepackage[utf8]{inputenc}, \usepackage[T1]{fontenc}).
- Page geometry & margins (\usepackage{geometry}, \geometry{...}).
- Graphics & publication-quality tables (\usepackage{graphicx}, \usepackage{booktabs}).
- Conditional lightweight packages (xcolor, hyperref, multirow, colortbl, ulem, fancyhdr).
- Reflowable headings, nested lists, verbatim code blocks, booktabs tables, and figures.
"""

from __future__ import annotations

from collections import Counter
import pathlib
import re
from typing import Dict, List, Optional, Tuple, Union

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
    TableCell,
    TextRun,
    VectorBlock,
)

# Monospace font family indicators
_MONOSPACE_FONTS = (
    "courier",
    "consolas",
    "menlo",
    "monaco",
    "lucida console",
    "dejavu sans mono",
    "liberation mono",
    "fira code",
    "jetbrains mono",
    "source code",
    "monospace",
    "inconsolata",
    "cascadia",
    "sf mono",
    "roboto mono",
    "ubuntu mono",
)

# List marker detection patterns
_BULLET_MARKERS = frozenset(
    {"•", "▪", "▫", "◦", "‣", "⁃", "●", "○", "■", "□", "◆", "◇", "▸", "▹", "➤", "➢", "–", "—", "-", "*", "+"}
)
_ORDERED_MARKER_RE = re.compile(r"^(\d+[.)]|[a-zA-Z][.)]|[ivxlcdmIVXLCDM]+[.)])$")
_TEXT_ORDERED_PREFIX_RE = re.compile(r"^(\d+[.)])\s+(.+)$")
_TEXT_BULLET_PREFIX_RE = re.compile(r"^([•▪▫◦‣⁃●○■□◆◇▸▹➤➢\-\*\+])\s+(.+)$")
_URL_RE = re.compile(r"^(https?://\S+|mailto:\S+)$", re.IGNORECASE)
_NUMERIC_CELL_RE = re.compile(r"^[+-]?(?:\$|€|£|¥)?\d[\d,]*(?:\.\d+)?%?$")

# Special LaTeX characters and safe replacements
_LATEX_SPECIAL_MAP: Dict[str, str] = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "$": r"\$",
    "&": r"\&",
    "#": r"\#",
    "%": r"\%",
    "_": r"\_",
    "^": r"\textasciicircum{}",
    "~": r"\textasciitilde{}",
    "<": r"\textless{}",
    ">": r"\textgreater{}",
    "\u00a0": "~",
    "\u2013": "--",
    "\u2014": "---",
    "\u2018": "`",
    "\u2019": "'",
    "\u201c": "``",
    "\u201d": "''",
    "\u2026": r"\ldots{}",
    "\u2022": r"\textbullet{}",
    "\u00b0": r"\textdegree{}",
    "\u00a9": r"\textcopyright{}",
    "\u00ae": r"\textregistered{}",
    "\u2122": r"\texttrademark{}",
}

_HEADING_COMMANDS: Dict[HeadingLevel, str] = {
    HeadingLevel.H1: "section",
    HeadingLevel.H2: "subsection",
    HeadingLevel.H3: "subsubsection",
    HeadingLevel.H4: "paragraph",
    HeadingLevel.H5: "subparagraph",
    HeadingLevel.H6: "subparagraph",
}


def escape_latex_text(text: str) -> str:
    """Escape raw text for safe inclusion in LaTeX text mode."""
    if not text:
        return ""
    out: List[str] = []
    for ch in text:
        if ch == "\r":
            continue
        if ch == "\n":
            out.append(" \\\\\n")
            continue
        if ch == "\t":
            out.append(" ")
            continue
        code = ord(ch)
        if code < 0x20 or code == 0x7F:
            continue
        mapped = _LATEX_SPECIAL_MAP.get(ch)
        if mapped is not None:
            out.append(mapped)
        else:
            out.append(ch)
    return "".join(out)


def escape_latex_url(url: str) -> str:
    """Escape characters that break LaTeX \\url{...} / \\href{...} arguments."""
    if not url:
        return ""
    cleaned = "".join(ch for ch in url.strip() if ord(ch) >= 0x20 and ord(ch) != 0x7F)
    return (
        cleaned.replace("\\", r"\\")
        .replace("%", r"\%")
        .replace("#", r"\#")
        .replace("{", r"\{")
        .replace("}", r"\}")
    )


def _format_pt(value: float) -> str:
    """Format a point measurement cleanly (e.g., 612pt or 595.28pt)."""
    rounded = round(value, 2)
    if abs(rounded - round(rounded)) < 1e-6:
        return f"{int(round(rounded))}pt"
    return f"{rounded:.2f}".rstrip("0").rstrip(".") + "pt"


def _is_monospace_font(font_name: str) -> bool:
    """Return True if font_name refers to a monospace/fixed-width typeface."""
    if not font_name:
        return False
    lower = font_name.lower()
    if "+" in lower and len(lower.split("+", 1)[0]) == 6:
        lower = lower.split("+", 1)[1]
    return any(mono in lower for mono in _MONOSPACE_FONTS)


def _is_monospace_paragraph(p: Paragraph) -> bool:
    """Return True when all non-whitespace runs in a body paragraph use a monospace font."""
    if p.heading_level is not None or not p.runs:
        return False
    has_text = False
    for r in p.runs:
        if r.text.strip():
            has_text = True
            if not _is_monospace_font(r.font_name):
                return False
    return has_text


def _detect_list_kind(p: Paragraph) -> Tuple[bool, bool]:
    """Return (is_list, is_ordered) for a Paragraph."""
    if p.heading_level is not None:
        return False, False
    if p.list_marker is not None:
        m = p.list_marker.strip()
        if m in _BULLET_MARKERS:
            return True, False
        if _ORDERED_MARKER_RE.match(m):
            return True, True
        return True, False
    raw = p.text.lstrip()
    if _TEXT_BULLET_PREFIX_RE.match(raw):
        return True, False
    if _TEXT_ORDERED_PREFIX_RE.match(raw):
        return True, True
    return False, False


def _strip_list_marker_from_first_run(p: Paragraph) -> Optional[str]:
    """Compute override text for the first non-empty run if it repeats the list marker."""
    for r in p.runs:
        if not r.text:
            continue
        raw = r.text.lstrip()
        m_bul = _TEXT_BULLET_PREFIX_RE.match(raw)
        if m_bul:
            return m_bul.group(2)
        m_ord = _TEXT_ORDERED_PREFIX_RE.match(raw)
        if m_ord:
            return m_ord.group(2)
        if p.list_marker and raw.startswith(p.list_marker):
            rem = raw[len(p.list_marker) :].lstrip()
            if rem != raw:
                return rem
        break
    return None


def _detect_modal_font_size(doc_ir: DocumentIR) -> int:
    """Select the standard LaTeX document class base font size (10, 11, or 12 pt)."""
    size_counts: Counter[float] = Counter()
    for page in doc_ir.pages:
        for block in page.blocks:
            if isinstance(block, Paragraph) and block.heading_level is None:
                for run in block.runs:
                    weight = len(run.text.strip())
                    if weight > 0 and run.font_size > 0:
                        size_counts[round(run.font_size, 1)] += weight
    if not size_counts:
        return 11
    modal = size_counts.most_common(1)[0][0]
    if modal <= 10.4:
        return 10
    if modal >= 11.6:
        return 12
    return 11


def _detect_latex_col_alignments(table: Table, num_cols: int) -> List[str]:
    """Resolve LaTeX tabular column alignment specs ('l', 'c', 'r') per column."""
    votes: List[List[Alignment]] = [[] for _ in range(num_cols)]
    num_rows = len(table.rows)
    occupied: List[List[bool]] = [[False] * num_cols for _ in range(num_rows)]

    for r_idx, row in enumerate(table.rows):
        c_idx = 0
        for cell in row.cells:
            while c_idx < num_cols and occupied[r_idx][c_idx]:
                c_idx += 1
            if c_idx >= num_cols:
                break
            cspan = max(1, min(cell.col_span, num_cols - c_idx))
            rspan = max(1, min(cell.row_span, num_rows - r_idx))
            for dr in range(rspan):
                for dc in range(cspan):
                    occupied[r_idx + dr][c_idx + dc] = True

            cell_align: Optional[Alignment] = None
            raw_txt = ""
            for b in cell.content:
                if isinstance(b, Paragraph):
                    raw_txt += b.text.strip()
                    if b.alignment != Alignment.LEFT:
                        cell_align = b.alignment
            if cell_align is not None:
                votes[c_idx].append(cell_align)
            elif not row.is_header and r_idx > 0 and _NUMERIC_CELL_RE.match(raw_txt):
                votes[c_idx].append(Alignment.RIGHT)
            elif raw_txt:
                votes[c_idx].append(Alignment.LEFT)
            c_idx += cspan

    has_non_left = any(
        any(v in (Alignment.RIGHT, Alignment.CENTER) for v in col_v)
        for col_v in votes
    )
    align_chars = {
        Alignment.LEFT: "l",
        Alignment.CENTER: "c",
        Alignment.RIGHT: "r",
        Alignment.JUSTIFIED: "l",
    }
    if not has_non_left:
        fallback = align_chars.get(table.alignment, "l")
        return [fallback] * num_cols

    resolved: List[str] = []
    for c in range(num_cols):
        col_v = votes[c]
        if not col_v:
            resolved.append("l")
            continue
        rights = sum(1 for v in col_v if v == Alignment.RIGHT)
        centers = sum(1 for v in col_v if v == Alignment.CENTER)
        total = len(col_v)
        if rights >= total / 2:
            resolved.append("r")
        elif centers >= total / 2:
            resolved.append("c")
        else:
            resolved.append("l")
    return resolved


class LatexEmitter(BaseEmitter):
    """Pure-Python LaTeX (.tex) document emitter generating clean, compilable source."""

    __slots__ = (
        "document_class",
        "numbered_headings",
        "render_headers_footers",
        "emit_pagebreaks",
        "emit_maketitle",
        "enable_math_heuristics",
        "image_dir",
        "image_link_prefix",
        "extracted_images",
        "_uses_strikethrough",
        "_uses_multirow",
        "_uses_colortbl",
        "_uses_math",
    )

    def __init__(
        self,
        document_class: str = "article",
        numbered_headings: bool = True,
        render_headers_footers: bool = True,
        emit_pagebreaks: bool = True,
        emit_maketitle: bool = False,
        enable_math_heuristics: bool = True,
        image_dir: Optional[Union[str, pathlib.Path]] = None,
        image_link_prefix: Optional[str] = None,
    ) -> None:
        self.document_class: str = document_class.strip() or "article"
        self.numbered_headings: bool = numbered_headings
        self.render_headers_footers: bool = render_headers_footers
        self.emit_pagebreaks: bool = emit_pagebreaks
        self.emit_maketitle: bool = emit_maketitle
        self.enable_math_heuristics: bool = enable_math_heuristics
        self.image_dir: Optional[pathlib.Path] = (
            pathlib.Path(image_dir) if image_dir is not None else None
        )
        self.image_link_prefix: Optional[str] = image_link_prefix
        self.extracted_images: List[pathlib.Path] = []
        self._uses_strikethrough: bool = False
        self._uses_multirow: bool = False
        self._uses_colortbl: bool = False
        self._uses_math: bool = False

    def emit(
        self,
        doc_ir: DocumentIR,
        mode: ConversionMode = ConversionMode.FLOW,
    ) -> bytes:
        """Serialize DocumentIR into UTF-8 encoded LaTeX (.tex) source bytes.

        Args:
            doc_ir: Validated DocumentIR structure.
            mode: Layout mode (informational; LaTeX uses reflowable typesetting).

        Returns:
            UTF-8 encoded bytes of the generated LaTeX source.

        Raises:
            SerializationError: If doc_ir contains no pages.
        """
        if not doc_ir.pages:
            raise SerializationError("Cannot emit LaTeX from empty DocumentIR")

        return self.render(doc_ir).encode("utf-8")

    def render(self, doc_ir: DocumentIR) -> str:
        """Render DocumentIR into a complete, compilable LaTeX source string."""
        if not doc_ir.pages:
            raise SerializationError("Cannot emit LaTeX from empty DocumentIR")

        self.extracted_images = []
        self._uses_strikethrough = False
        self._uses_multirow = False
        self._uses_colortbl = False
        self._uses_math = False

        # Render body first so conditional packages (ulem, multirow, colortbl) are exact
        body_sections: List[str] = []
        lowered_meta = {
            k.lstrip("/").lower(): v.strip()
            for k, v in doc_ir.metadata.items()
            if v and v.strip()
        }
        if self.emit_maketitle and "title" in lowered_meta:
            body_sections.append(r"\maketitle")

        image_counter = [1]
        for page_idx, page in enumerate(doc_ir.pages):
            if page_idx > 0:
                prev = doc_ir.pages[page_idx - 1]
                margins_changed = (
                    abs(page.margin_top - prev.margin_top) > 1.0
                    or abs(page.margin_bottom - prev.margin_bottom) > 1.0
                    or abs(page.margin_left - prev.margin_left) > 1.0
                    or abs(page.margin_right - prev.margin_right) > 1.0
                )
                if margins_changed:
                    body_sections.append(self._build_newgeometry(page))
                elif self.emit_pagebreaks:
                    body_sections.append(r"\newpage")

            printable_w = max(72.0, page.width - page.margin_left - page.margin_right)
            page_body = self.render_page(
                page,
                image_counter=image_counter,
                printable_width=printable_w,
            )
            if page_body:
                body_sections.append(page_body)

        preamble = self.build_preamble(
            doc_ir,
            use_strikethrough=self._uses_strikethrough,
            use_multirow=self._uses_multirow,
            use_colortbl=self._uses_colortbl,
            use_math=self._uses_math,
        )

        body_str = "\n\n".join(body_sections).strip()
        if body_str:
            return f"{preamble}\n\n\\begin{{document}}\n\n{body_str}\n\n\\end{{document}}\n"
        return f"{preamble}\n\n\\begin{{document}}\n\\end{{document}}\n"

    def build_preamble(
        self,
        doc_ir: DocumentIR,
        *,
        use_strikethrough: bool = False,
        use_multirow: bool = False,
        use_colortbl: bool = False,
        use_math: bool = False,
    ) -> str:
        """Construct the LaTeX document preamble with geometry, graphicx, booktabs, and metadata."""
        base_pt = _detect_modal_font_size(doc_ir)
        first_page = doc_ir.pages[0]

        lines: List[str] = [
            f"\\documentclass[{base_pt}pt]{{{self.document_class}}}",
            r"\usepackage[utf8]{inputenc}",
            r"\usepackage[T1]{fontenc}",
            r"\usepackage{lmodern}",
            r"\usepackage{geometry}",
            r"\usepackage{graphicx}",
            r"\usepackage{booktabs}",
            r"\usepackage{xcolor}",
        ]

        if use_math:
            lines.append(r"\usepackage{amsmath,amssymb}")
        if use_multirow:
            lines.append(r"\usepackage{multirow}")
        if use_colortbl:
            lines.append(r"\usepackage{colortbl}")
        if use_strikethrough:
            lines.append(r"\usepackage[normalem]{ulem}")

        hdr_txt, ftr_txt = self._extract_header_footer(first_page)
        if hdr_txt or ftr_txt:
            lines.append(r"\usepackage{fancyhdr}")

        lines.append(r"\usepackage[hidelinks]{hyperref}")

        # Page geometry configuration
        w = max(72.0, first_page.width)
        h = max(72.0, first_page.height)
        m_top = max(0.0, first_page.margin_top)
        m_bottom = max(0.0, first_page.margin_bottom)
        m_left = max(0.0, first_page.margin_left)
        m_right = max(0.0, first_page.margin_right)
        lines.append("")
        lines.append(
            "\\geometry{\n"
            f"  paperwidth={_format_pt(w)},\n"
            f"  paperheight={_format_pt(h)},\n"
            f"  top={_format_pt(m_top)},\n"
            f"  bottom={_format_pt(m_bottom)},\n"
            f"  left={_format_pt(m_left)},\n"
            f"  right={_format_pt(m_right)},\n"
            "}"
        )

        # Header / footer setup via fancyhdr
        if hdr_txt or ftr_txt:
            lines.append("")
            lines.append(r"\pagestyle{fancy}")
            lines.append(r"\fancyhf{}")
            if hdr_txt:
                lines.append(f"\\fancyhead[R]{{\\small {hdr_txt}}}")
            if ftr_txt:
                lines.append(f"\\fancyfoot[C]{{\\small {ftr_txt}}}")
            lines.append(r"\renewcommand{\headrulewidth}{0pt}")

        # Document metadata (\title, \author, \date, \hypersetup)
        meta_block = self.build_metadata_preamble(doc_ir.metadata)
        if meta_block:
            lines.append("")
            lines.append(meta_block)

        return "\n".join(lines)

    def build_metadata_preamble(self, metadata: Dict[str, str]) -> str:
        """Build LaTeX \\title, \\author, \\date, and \\hypersetup directives from metadata."""
        if not metadata:
            return ""
        lowered = {
            k.lstrip("/").lower(): v.strip()
            for k, v in metadata.items()
            if v and v.strip()
        }
        lines: List[str] = []
        hyper_args: List[str] = []

        if "title" in lowered:
            escaped_title = escape_latex_text(lowered["title"])
            lines.append(f"\\title{{{escaped_title}}}")
            hyper_args.append(f"pdftitle={{{escaped_title}}}")
        if "author" in lowered:
            authors = [a.strip() for a in re.split(r"[;]+", lowered["author"]) if a.strip()]
            if authors:
                escaped_authors = [escape_latex_text(a) for a in authors]
                joined_authors = r" \and ".join(escaped_authors)
                lines.append(f"\\author{{{joined_authors}}}")
                hyper_args.append(f"pdfauthor={{{', '.join(escaped_authors)}}}")
        if "title" in lowered or "author" in lowered:
            date_val = lowered.get("creationdate", "")
            if date_val:
                lines.append(f"\\date{{{escape_latex_text(date_val)}}}")
            else:
                lines.append(r"\date{}")
        if "subject" in lowered:
            hyper_args.append(f"pdfsubject={{{escape_latex_text(lowered['subject'])}}}")
        if "keywords" in lowered:
            hyper_args.append(f"pdfkeywords={{{escape_latex_text(lowered['keywords'])}}}")

        if hyper_args:
            lines.append("\\hypersetup{\n  " + ",\n  ".join(hyper_args) + ",\n}")

        return "\n".join(lines)

    def _build_newgeometry(self, page: DocumentPage) -> str:
        """Build \\newgeometry{...} directive when margins change across pages."""
        m_top = max(0.0, page.margin_top)
        m_bottom = max(0.0, page.margin_bottom)
        m_left = max(0.0, page.margin_left)
        m_right = max(0.0, page.margin_right)
        return (
            f"\\newgeometry{{top={_format_pt(m_top)}, bottom={_format_pt(m_bottom)}, "
            f"left={_format_pt(m_left)}, right={_format_pt(m_right)}}}"
        )

    def _extract_header_footer(self, page: DocumentPage) -> Tuple[str, str]:
        """Extract escaped header and footer text from a DocumentPage."""
        if not self.render_headers_footers:
            return "", ""
        hdr_txt = ""
        ftr_txt = ""
        if page.header and page.header.content:
            hdr_txt = " ".join(
                escape_latex_text(p.text.strip())
                for p in page.header.content
                if p.text.strip()
            )
        if page.footer and page.footer.content:
            ftr_txt = " ".join(
                escape_latex_text(p.text.strip())
                for p in page.footer.content
                if p.text.strip()
            )
        return hdr_txt, ftr_txt

    def render_page(
        self,
        page: DocumentPage,
        image_counter: Optional[List[int]] = None,
        printable_width: float = 468.0,
    ) -> str:
        """Render all body blocks of a DocumentPage, grouping code blocks and lists."""
        counter = image_counter if image_counter is not None else [1]
        out_chunks: List[str] = []
        blocks = page.blocks
        n = len(blocks)
        i = 0

        while i < n:
            block = blocks[i]

            # 1. Group consecutive monospace paragraphs into a single code block
            if isinstance(block, Paragraph) and _is_monospace_paragraph(block):
                code_lines: List[str] = []
                while i < n:
                    nxt = blocks[i]
                    if isinstance(nxt, Paragraph) and _is_monospace_paragraph(nxt):
                        code_lines.append(nxt.text.rstrip("\r\n"))
                        i += 1
                    else:
                        break
                out_chunks.append(self.render_code_block("\n".join(code_lines)))
                continue

            # 2. Group consecutive list paragraphs into itemize/enumerate environments
            if isinstance(block, Paragraph) and _detect_list_kind(block)[0]:
                list_paras: List[Tuple[Paragraph, bool]] = []
                while i < n:
                    nxt = blocks[i]
                    if isinstance(nxt, Paragraph):
                        is_lst, is_ord = _detect_list_kind(nxt)
                        if is_lst:
                            list_paras.append((nxt, is_ord))
                            i += 1
                            continue
                    break
                rendered_list = self.render_list_group(list_paras)
                if rendered_list:
                    out_chunks.append(rendered_list)
                continue

            rendered = self.render_block(block, counter, printable_width=printable_width)
            if rendered:
                out_chunks.append(rendered)
            i += 1

        return "\n\n".join(out_chunks)

    def render_block(
        self,
        block: BlockNode,
        image_counter: List[int],
        printable_width: float = 468.0,
    ) -> str:
        """Render a single BlockNode into LaTeX markup."""
        if isinstance(block, Paragraph):
            return self.render_paragraph(block)
        if isinstance(block, Table):
            return self.render_table(block)
        if isinstance(block, ImageBlock):
            return self.render_image(block, image_counter, printable_width=printable_width)
        if isinstance(block, VectorBlock):
            return ""
        return ""

    def render_code_block(self, code_text: str) -> str:
        """Render a block of source code using verbatim (or safe ttfamily fallback)."""
        if r"\end{verbatim}" in code_text:
            escaped_lines = [escape_latex_text(ln) for ln in code_text.splitlines()]
            body = " \\\\\n".join(escaped_lines)
            return f"\\begin{{quote}}\\ttfamily\n{body}\n\\end{{quote}}"
        return f"\\begin{{verbatim}}\n{code_text}\n\\end{{verbatim}}"

    def render_list_group(self, items: List[Tuple[Paragraph, bool]]) -> str:
        """Render contiguous list items into properly nested itemize/enumerate environments."""
        if not items:
            return ""
        lines: List[str] = []
        # Stack of (level, env_name)
        stack: List[Tuple[int, str]] = []

        for p, is_ordered in items:
            level = max(0, min(3, p.list_level))
            env = "enumerate" if is_ordered else "itemize"

            # Close deeper environments or same-level mismatched environment
            while stack and (stack[-1][0] > level or (stack[-1][0] == level and stack[-1][1] != env)):
                closed_lvl, closed_env = stack.pop()
                lines.append(f"{'  ' * closed_lvl}\\end{{{closed_env}}}")

            # Open new environment if needed
            if not stack or stack[-1][0] < level:
                lines.append(f"{'  ' * level}\\begin{{{env}}}")
                stack.append((level, env))

            override = _strip_list_marker_from_first_run(p)
            body = self._render_paragraph_runs(p, first_run_override=override).strip()
            if not body:
                continue
            lines.append(f"{'  ' * level}  \\item {body}")

        while stack:
            closed_lvl, closed_env = stack.pop()
            lines.append(f"{'  ' * closed_lvl}\\end{{{closed_env}}}")

        return "\n".join(lines)

    def _render_paragraph_runs(
        self,
        p: Paragraph,
        first_run_override: Optional[str] = None,
        suppress_bold: bool = False,
    ) -> str:
        """Render all inline TextRuns of a Paragraph."""
        if self.enable_math_heuristics:
            from anyconvert.emitters.latex.math import render_latex_math_runs

            rendered, used_math = render_latex_math_runs(
                p.runs,
                render_run_fn=lambda r, ov, sb: self.render_run(
                    r, override_text=ov, suppress_bold=sb
                ),
                first_run_override=first_run_override,
                suppress_bold=suppress_bold,
            )
            if used_math:
                self._uses_math = True
            return rendered

        parts: List[str] = []
        override_applied = False
        for r in p.runs:
            if not override_applied and first_run_override is not None and r.text:
                parts.append(
                    self.render_run(r, override_text=first_run_override, suppress_bold=suppress_bold)
                )
                override_applied = True
            else:
                parts.append(self.render_run(r, suppress_bold=suppress_bold))
        return "".join(parts)

    def render_paragraph(self, p: Paragraph) -> str:
        """Render a Paragraph into a LaTeX section heading, aligned block, or body paragraph."""
        if not p.runs:
            return ""
        if p.heading_level is not None:
            cmd = _HEADING_COMMANDS.get(p.heading_level, "section")
            star = "" if self.numbered_headings else "*"
            inner = self._render_paragraph_runs(p, suppress_bold=True).strip()
            if not inner:
                return ""
            return f"\\{cmd}{star}{{{inner}}}"

        body = self._render_paragraph_runs(p).strip()
        if not body:
            return ""

        if p.alignment == Alignment.CENTER:
            return f"\\begin{{center}}\n{body}\n\\end{{center}}"
        if p.alignment == Alignment.RIGHT:
            return f"\\begin{{flushright}}\n{body}\n\\end{{flushright}}"
        return body

    def render_run(
        self,
        run: TextRun,
        override_text: Optional[str] = None,
        suppress_bold: bool = False,
    ) -> str:
        """Render an inline TextRun into idiomatic LaTeX inline commands."""
        raw = run.text if override_text is None else override_text
        if not raw:
            return ""

        stripped = raw.strip()
        if not stripped:
            return escape_latex_text(raw)

        # Hoist boundary whitespace outside inline commands
        lead_len = len(raw) - len(raw.lstrip())
        trail_len = len(raw) - len(raw.rstrip())
        lead = raw[:lead_len]
        trail = raw[len(raw) - trail_len :] if trail_len > 0 else ""

        # Bare hyperlink run
        if _URL_RE.match(stripped):
            return f"{lead}\\url{{{escape_latex_url(stripped)}}}{trail}"

        escaped = escape_latex_text(stripped)
        if not escaped:
            return lead + trail

        content = escaped

        # Monospace inline code
        if _is_monospace_font(run.font_name):
            content = f"\\texttt{{{content}}}"

        # Bold / Italic
        apply_bold = run.is_bold and not suppress_bold
        if run.is_italic:
            content = f"\\textit{{{content}}}"
        if apply_bold:
            content = f"\\textbf{{{content}}}"

        # Underline / Strikethrough
        if run.is_underline:
            content = f"\\underline{{{content}}}"
        if run.is_strikethrough:
            self._uses_strikethrough = True
            content = f"\\sout{{{content}}}"

        # Superscript / Subscript baseline shifts
        if run.baseline_offset > 0.5:
            content = f"\\textsuperscript{{{content}}}"
        elif run.baseline_offset < -0.5:
            content = f"\\textsubscript{{{content}}}"

        # Non-black color
        r_c, g_c, b_c = run.color.r, run.color.g, run.color.b
        if (r_c + g_c + b_c) > 45:
            hex_rgb = f"{r_c:02X}{g_c:02X}{b_c:02X}"
            content = f"\\textcolor[HTML]{{{hex_rgb}}}{{{content}}}"

        return f"{lead}{content}{trail}"

    def _format_cell_body(self, cell: TableCell) -> str:
        """Render inner Paragraphs of a TableCell into inline LaTeX content."""
        para_strs: List[str] = []
        for sub in cell.content:
            if isinstance(sub, Paragraph):
                txt = self._render_paragraph_runs(sub).strip()
                if txt:
                    para_strs.append(txt)
        return " ".join(para_strs)

    def render_table(self, table: Table) -> str:
        """Render a Table node into a publication-quality LaTeX booktabs table."""
        if not table.rows:
            return ""

        num_cols = max(
            len(table.col_widths),
            max((sum(max(1, c.col_span) for c in row.cells) for row in table.rows), default=0),
        )
        if num_cols <= 0:
            return ""

        num_rows = len(table.rows)
        col_aligns = _detect_latex_col_alignments(table, num_cols)
        col_spec = "".join(col_aligns)

        occupied: List[List[bool]] = [[False] * num_cols for _ in range(num_rows)]
        lines: List[str] = [
            r"\begin{table}[htbp]",
            r"\centering",
            f"\\begin{{tabular}}{{{col_spec}}}",
            r"\toprule",
        ]

        header_count = 0
        for row in table.rows:
            if row.is_header:
                header_count += 1
            else:
                break

        for r_idx, row in enumerate(table.rows):
            row_cells_tex: List[str] = []
            c_idx = 0

            for cell in row.cells:
                while c_idx < num_cols and occupied[r_idx][c_idx]:
                    row_cells_tex.append("")
                    c_idx += 1
                if c_idx >= num_cols:
                    break

                cspan = max(1, min(cell.col_span, num_cols - c_idx))
                rspan = max(1, min(cell.row_span, num_rows - r_idx))
                for dr in range(rspan):
                    for dc in range(cspan):
                        occupied[r_idx + dr][c_idx + dc] = True

                body = self._format_cell_body(cell)
                cell_prefix = ""
                if cell.background_color is not None:
                    bg = cell.background_color
                    if not (bg.r >= 250 and bg.g >= 250 and bg.b >= 250):
                        self._uses_colortbl = True
                        cell_prefix = f"\\cellcolor[HTML]{{{bg.r:02X}{bg.g:02X}{bg.b:02X}}}"

                if rspan > 1:
                    self._uses_multirow = True
                    body = f"\\multirow{{{rspan}}}{{*}}{{{body}}}"

                cell_inner = f"{cell_prefix}{body}"
                if cspan > 1:
                    span_align = col_aligns[c_idx]
                    cell_tex = f"\\multicolumn{{{cspan}}}{{{span_align}}}{{{cell_inner}}}"
                else:
                    cell_tex = cell_inner

                row_cells_tex.append(cell_tex)
                c_idx += cspan

            while c_idx < num_cols:
                row_cells_tex.append("")
                c_idx += 1

            lines.append(" & ".join(row_cells_tex) + r" \\")
            if header_count > 0 and r_idx == header_count - 1 and r_idx < num_rows - 1:
                lines.append(r"\midrule")

        lines.append(r"\bottomrule")
        lines.append(r"\end{tabular}")
        lines.append(r"\end{table}")
        return "\n".join(lines)

    def render_image(
        self,
        img: ImageBlock,
        image_counter: List[int],
        printable_width: float = 468.0,
    ) -> str:
        """Render an ImageBlock as an external \\includegraphics figure or compilable placeholder."""
        idx = image_counter[0]
        image_counter[0] += 1
        img.sync_format()
        alt = img.alt_text.strip() if img.alt_text else f"Image {idx}"
        escaped_alt = escape_latex_text(alt)

        if self.image_dir is not None and img.image_bytes:
            ext = img.file_extension
            filename = f"img_{idx}{ext}"
            self.image_dir.mkdir(parents=True, exist_ok=True)
            target = self.image_dir / filename
            target.write_bytes(img.image_bytes)
            self.extracted_images.append(target)

            if self.image_link_prefix is not None:
                prefix = self.image_link_prefix.rstrip("/")
                rel_ref = f"{prefix}/{filename}" if prefix else filename
            else:
                rel_ref = f"{self.image_dir.as_posix().rstrip('/')}/{filename}"

            if img.bbox.width > 1.0:
                clamped_w = min(img.bbox.width, max(72.0, printable_width))
                width_opt = f"width={_format_pt(clamped_w)}"
            else:
                width_opt = r"width=0.8\linewidth"

            return (
                "\\begin{figure}[htbp]\n"
                "  \\centering\n"
                f"  \\includegraphics[{width_opt}]{{{rel_ref}}}\n"
                f"  \\caption{{{escaped_alt}}}\n"
                "\\end{figure}"
            )

        return (
            "\\begin{figure}[htbp]\n"
            "  \\centering\n"
            f"  \\fbox{{\\parbox{{0.8\\linewidth}}{{\\centering {escaped_alt}}}}}\n"
            f"  \\caption{{{escaped_alt}}}\n"
            "\\end{figure}"
        )


__all__ = [
    "LatexEmitter",
    "escape_latex_text",
    "escape_latex_url",
]
