"""Semantic HTML5 Flow Mode Generation Module.

Generates responsive, accessible, SEO-friendly HTML5 document flows from DocumentIR,
using semantic markup (<article>, <header>, <footer>, <main>, <h1>-<h6>, <p>, <ul>, <ol>,
<li>, <table class="pure-table">, <figure>, <figcaption>).
"""

from __future__ import annotations

import base64
import re
from typing import List, Optional, Sequence, Tuple

from anyconvert.common.color import Color
from anyconvert.emitters.base import color_to_hex, xml_escape
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
    TableRow,
    TextRun,
    VectorBlock,
    detect_image_format,
)

# Common unordered bullet prefixes in text streams
UNORDERED_BULLET_RE = re.compile(
    r"^[\s]*([•·○●▪■▫–—\*\-]|[\u2022\u00b7\u25cb\u25cf\u25aa\u25a0\u25ab\u2013\u2014\u2713\u27a4])\s+"
)

# Common ordered list numbering prefixes in text streams (e.g. "1.", "1)", "(1)", "a.", "i.")
ORDERED_NUMBER_RE = re.compile(
    r"^[\s]*(\(?\d+[\.\)]|\(?[a-zA-Z][\.\)]|\(?[ivxlcdmIVXLCDM]+[\.\)])\s+"
)

# URL matching regex for automatic anchor tagging
URL_RE = re.compile(r"^(https?://|mailto:)[^\s]+$")

# Monospace font name indicators
MONOSPACE_FONT_KEYWORDS = (
    "mono",
    "courier",
    "consolas",
    "menlo",
    "monaco",
    "dejavusansmono",
    "liberationmono",
    "sourcecodepro",
    "terminal",
)


