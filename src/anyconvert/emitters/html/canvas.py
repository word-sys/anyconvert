"""Pixel-Accurate Canvas Mode HTML5 Generation Module.

Generates 1:1 visually matching HTML5 document layouts from DocumentIR,
using coordinate-positioned elements (position: absolute; left: ...pt; top: ...pt),
SVG vector layer, and embedded Base64 raster imagery.
"""

from __future__ import annotations

import base64
import math
from typing import List, Optional, Sequence

from anyconvert.common.color import Color
from anyconvert.emitters.base import color_to_hex, xml_escape
from anyconvert.ir.model import (
    BlockNode,
    DocumentIR,
    DocumentPage,
    ImageBlock,
    Paragraph,
    Table,
    TableCell,
    TableRow,
    TextRun,
    VectorBlock,
    detect_image_format,
)


class CanvasHTMLRenderer:
    """Renderer for pixel-accurate, coordinate-positioned HTML5 documents."""

    def __init__(self, indent_step: str = "  ") -> None:
        self.indent_step = indent_step

    def render_body(self, doc_ir: DocumentIR) -> str:
        """Render the complete body content of a DocumentIR hierarchy in canvas mode.

        Args:
            doc_ir: Document intermediate representation.

        Returns:
            HTML string containing the <div class="canvas-wrapper"> block.
        """
        lines: List[str] = ['  <div class="canvas-wrapper">']

        for page_idx, page in enumerate(doc_ir.pages):
            page_num = page_idx + 1
            lines.append(self.render_page(page, page_num=page_num, indent="    "))

        lines.append('  </div>')
        return "\n".join(lines)

    def render_page(
        self,
        page: DocumentPage,
        page_num: int = 1,
        indent: str = "    ",
    ) -> str:
        """Render a single DocumentPage as an absolute-positioned canvas page."""
        lines: List[str] = [
            f'{indent}<div id="page-{page_num}" class="canvas-page" '
            f'style="width: {page.width:.1f}pt; height: {page.height:.1f}pt;">'
        ]

        # 1. Vector graphics layer (rendered as background)
        vector_blocks = [b for b in page.blocks if isinstance(b, VectorBlock)]
        if vector_blocks:
            v_layer = self.render_vector_layer(
                vector_blocks,
                width=page.width,
                height=page.height,
                indent=f"{indent}  ",
            )
            if v_layer:
                lines.append(v_layer)

        # 2. Raster images
        for block in page.blocks:
            if isinstance(block, ImageBlock):
                lines.append(self.render_image(block, indent=f"{indent}  "))

        # 3. Tables (structured layout grids)
        for block in page.blocks:
            if isinstance(block, Table):
                lines.append(self.render_table(block, indent=f"{indent}  "))

        # 4. Text paragraphs (headers, body text, footers)
        if page.header and page.header.content:
            for p in page.header.content:
                lines.append(self.render_paragraph(p, indent=f"{indent}  "))

        for block in page.blocks:
            if isinstance(block, Paragraph):
                lines.append(self.render_paragraph(block, indent=f"{indent}  "))

        if page.footer and page.footer.content:
            for p in page.footer.content:
                lines.append(self.render_paragraph(p, indent=f"{indent}  "))

        lines.append(f'{indent}</div>')
        return "\n".join(lines)

    def render_vector_layer(
        self,
        vectors: Sequence[VectorBlock],
        width: float,
        height: float,
        indent: str = "      ",
    ) -> str:
        """Render vector paths inside a unified SVG layer covering the page."""
        paths: List[str] = []
        for vb in vectors:
            path_str = self.render_vector_path(vb, indent=f"{indent}  ")
            if path_str:
                paths.append(path_str)

        if not paths:
            return ""

        lines: List[str] = [
            f'{indent}<svg class="canvas-vector" viewBox="0 0 {width:.1f} {height:.1f}" '
            f'width="{width:.1f}pt" height="{height:.1f}pt">',
            *paths,
            f'{indent}</svg>',
        ]
        return "\n".join(lines)

    def render_vector_path(self, vec: VectorBlock, indent: str = "        ") -> str:
        """Render a single VectorBlock into an SVG <path> with full styling attributes."""
        if not vec.svg_path:
            return ""

        attrs: List[str] = [f'd="{xml_escape(vec.svg_path)}"']

        # Fill styling
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

        # Stroke styling
        if vec.stroke_color is not None and vec.stroke_width > 0:
            s_hex = color_to_hex(vec.stroke_color)
            attrs.append(f'stroke="#{s_hex.lower()}"')
            attrs.append(f'stroke-width="{vec.stroke_width:.2f}"')
            s_alpha = vec.stroke_color.a * vec.stroke_alpha
            if s_alpha < 1.0:
                attrs.append(f'stroke-opacity="{s_alpha:.2f}"')

            cap_map = {0: "butt", 1: "round", 2: "square"}
            cap_val = cap_map.get(vec.line_cap, "butt")
            if cap_val != "butt":
                attrs.append(f'stroke-linecap="{cap_val}"')

            join_map = {0: "miter", 1: "round", 2: "bevel"}
            join_val = join_map.get(vec.line_join, "miter")
            if join_val != "miter":
                attrs.append(f'stroke-linejoin="{join_val}"')
            elif vec.miter_limit != 4.0:
                attrs.append(f'stroke-miterlimit="{vec.miter_limit:.1f}"')

            if vec.dash_array:
                dashes = " ".join(f"{d:.2f}" for d in vec.dash_array)
                attrs.append(f'stroke-dasharray="{dashes}"')
                if vec.dash_phase:
                    attrs.append(f'stroke-dashoffset="{vec.dash_phase:.2f}"')
        else:
            attrs.append('stroke="none"')

        return f'{indent}<path {" ".join(attrs)}/>'

    def render_image(self, img: ImageBlock, indent: str = "      ") -> str:
        """Render an ImageBlock as an absolute-positioned <img> with Base64 Data URI."""
        if not img.image_bytes:
            return ""

        mime = self._resolve_mime_type(img)
        b64 = base64.b64encode(img.image_bytes).decode("ascii")
        alt = xml_escape(img.alt_text)

        styles: List[str] = [
            f"left: {img.bbox.x0:.1f}pt;",
            f"top: {img.bbox.y0:.1f}pt;",
            f"width: {img.bbox.width:.1f}pt;",
            f"height: {img.bbox.height:.1f}pt;",
        ]

        if img.rotation != 0.0:
            rad = math.radians(img.rotation)
            cos_a = math.cos(rad)
            sin_a = math.sin(rad)
            styles.append(
                f"transform: matrix({cos_a:.4f}, {sin_a:.4f}, {-sin_a:.4f}, {cos_a:.4f}, 0, 0);"
            )
            styles.append("transform-origin: 0 0;")

        style_str = " ".join(styles)
        return (
            f'{indent}<img class="canvas-element canvas-image" style="{style_str}" '
            f'src="data:{mime};base64,{b64}" alt="{alt}"/>'
        )

    def render_paragraph(self, p: Paragraph, indent: str = "      ") -> str:
        """Render a Paragraph into an absolute-positioned <div> with styled text spans."""
        if not p.runs:
            return ""

        x0 = p.bbox.x0 if p.bbox is not None else 72.0
        y0 = p.bbox.y0 if p.bbox is not None else 72.0
        max_font_sz = max((r.font_size for r in p.runs), default=11.0)

        styles: List[str] = [
            f"left: {x0:.1f}pt;",
            f"top: {y0:.1f}pt;",
            f"font-size: {max_font_sz:.1f}pt;",
        ]
        if p.bbox is not None and p.bbox.width > 0:
            styles.append(f"width: {p.bbox.width:.1f}pt;")

        runs_html = "".join(self.render_run(r) for r in p.runs)
        style_str = " ".join(styles)

        return f'{indent}<div class="canvas-element canvas-text" style="{style_str}">{runs_html}</div>'

    def render_run(self, r: TextRun) -> str:
        """Render an individual TextRun into an inline styled <span>."""
        text = xml_escape(r.text)
        if not text:
            return ""

        styles: List[str] = []

        if r.font_name:
            fn = xml_escape(r.font_name)
            styles.append(f"font-family: '{fn}', sans-serif;")

        styles.append(f"font-size: {r.font_size:.1f}pt;")

        if r.color:
            hex_c = color_to_hex(r.color).lower()
            styles.append(f"color: #{hex_c};")
            if r.color.a < 1.0:
                styles.append(f"opacity: {r.color.a:.2f};")

        if r.is_bold:
            styles.append("font-weight: bold;")
        if r.is_italic:
            styles.append("font-style: italic;")
        if r.is_underline:
            styles.append("text-decoration: underline;")
        if r.is_strikethrough:
            styles.append("text-decoration: line-through;")

        if r.tracking != 0.0:
            styles.append(f"letter-spacing: {r.tracking:.2f}pt;")

        if r.baseline_offset > 0.5:
            styles.append(f"vertical-align: {r.baseline_offset:.1f}pt;")
        elif r.baseline_offset < -0.5:
            styles.append(f"vertical-align: {r.baseline_offset:.1f}pt;")

        style_attr = f' style="{" ".join(styles)}"' if styles else ""
        return f"<span{style_attr}>{text}</span>"

    def render_table(self, tbl: Table, indent: str = "      ") -> str:
        """Render a Table into absolute-positioned coordinate grid with cell borders."""
        if tbl.bbox is None:
            return ""

        styles: List[str] = [
            f"left: {tbl.bbox.x0:.1f}pt;",
            f"top: {tbl.bbox.y0:.1f}pt;",
            f"width: {tbl.bbox.width:.1f}pt;",
            f"height: {tbl.bbox.height:.1f}pt;",
            "border-collapse: collapse;",
        ]

        lines: List[str] = [
            f'{indent}<table class="canvas-element canvas-table" style="{" ".join(styles)}">'
        ]

        for row in tbl.rows:
            lines.append(f'{indent}  <tr>')
            for cell in row.cells:
                c_styles: List[str] = []
                if cell.width > 0:
                    c_styles.append(f"width: {cell.width:.1f}pt;")
                if cell.height > 0:
                    c_styles.append(f"height: {cell.height:.1f}pt;")
                if cell.background_color is not None:
                    bg_hex = color_to_hex(cell.background_color).lower()
                    c_styles.append(f"background-color: #{bg_hex};")

                for side, border in cell.borders.items():
                    b_hex = color_to_hex(border.color).lower()
                    c_styles.append(f"border-{side}: {border.width:.1f}pt {border.style} #{b_hex};")

                attrs: List[str] = []
                if cell.col_span > 1:
                    attrs.append(f'colspan="{cell.col_span}"')
                if cell.row_span > 1:
                    attrs.append(f'rowspan="{cell.row_span}"')
                if c_styles:
                    attrs.append(f'style="{" ".join(c_styles)}"')

                attr_str = f" {' '.join(attrs)}" if attrs else ""
                tag = "th" if row.is_header else "td"

                content_parts: List[str] = []
                for b in cell.content:
                    if isinstance(b, Paragraph):
                        content_parts.append("".join(self.render_run(r) for r in b.runs))

                cell_content = "".join(content_parts)
                lines.append(f'{indent}    <{tag}{attr_str}>{cell_content}</{tag}>')
            lines.append(f'{indent}  </tr>')

        lines.append(f'{indent}</table>')
        return "\n".join(lines)

    def _resolve_mime_type(self, img: ImageBlock) -> str:
        """Resolve image MIME type from image bytes or format."""
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


def render_canvas_body(doc_ir: DocumentIR) -> str:
    """Convenience function to render DocumentIR into canvas mode HTML body."""
    renderer = CanvasHTMLRenderer()
    return renderer.render_body(doc_ir)


__all__ = [
    "CanvasHTMLRenderer",
    "render_canvas_body",
]
