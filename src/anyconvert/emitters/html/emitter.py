"""Modular HTML5 document emitter architecture.

Converts DocumentIR into modern, semantic, zero-dependency HTML5 documents supporting
both reflowable responsive documents (FLOW mode) and pixel-accurate fixed layouts (CANVAS mode).
"""

from __future__ import annotations

import base64
from typing import List, Optional

from anyconvert.common.color import Color
from anyconvert.emitters.base import (
    BaseEmitter,
    ConversionMode,
    color_to_hex,
    xml_escape,
)
from anyconvert.emitters.html.css import build_default_css
from anyconvert.emitters.html.flow import render_flow_body
from anyconvert.exceptions import SerializationError
from anyconvert.ir.model import (
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


class HTMLEmitter(BaseEmitter):
    """Pure-Python HTML5 emitter supporting semantic flow and visual canvas layout modes."""

    def emit(
        self,
        doc_ir: DocumentIR,
        mode: ConversionMode = ConversionMode.FLOW,
    ) -> bytes:
        """Serialize a DocumentIR container into an HTML5 document encoded in UTF-8.

        Args:
            doc_ir: Validated DocumentIR object hierarchy.
            mode: Conversion layout mode (FLOW or CANVAS).

        Returns:
            Raw bytes of the emitted standalone HTML document.

        Raises:
            SerializationError: If doc_ir contains no pages.
        """
        html_str = self.render_html(doc_ir, mode=mode)
        return html_str.encode("utf-8")

    def emit_page(
        self,
        page: DocumentPage,
        mode: ConversionMode = ConversionMode.FLOW,
        title: str = "",
    ) -> bytes:
        """Serialize a single DocumentPage into standalone HTML5 bytes."""
        doc_ir = DocumentIR(pages=[page])
        return self.emit(doc_ir, mode=mode)

    def render_html(
        self,
        doc_ir: DocumentIR,
        mode: ConversionMode = ConversionMode.FLOW,
        title: str = "",
    ) -> str:
        """Render a DocumentIR hierarchy into a standalone HTML5 string.

        Args:
            doc_ir: Validated DocumentIR hierarchy.
            mode: Conversion mode (FLOW or CANVAS).
            title: Optional document title.

        Returns:
            Complete HTML5 document string.
        """
        if not doc_ir.pages:
            raise SerializationError("Cannot emit HTML from empty DocumentIR")

        doc_title = title or doc_ir.metadata.get("Title", "Document")
        escaped_title = xml_escape(doc_title)
        css = build_default_css(mode=mode)

        if mode == ConversionMode.CANVAS:
            body_content = self._render_canvas_body(doc_ir)
        else:
            body_content = self._render_flow_body(doc_ir)

        return (
            '<!DOCTYPE html>\n'
            '<html lang="en">\n'
            '<head>\n'
            '  <meta charset="UTF-8">\n'
            '  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
            f'  <title>{escaped_title}</title>\n'
            '  <style type="text/css">\n'
            f'{css}\n'
            '  </style>\n'
            '</head>\n'
            '<body>\n'
            f'{body_content}\n'
            '</body>\n'
            '</html>'
        )

    def _render_flow_body(self, doc_ir: DocumentIR) -> str:
        """Render DocumentIR in semantic FLOW mode."""
        return render_flow_body(doc_ir)

    def _render_canvas_body(self, doc_ir: DocumentIR) -> str:
        """Render DocumentIR in pixel-accurate CANVAS mode."""
        lines: List[str] = ['  <div class="canvas-wrapper">']

        for page_idx, page in enumerate(doc_ir.pages):
            page_num = page_idx + 1
            lines.append(
                f'    <div id="page-{page_num}" class="canvas-page" '
                f'style="width: {page.width:.1f}pt; height: {page.height:.1f}pt;">'
            )

            # Vector layer (rendered first as background graphics)
            vector_blocks = [b for b in page.blocks if isinstance(b, VectorBlock)]
            if vector_blocks:
                lines.append(
                    f'      <svg class="canvas-vector" viewBox="0 0 {page.width:.1f} {page.height:.1f}" '
                    f'width="{page.width:.1f}pt" height="{page.height:.1f}pt">'
                )
                for vb in vector_blocks:
                    lines.append(self._render_vector_canvas(vb, indent="        "))
                lines.append('      </svg>')

            # Images
            for block in page.blocks:
                if isinstance(block, ImageBlock):
                    lines.append(self._render_image_canvas(block, indent="      "))

            # Text paragraphs
            for block in page.blocks:
                if isinstance(block, Paragraph):
                    lines.append(self._render_paragraph_canvas(block, indent="      "))

            lines.append('    </div>')

        lines.append('  </div>')
        return "\n".join(lines)

    # --------------------------------------------------------------------------
    # Flow Mode Element Renderers
    # --------------------------------------------------------------------------

    def _render_paragraph_flow(self, p: Paragraph, indent: str = "      ") -> str:
        """Render a Paragraph into semantic HTML5 (<p> or <h1-h6>)."""
        tag_map = {
            HeadingLevel.H1: "h1",
            HeadingLevel.H2: "h2",
            HeadingLevel.H3: "h3",
            HeadingLevel.H4: "h4",
            HeadingLevel.H5: "h5",
            HeadingLevel.H6: "h6",
        }
        tag = tag_map.get(p.heading_level, "p") if p.heading_level is not None else "p"
        runs_html = "".join(self._render_run_html(r) for r in p.runs)
        return f"{indent}<{tag}>{runs_html}</{tag}>"

    def _render_run_html(self, r: TextRun) -> str:
        """Render a TextRun into formatted inline HTML text."""
        text = xml_escape(r.text)
        if r.is_bold:
            text = f"<strong>{text}</strong>"
        if r.is_italic:
            text = f"<em>{text}</em>"
        if r.is_underline:
            text = f"<u>{text}</u>"
        if r.is_strikethrough:
            text = f"<s>{text}</s>"
        return text

    def _render_image_flow(self, img: ImageBlock, indent: str = "      ") -> str:
        """Render an ImageBlock as an inline Base64 Data URI <img>."""
        if not img.image_bytes:
            return ""
        b64 = base64.b64encode(img.image_bytes).decode("ascii")
        alt = xml_escape(img.alt_text)
        return f'{indent}<img src="data:{img.mime_type};base64,{b64}" alt="{alt}"/>'

    def _render_vector_flow(self, vec: VectorBlock, indent: str = "      ") -> str:
        """Render a VectorBlock as an inline SVG graphic in Flow mode."""
        if not vec.svg_path:
            return ""
        bw = max(1.0, vec.bbox.width)
        bh = max(1.0, vec.bbox.height)
        bx0 = vec.bbox.x0
        by0 = vec.bbox.y0

        f_hex = f"#{color_to_hex(vec.fill_color).lower()}" if vec.fill_color else "none"
        s_hex = f"#{color_to_hex(vec.stroke_color).lower()}" if (vec.stroke_color and vec.stroke_width > 0) else "none"
        sw = f"{vec.stroke_width:.2f}" if (vec.stroke_color and vec.stroke_width > 0) else "0"

        return (
            f'{indent}<svg viewBox="{bx0:.1f} {by0:.1f} {bw:.1f} {bh:.1f}" '
            f'width="{bw:.1f}pt" height="{bh:.1f}pt">\n'
            f'{indent}  <path d="{xml_escape(vec.svg_path)}" fill="{f_hex}" stroke="{s_hex}" stroke-width="{sw}"/>\n'
            f'{indent}</svg>'
        )

    def _render_table_flow(self, tbl: Table, indent: str = "      ") -> str:
        """Render a Table into a semantic <table class="pure-table">."""
        lines: List[str] = [f'{indent}<table class="pure-table">']
        for row in tbl.rows:
            lines.append(f'{indent}  <tr>')
            for cell in row.cells:
                tag = "th" if row.is_header else "td"
                span_attrs = ""
                if cell.col_span > 1:
                    span_attrs += f' colspan="{cell.col_span}"'
                if cell.row_span > 1:
                    span_attrs += f' rowspan="{cell.row_span}"'
                cell_html = "".join(
                    self._render_paragraph_flow(p, indent="").strip()
                    for p in cell.content
                    if isinstance(p, Paragraph)
                )
                lines.append(f'{indent}    <{tag}{span_attrs}>{cell_html}</{tag}>')
            lines.append(f'{indent}  </tr>')
        lines.append(f'{indent}</table>')
        return "\n".join(lines)

    # --------------------------------------------------------------------------
    # Canvas Mode Element Renderers
    # --------------------------------------------------------------------------

    def _render_paragraph_canvas(self, p: Paragraph, indent: str = "      ") -> str:
        """Render an absolute-positioned paragraph block for Canvas mode."""
        if not p.runs:
            return ""
        x0 = p.bbox.x0 if p.bbox is not None else 0.0
        y0 = p.bbox.y0 if p.bbox is not None else 0.0
        runs_html = "".join(self._render_run_html(r) for r in p.runs)
        max_font_sz = max((r.font_size for r in p.runs), default=11.0)

        style = (
            f"left: {x0:.1f}pt; top: {y0:.1f}pt; font-size: {max_font_sz:.1f}pt;"
        )
        return f'{indent}<div class="canvas-element canvas-text" style="{style}">{runs_html}</div>'

    def _render_image_canvas(self, img: ImageBlock, indent: str = "      ") -> str:
        """Render an absolute-positioned image block for Canvas mode."""
        if not img.image_bytes:
            return ""
        b64 = base64.b64encode(img.image_bytes).decode("ascii")
        alt = xml_escape(img.alt_text)
        style = (
            f"left: {img.bbox.x0:.1f}pt; top: {img.bbox.y0:.1f}pt; "
            f"width: {img.bbox.width:.1f}pt; height: {img.bbox.height:.1f}pt;"
        )
        return (
            f'{indent}<img class="canvas-element canvas-image" style="{style}" '
            f'src="data:{img.mime_type};base64,{b64}" alt="{alt}"/>'
        )

    def _render_vector_canvas(self, vec: VectorBlock, indent: str = "        ") -> str:
        """Render a path element for the canvas SVG background layer."""
        if not vec.svg_path:
            return ""
        f_hex = f"#{color_to_hex(vec.fill_color).lower()}" if vec.fill_color else "none"
        s_hex = f"#{color_to_hex(vec.stroke_color).lower()}" if (vec.stroke_color and vec.stroke_width > 0) else "none"
        sw = f"{vec.stroke_width:.2f}" if (vec.stroke_color and vec.stroke_width > 0) else "0"
        return f'{indent}<path d="{xml_escape(vec.svg_path)}" fill="{f_hex}" stroke="{s_hex}" stroke-width="{sw}"/>'


__all__ = ["HTMLEmitter"]