class FlowHTMLRenderer:
    """Renderer for semantic reflowable HTML5 documents."""

    def __init__(self, indent_step: str = "  ") -> None:
        self.indent_step = indent_step

    def render_body(self, doc_ir: DocumentIR) -> str:
        """Render the complete body content of a DocumentIR hierarchy.

        Args:
            doc_ir: Document intermediate representation.

        Returns:
            HTML string containing the <main class="document-flow"> block.
        """
        lines: List[str] = ['  <main class="document-flow">']

        for page_idx, page in enumerate(doc_ir.pages):
            page_num = page_idx + 1
            lines.append(f'    <article id="page-{page_num}" class="page-flow">')

            # Marginal header
            if page.header and page.header.content:
                lines.append('      <header class="page-header" role="doc-pageheader">')
                for p in page.header.content:
                    lines.append(self.render_paragraph(p, indent="        "))
                lines.append('      </header>')

            # Page content blocks
            lines.extend(self._render_blocks(page.blocks, indent="      "))

            # Marginal footer
            if page.footer and page.footer.content:
                lines.append('      <footer class="page-footer" role="doc-pagefooter">')
                for p in page.footer.content:
                    lines.append(self.render_paragraph(p, indent="        "))
                lines.append('      </footer>')

            lines.append('    </article>')

        lines.append('  </main>')
        return "\n".join(lines)

    def _render_blocks(self, blocks: Sequence[BlockNode], indent: str = "      ") -> List[str]:
        """Render a sequence of content blocks, grouping list items into <ul> or <ol>."""
        lines: List[str] = []
        i = 0
        n = len(blocks)

        while i < n:
            block = blocks[i]

            if isinstance(block, Paragraph):
                is_list, list_type = self._detect_list_type(block)
                if is_list and list_type:
                    # Group contiguous list items of the same list type
                    list_items: List[Paragraph] = []
                    while i < n:
                        candidate = blocks[i]
                        if isinstance(candidate, Paragraph):
                            cand_is_list, cand_type = self._detect_list_type(candidate)
                            if cand_is_list and cand_type == list_type:
                                list_items.append(candidate)
                                i += 1
                                continue
                        break
                    lines.append(self.render_list(list_items, list_type, indent=indent))
                    continue
                else:
                    lines.append(self.render_paragraph(block, indent=indent))
                    i += 1
            elif isinstance(block, Table):
                lines.append(self.render_table(block, indent=indent))
                i += 1
            elif isinstance(block, ImageBlock):
                lines.append(self.render_image(block, indent=indent))
                i += 1
            elif isinstance(block, VectorBlock):
                lines.append(self.render_vector(block, indent=indent))
                i += 1
            else:
                i += 1

        return lines

    def _detect_list_type(self, p: Paragraph) -> Tuple[bool, Optional[str]]:
        """Determine if a paragraph is a list item and whether it is 'ul' or 'ol'."""
        if p.list_marker:
            marker = p.list_marker.strip()
            if marker in ("•", "o", "▪", "-", "*", "–", "—", "·", "●", "○", "▫", "■"):
                return True, "ul"
            if marker.endswith(".") or marker.endswith(")") or marker.isdigit():
                return True, "ol"
            return True, "ul"

        # Check plain text prefix if runs exist
        para_text = p.text
        if not para_text.strip():
            return False, None

        if UNORDERED_BULLET_RE.match(para_text):
            return True, "ul"
        if ORDERED_NUMBER_RE.match(para_text):
            return True, "ol"

        return False, None

    def render_list(
        self,
        items: Sequence[Paragraph],
        list_type: str,
        indent: str = "      ",
    ) -> str:
        """Render a group of paragraphs as a semantic <ul> or <ol> list."""
        tag = "ol" if list_type == "ol" else "ul"
        lines: List[str] = [f'{indent}<{tag} class="flow-list">']

        for p in items:
            runs_html = self._render_runs_for_list_item(p)
            lines.append(f'{indent}  <li>{runs_html}</li>')

        lines.append(f'{indent}</{tag}>')
        return "\n".join(lines)

    def _render_runs_for_list_item(self, p: Paragraph) -> str:
        """Render paragraph runs while cleanly stripping bullet/number markers."""
        if not p.runs:
            return ""

        # Make copy of runs texts to strip marker without modifying original IR
        first_text = p.runs[0].text
        stripped_prefix = ""

        if p.list_marker and first_text.startswith(p.list_marker):
            stripped_prefix = p.list_marker
        else:
            m_ul = UNORDERED_BULLET_RE.match(first_text)
            if m_ul:
                stripped_prefix = m_ul.group(0)
            else:
                m_ol = ORDERED_NUMBER_RE.match(first_text)
                if m_ol:
                    stripped_prefix = m_ol.group(0)

        rendered_runs: List[str] = []
        for idx, r in enumerate(p.runs):
            if idx == 0 and stripped_prefix:
                remaining_text = first_text[len(stripped_prefix):]
                rendered_runs.append(self.render_run(r, override_text=remaining_text))
            else:
                rendered_runs.append(self.render_run(r))

        return "".join(rendered_runs)

    def render_paragraph(self, p: Paragraph, indent: str = "      ") -> str:
        """Render a Paragraph into a semantic HTML5 tag (h1-h6, p)."""
        tag_map = {
            HeadingLevel.H1: "h1",
            HeadingLevel.H2: "h2",
            HeadingLevel.H3: "h3",
            HeadingLevel.H4: "h4",
            HeadingLevel.H5: "h5",
            HeadingLevel.H6: "h6",
        }
        tag = tag_map.get(p.heading_level, "p") if p.heading_level is not None else "p"

        attrs: List[str] = []
        styles: List[str] = []

        if p.alignment == Alignment.CENTER:
            styles.append("text-align: center;")
        elif p.alignment == Alignment.RIGHT:
            styles.append("text-align: right;")
        elif p.alignment == Alignment.JUSTIFIED:
            styles.append("text-align: justify;")

        if styles:
            attrs.append(f'style="{" ".join(styles)}"')

        attr_str = f" {' '.join(attrs)}" if attrs else ""
        runs_html = "".join(self.render_run(r) for r in p.runs)

        return f"{indent}<{tag}{attr_str}>{runs_html}</{tag}>"

    def render_run(self, r: TextRun, override_text: Optional[str] = None) -> str:
        """Render an individual TextRun with inline styling."""
        raw_text = override_text if override_text is not None else r.text
        text = xml_escape(raw_text)

        if not text:
            return ""

        # Automatic link detection
        stripped = raw_text.strip()
        is_link = bool(URL_RE.match(stripped))

        # Check font characteristics
        fn_lower = r.font_name.lower().replace("-", "").replace("_", "").replace(" ", "")
        is_code = any(k in fn_lower for k in MONOSPACE_FONT_KEYWORDS)

        if is_code:
            text = f"<code>{text}</code>"

        if r.is_bold:
            text = f"<strong>{text}</strong>"
        if r.is_italic:
            text = f"<em>{text}</em>"
        if r.is_underline and not is_link:
            text = f"<u>{text}</u>"
        if r.is_strikethrough:
            text = f"<s>{text}</s>"

        if r.baseline_offset > 0.5:
            text = f"<sup>{text}</sup>"
        elif r.baseline_offset < -0.5:
            text = f"<sub>{text}</sub>"

        # Apply custom text color if not standard black
        if r.color and (r.color.r, r.color.g, r.color.b) != (0, 0, 0):
            hex_color = color_to_hex(r.color).lower()
            text = f'<span style="color: #{hex_color};">{text}</span>'

        if is_link:
            url_target = xml_escape(stripped)
            text = f'<a href="{url_target}" rel="noopener">{text}</a>'

        return text

    def render_table(self, tbl: Table, indent: str = "      ") -> str:
        """Render a Table into a semantic <table class="pure-table"> element."""
        if not tbl.rows:
            return ""

        lines: List[str] = [f'{indent}<table class="pure-table">']

        header_rows = [r for r in tbl.rows if r.is_header]
        body_rows = [r for r in tbl.rows if not r.is_header]

        if header_rows:
            lines.append(f'{indent}  <thead>')
            for row in header_rows:
                lines.append(self._render_table_row(row, is_header=True, indent=f"{indent}    "))
            lines.append(f'{indent}  </thead>')

        if body_rows:
            lines.append(f'{indent}  <tbody>')
            for row in body_rows:
                lines.append(self._render_table_row(row, is_header=False, indent=f"{indent}    "))
            lines.append(f'{indent}  </tbody>')
        elif not header_rows:
            # Fallback for tables where no header flag was set
            lines.append(f'{indent}  <tbody>')
            for row in tbl.rows:
                lines.append(self._render_table_row(row, is_header=False, indent=f"{indent}    "))
            lines.append(f'{indent}  </tbody>')

        lines.append(f'{indent}</table>')
        return "\n".join(lines)

    def _render_table_row(self, row: TableRow, is_header: bool, indent: str = "        ") -> str:
        """Render a single table row with <th> or <td> cells."""
        lines: List[str] = [f'{indent}<tr>']
        cell_tag = "th" if is_header else "td"

        for cell in row.cells:
            attrs: List[str] = []
            styles: List[str] = []

            if cell.col_span > 1:
                attrs.append(f'colspan="{cell.col_span}"')
            if cell.row_span > 1:
                attrs.append(f'rowspan="{cell.row_span}"')

            if cell.background_color:
                bg_hex = color_to_hex(cell.background_color).lower()
                styles.append(f"background-color: #{bg_hex};")

            if styles:
                attrs.append(f'style="{" ".join(styles)}"')

            attr_str = f" {' '.join(attrs)}" if attrs else ""

            cell_html_parts: List[str] = []
            if (
                len(cell.content) == 1
                and isinstance(cell.content[0], Paragraph)
                and cell.content[0].heading_level is None
                and cell.content[0].alignment == Alignment.LEFT
            ):
                cell_html_parts.append("".join(self.render_run(r) for r in cell.content[0].runs))
            else:
                for block in cell.content:
                    if isinstance(block, Paragraph):
                        cell_html_parts.append(self.render_paragraph(block, indent="").strip())
                    elif isinstance(block, ImageBlock):
                        cell_html_parts.append(self.render_image(block, indent="").strip())
                    elif isinstance(block, VectorBlock):
                        cell_html_parts.append(self.render_vector(block, indent="").strip())

            content_html = "".join(cell_html_parts)
            lines.append(f'{indent}  <{cell_tag}{attr_str}>{content_html}</{cell_tag}>')

        lines.append(f'{indent}</tr>')
        return "\n".join(lines)

    def render_image(self, img: ImageBlock, indent: str = "      ") -> str:
        """Render an ImageBlock as a Base64 Data URI inside a semantic <figure>."""
        if not img.image_bytes:
            return ""

        mime_type = self._resolve_mime_type(img)
        b64 = base64.b64encode(img.image_bytes).decode("ascii")
        alt = xml_escape(img.alt_text)

        lines: List[str] = [
            f'{indent}<figure class="flow-figure">',
            f'{indent}  <img src="data:{mime_type};base64,{b64}" alt="{alt}" loading="lazy"/>',
        ]
        if img.alt_text:
            lines.append(f'{indent}  <figcaption>{alt}</figcaption>')
        lines.append(f'{indent}</figure>')

        return "\n".join(lines)

    def render_vector(self, vec: VectorBlock, indent: str = "      ") -> str:
        """Render a VectorBlock as an inline SVG graphic."""
        if not vec.svg_path:
            return ""

        bw = max(1.0, vec.bbox.width)
        bh = max(1.0, vec.bbox.height)
        bx0 = vec.bbox.x0
        by0 = vec.bbox.y0

        f_hex = f"#{color_to_hex(vec.fill_color).lower()}" if vec.fill_color else "none"
        s_hex = (
            f"#{color_to_hex(vec.stroke_color).lower()}"
            if (vec.stroke_color and vec.stroke_width > 0)
            else "none"
        )
        sw = (
            f"{vec.stroke_width:.2f}"
            if (vec.stroke_color and vec.stroke_width > 0)
            else "0"
        )

        return (
            f'{indent}<div class="flow-vector">\n'
            f'{indent}  <svg viewBox="{bx0:.1f} {by0:.1f} {bw:.1f} {bh:.1f}" '
            f'width="{bw:.1f}pt" height="{bh:.1f}pt">\n'
            f'{indent}    <path d="{xml_escape(vec.svg_path)}" fill="{f_hex}" stroke="{s_hex}" stroke-width="{sw}"/>\n'
            f'{indent}  </svg>\n'
            f'{indent}</div>'
        )

    def _resolve_mime_type(self, img: ImageBlock) -> str:
        """Resolve MIME type from image bytes or format."""
        fmt = img.format.lower().strip() if img.format else ""
        if not fmt or fmt == "unknown":
            fmt = detect_image_format(img.image_bytes)

        mime_map = {
            "png": "image/png",
            "jpeg": "image/jpeg",
            "jpg": "image/jpeg",
            "webp": "image/webp",
            "gif": "image/gif",
            "bmp": "image/bmp",
            "svg": "image/svg+xml",
        }
        return mime_map.get(fmt, "image/png")


def render_flow_body(doc_ir: DocumentIR) -> str:
    """Convenience function to render DocumentIR into flow mode HTML body."""
    renderer = FlowHTMLRenderer()
    return renderer.render_body(doc_ir)


__all__ = [
    "FlowHTMLRenderer",
    "render_flow_body",
]
