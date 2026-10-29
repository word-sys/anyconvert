"""Pure-Python SVG vector graphics emitter.

Renders DocumentIR pages into standalone, scalable, W3C-compliant SVG documents:
- Translates VectorBlock paths with fill, stroke, dash patterns, and line caps/joins.
- Embeds raster images (JPEG, PNG, WebP) as base64 data URIs (<image>).
- Renders text runs with font styling, sizes, weights, and colors (<text>, <tspan>).
- Renders structured tables and cell borders.
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
from anyconvert.exceptions import SerializationError
from anyconvert.ir.model import (
    BlockNode,
    DocumentIR,
    DocumentPage,
    ImageBlock,
    Paragraph,
    Table,
    TextRun,
    VectorBlock,
)


class SvgEmitter(BaseEmitter):
    """Pure-Python SVG emitter converting document pages into standalone vector graphics."""

    def emit(
        self,
        doc_ir: DocumentIR,
        mode: ConversionMode = ConversionMode.FLOW,
    ) -> bytes:
        """Serialize a DocumentIR container into SVG format bytes.

        If doc_ir contains a single page, a single <svg> document matching that page is returned.
        If doc_ir contains multiple pages, all pages are stacked vertically in a single master SVG.

        Args:
            doc_ir: Validated DocumentIR hierarchy.
            mode: Layout conversion mode (informational; SVG preserves vector geometry).

        Returns:
            Raw bytes of the emitted SVG document encoded in UTF-8.
        """
        if not doc_ir.pages:
            raise SerializationError("Cannot emit SVG from empty DocumentIR")

        if len(doc_ir.pages) == 1:
            svg_text = self.render_page(doc_ir.pages[0])
            return svg_text.encode("utf-8")

        # Multi-page layout: stack pages vertically with a small gap
        gap = 20.0
        max_w = max(p.width for p in doc_ir.pages)
        total_h = sum(p.height for p in doc_ir.pages) + gap * (len(doc_ir.pages) - 1)

        lines: List[str] = [
            '<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="{max_w:.1f}pt" height="{total_h:.1f}pt" viewBox="0 0 {max_w:.1f} {total_h:.1f}" version="1.1">',
            '  <defs>',
            '    <style type="text/css">',
            '      text { font-family: sans-serif; }',
            '    </style>',
            '  </defs>',
        ]

        curr_y = 0.0
        for idx, page in enumerate(doc_ir.pages):
            page_num = idx + 1
            lines.append(f'  <g id="page_{page_num}" transform="translate(0, {curr_y:.1f})">')
            lines.append(f'    <rect width="{page.width:.1f}" height="{page.height:.1f}" fill="#ffffff"/>')
            lines.append(self._render_page_content(page, indent="    "))
            lines.append('  </g>')
            curr_y += page.height + gap

        lines.append('</svg>')
        return "\n".join(lines).encode("utf-8")

    def emit_page(self, page: DocumentPage) -> bytes:
        """Serialize a single DocumentPage directly into SVG bytes."""
        return self.render_page(page).encode("utf-8")

    def render_page(self, page: DocumentPage) -> str:
        """Render a single DocumentPage into a standalone SVG document string."""
        content = self._render_page_content(page, indent="  ")
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="{page.width:.1f}pt" height="{page.height:.1f}pt" '
            f'viewBox="0 0 {page.width:.1f} {page.height:.1f}" version="1.1">\n'
            '  <defs>\n'
            '    <style type="text/css">\n'
            '      text { font-family: sans-serif; }\n'
            '    </style>\n'
            '  </defs>\n'
            f'  <rect width="{page.width:.1f}" height="{page.height:.1f}" fill="#ffffff"/>\n'
            f'{content}\n'
            '</svg>'
        )

    def _render_page_content(self, page: DocumentPage, indent: str = "  ") -> str:
        """Render all blocks on a page into SVG element markup."""
        elements: List[str] = []

        # Marginal header
        if page.header:
            for p in page.header.content:
                elements.append(self._render_paragraph(p, indent))

        # Page body blocks
        for block in page.blocks:
            if isinstance(block, VectorBlock):
                v_xml = self._render_vector(block, indent)
                if v_xml:
                    elements.append(v_xml)
            elif isinstance(block, Paragraph):
                elements.append(self._render_paragraph(block, indent))
            elif isinstance(block, ImageBlock):
                elements.append(self._render_image(block, indent))
            elif isinstance(block, Table):
                elements.append(self._render_table(block, indent))

        # Marginal footer
        if page.footer:
            for p in page.footer.content:
                elements.append(self._render_paragraph(p, indent))

        return "\n".join(elements)

    def _render_vector(self, vec: VectorBlock, indent: str) -> str:
        """Render a VectorBlock into an SVG <path> element."""
        if not vec.svg_path:
            return ""

        attrs: List[str] = [f'd="{xml_escape(vec.svg_path)}"']

        # Fill
        if vec.fill_color is not None:
            f_hex = color_to_hex(vec.fill_color)
            attrs.append(f'fill="#{f_hex.lower()}"')
            alpha = vec.fill_color.a * vec.fill_alpha
            if alpha < 1.0:
                attrs.append(f'fill-opacity="{alpha:.2f}"')
        else:
            attrs.append('fill="none"')

        if vec.fill_rule != "nonzero":
            attrs.append(f'fill-rule="{vec.fill_rule}"')

        # Stroke
        if vec.stroke_color is not None and vec.stroke_width > 0:
            s_hex = color_to_hex(vec.stroke_color)
            attrs.append(f'stroke="#{s_hex.lower()}"')
            attrs.append(f'stroke-width="{vec.stroke_width:.2f}"')
            s_alpha = vec.stroke_color.a * vec.stroke_alpha
            if s_alpha < 1.0:
                attrs.append(f'stroke-opacity="{s_alpha:.2f}"')

            # Cap
            cap_map = {0: "butt", 1: "round", 2: "square"}
            cap_val = cap_map.get(vec.line_cap, "butt")
            if cap_val != "butt":
                attrs.append(f'stroke-linecap="{cap_val}"')

            # Join
            join_map = {0: "miter", 1: "round", 2: "bevel"}
            join_val = join_map.get(vec.line_join, "miter")
            if join_val != "miter":
                attrs.append(f'stroke-linejoin="{join_val}"')
            elif vec.miter_limit != 4.0:
                attrs.append(f'stroke-miterlimit="{vec.miter_limit:.1f}"')

            # Dash
            if vec.dash_array:
                dashes = " ".join(f"{d:.2f}" for d in vec.dash_array)
                attrs.append(f'stroke-dasharray="{dashes}"')
                if vec.dash_phase:
                    attrs.append(f'stroke-dashoffset="{vec.dash_phase:.2f}"')
        else:
            attrs.append('stroke="none"')

        return f'{indent}<path {" ".join(attrs)}/>'

    def _render_paragraph(self, p: Paragraph, indent: str) -> str:
        """Render a Paragraph into SVG <text> with <tspan> runs."""
        if not p.runs:
            return ""

        x0 = p.bbox.x0 if p.bbox is not None else 72.0
        y0 = p.bbox.y0 if p.bbox is not None else 72.0
        max_font_sz = max((r.font_size for r in p.runs), default=11.0)
        baseline_y = y0 + max_font_sz

        tspans: List[str] = []
        for r in p.runs:
            t_attrs: List[str] = []
            font_family = r.font_name or "sans-serif"
            t_attrs.append(f'font-family="{xml_escape(font_family)}"')
            t_attrs.append(f'font-size="{r.font_size:.1f}pt"')

            hex_c = color_to_hex(r.color)
            t_attrs.append(f'fill="#{hex_c.lower()}"')
            if r.color.a < 1.0:
                t_attrs.append(f'fill-opacity="{r.color.a:.2f}"')

            if r.is_bold:
                t_attrs.append('font-weight="bold"')
            if r.is_italic:
                t_attrs.append('font-style="italic"')
            if r.is_underline:
                t_attrs.append('text-decoration="underline"')

            tspans.append(f'<tspan {" ".join(t_attrs)}>{xml_escape(r.text)}</tspan>')

        content = "".join(tspans)
        return f'{indent}<text x="{x0:.1f}" y="{baseline_y:.1f}">{content}</text>'

    def _render_image(self, img: ImageBlock, indent: str) -> str:
        """Render an ImageBlock into an embedded base64 SVG <image> element."""
        if not img.image_bytes:
            return ""

        b64_data = base64.b64encode(img.image_bytes).decode("ascii")
        mime = img.mime_type
        x = img.bbox.x0
        y = img.bbox.y0
        w = img.bbox.width
        h = img.bbox.height

        return (
            f'{indent}<image x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'href="data:{mime};base64,{b64_data}"/>'
        )

    def _render_table(self, table: Table, indent: str) -> str:
        """Render a Table into SVG rectangles, borders, and cell text."""
        lines: List[str] = []
        if table.bbox is None:
            return ""

        curr_y = table.bbox.y0
        for row in table.rows:
            curr_x = table.bbox.x0
            for c_idx, cell in enumerate(row.cells):
                col_w = table.col_widths[c_idx] if c_idx < len(table.col_widths) else cell.width
                # Cell background
                if cell.background_color is not None:
                    bg_hex = color_to_hex(cell.background_color)
                    lines.append(
                        f'{indent}<rect x="{curr_x:.1f}" y="{curr_y:.1f}" '
                        f'width="{col_w:.1f}" height="{row.height:.1f}" '
                        f'fill="#{bg_hex.lower()}"/>'
                    )

                # Cell borders
                if cell.borders:
                    for side, border in cell.borders.items():
                        b_hex = color_to_hex(border.color)
                        bw = border.width
                        if side == "top":
                            lines.append(
                                f'{indent}<line x1="{curr_x:.1f}" y1="{curr_y:.1f}" '
                                f'x2="{curr_x + col_w:.1f}" y2="{curr_y:.1f}" '
                                f'stroke="#{b_hex.lower()}" stroke-width="{bw:.1f}"/>'
                            )
                        elif side == "bottom":
                            lines.append(
                                f'{indent}<line x1="{curr_x:.1f}" y1="{curr_y + row.height:.1f}" '
                                f'x2="{curr_x + col_w:.1f}" y2="{curr_y + row.height:.1f}" '
                                f'stroke="#{b_hex.lower()}" stroke-width="{bw:.1f}"/>'
                            )
                        elif side == "left":
                            lines.append(
                                f'{indent}<line x1="{curr_x:.1f}" y1="{curr_y:.1f}" '
                                f'x2="{curr_x:.1f}" y2="{curr_y + row.height:.1f}" '
                                f'stroke="#{b_hex.lower()}" stroke-width="{bw:.1f}"/>'
                            )
                        elif side == "right":
                            lines.append(
                                f'{indent}<line x1="{curr_x + col_w:.1f}" y1="{curr_y:.1f}" '
                                f'x2="{curr_x + col_w:.1f}" y2="{curr_y + row.height:.1f}" '
                                f'stroke="#{b_hex.lower()}" stroke-width="{bw:.1f}"/>'
                            )

                # Cell content
                for p in cell.content:
                    if isinstance(p, Paragraph):
                        lines.append(self._render_paragraph(p, indent))

                curr_x += col_w
            curr_y += row.height

        return "\n".join(lines)


__all__ = ["SvgEmitter"]
