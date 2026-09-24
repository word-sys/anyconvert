"""Pure-Python OASIS OpenDocument Text (ODT) emitter conforming to ISO/IEC 26300."""

from __future__ import annotations

import datetime
from typing import Dict, List, Optional, Set, Tuple
import xml.etree.ElementTree as ET

from anyconvert.common.color import Color
from anyconvert.common.geometry import BoundingBox
from anyconvert.emitters.base import (
    BaseEmitter,
    ConversionMode,
    color_to_hex,
    xml_escape,
)
from anyconvert.exceptions import SerializationError
from anyconvert.ir.model import (
    Alignment,
    BlockNode,
    DocumentIR,
    DocumentPage,
    HeadingLevel,
    ImageBlock,
    PageHeaderFooter,
    Paragraph,
    Table,
    TableCell,
    TableRow,
    TextRun,
    VectorBlock,
)
from anyconvert.packaging.odf import (
    MEDIA_TYPE_IMAGE_PNG,
    MEDIA_TYPE_TEXT_XML,
    MIMETYPE_ODT,
    ODFPackage,
)


_ALIGN_MAP: Dict[Alignment, str] = {
    Alignment.LEFT: "left",
    Alignment.CENTER: "center",
    Alignment.RIGHT: "right",
    Alignment.JUSTIFIED: "justify",
}


def _color_to_odf(color: Color) -> str:
    """Format Color as an ODF #RRGGBB hex string."""
    return f"#{color_to_hex(color)}"


class OdtEmitter(BaseEmitter):
    """Pure-Python ODT (OpenDocument Text) emitter supporting Flow and Canvas modes."""

    def emit(
        self,
        doc_ir: DocumentIR,
        mode: ConversionMode = ConversionMode.FLOW,
    ) -> bytes:
        """Serialize a DocumentIR structure into an ISO/IEC 26300 compliant ODT package.

        Args:
            doc_ir: Validated DocumentIR instance.
            mode: ConversionMode.FLOW or ConversionMode.CANVAS.

        Returns:
            Raw bytes of the emitted .odt ZIP archive.
        """
        if not doc_ir.pages:
            raise SerializationError("Cannot emit ODT from empty DocumentIR")

        pkg = ODFPackage(mimetype=MIMETYPE_ODT)

        first_page = doc_ir.pages[0]

        # 1. Build content.xml and collect embedded images
        content_xml = self._build_content_xml(doc_ir=doc_ir, pkg=pkg, mode=mode)
        pkg.add_part("content.xml", content_xml, media_type=MEDIA_TYPE_TEXT_XML)

        # 2. Build styles.xml (page layouts, header/footer)
        styles_xml = self._build_styles_xml(first_page=first_page, mode=mode)
        pkg.add_part("styles.xml", styles_xml, media_type=MEDIA_TYPE_TEXT_XML)

        # 3. Build meta.xml
        meta_xml = self._build_meta_xml(metadata=doc_ir.metadata)
        pkg.add_part("meta.xml", meta_xml, media_type=MEDIA_TYPE_TEXT_XML)

        return pkg.to_bytes()

    def _build_content_xml(
        self,
        doc_ir: DocumentIR,
        pkg: ODFPackage,
        mode: ConversionMode,
    ) -> bytes:
        """Generate content.xml with automatic styles and body content."""
        auto_styles: List[str] = []
        body_elements: List[str] = []

        # Style registries to deduplicate automatic styles
        p_style_map: Dict[Tuple[str, str, str, str, str, str], str] = {}
        t_style_map: Dict[Tuple[str, float, str, bool, bool, bool, bool], str] = {}
        col_style_map: Dict[float, str] = {}
        cell_style_map: Dict[Tuple[Optional[str], str], str] = {}
        used_fonts: Set[str] = set()

        # Default graphic frame style (transparent background, no borders, no padding)
        auto_styles.append(
            '  <style:style style:name="Frame_Default" style:family="graphic">\n'
            '    <style:graphic-properties style:wrap="none" style:vertical-pos="from-top" style:vertical-rel="page" '
            'style:horizontal-pos="from-left" style:horizontal-rel="page" draw:fill="none" draw:stroke="none" fo:padding="0pt" fo:margin="0pt"/>\n'
            '  </style:style>'
        )

        if mode == ConversionMode.CANVAS:
            auto_styles.append(
                '  <style:style style:name="P_Canvas" style:family="paragraph">\n'
                '    <style:paragraph-properties fo:margin="0pt" fo:padding="0pt" fo:line-height="0%" fo:font-size="0pt"/>\n'
                '  </style:style>'
            )

        image_counter = [1]

        total_pages = len(doc_ir.pages)
        for page_idx, page in enumerate(doc_ir.pages):
            page_num = page_idx + 1

            if mode == ConversionMode.CANVAS:
                page_draw_elements: List[str] = []
                for block in page.blocks:
                    b_xml = self._render_block(
                        block=block,
                        pkg=pkg,
                        auto_styles=auto_styles,
                        p_style_map=p_style_map,
                        t_style_map=t_style_map,
                        col_style_map=col_style_map,
                        cell_style_map=cell_style_map,
                        image_counter=image_counter,
                        page_num=page_num,
                        page_width=page.width,
                        page_height=page.height,
                        used_fonts=used_fonts,
                        mode=mode,
                    )
                    if b_xml:
                        page_draw_elements.append(b_xml)
                body_elements.append(
                    '      <text:p text:style-name="P_Canvas">\n'
                    + "\n".join(page_draw_elements)
                    + "\n      </text:p>"
                )
            else:
                for block in page.blocks:
                    b_xml = self._render_block(
                        block=block,
                        pkg=pkg,
                        auto_styles=auto_styles,
                        p_style_map=p_style_map,
                        t_style_map=t_style_map,
                        col_style_map=col_style_map,
                        cell_style_map=cell_style_map,
                        image_counter=image_counter,
                        page_num=page_num,
                        page_width=page.width,
                        page_height=page.height,
                        used_fonts=used_fonts,
                        mode=mode,
                    )
                    if b_xml:
                        body_elements.append(b_xml)

            # Page break between pages (except last)
            if page_idx < total_pages - 1:
                pb_style = "P_PageBreak"
                if pb_style not in [s.split('"')[1] for s in auto_styles]:
                    auto_styles.append(
                        f'  <style:style style:name="{pb_style}" style:family="paragraph">\n'
                        '    <style:paragraph-properties fo:break-after="page"/>\n'
                        '  </style:style>'
                    )
                body_elements.append(f'      <text:p text:style-name="{pb_style}"/>')

        xml_lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"',
            '                         xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"',
            '                         xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"',
            '                         xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"',
            '                         xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"',
            '                         xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"',
            '                         xmlns:xlink="http://www.w3.org/1999/xlink"',
            '                         xmlns:dc="http://purl.org/dc/elements/1.1/"',
            '                         xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0"',
            '                         xmlns:number="urn:oasis:names:tc:opendocument:xmlns:datastyle:1.0"',
            '                         xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0"',
            '                         office:version="1.3">',
        ]
        if used_fonts:
            xml_lines.append('  <office:font-face-decls>')
            for f in sorted(used_fonts):
                xml_lines.append(f'    <style:font-face style:name="{xml_escape(f)}" svg:font-family="{xml_escape(f)}"/>')
            xml_lines.append('  </office:font-face-decls>')
        xml_lines.extend([
            '  <office:automatic-styles>',
            "\n".join(auto_styles),
            '  </office:automatic-styles>',
            '  <office:body>',
            '    <office:text>',
            "\n".join(body_elements),
            '    </office:text>',
            '  </office:body>',
            '</office:document-content>',
        ])
        return "\n".join(xml_lines).encode("utf-8")

    def _render_block(
        self,
        block: BlockNode,
        pkg: ODFPackage,
        auto_styles: List[str],
        p_style_map: Dict[Tuple[str, str, str, str, str, str], str],
        t_style_map: Dict[Tuple[str, float, str, bool, bool, bool, bool], str],
        col_style_map: Dict[float, str],
        cell_style_map: Dict[Tuple[Optional[str], str], str],
        image_counter: List[int],
        page_num: int,
        page_width: float,
        page_height: float,
        used_fonts: Set[str],
        mode: ConversionMode,
    ) -> str:
        """Render a BlockNode to ODF XML string."""
        if isinstance(block, Paragraph):
            return self._render_paragraph(
                p=block,
                auto_styles=auto_styles,
                p_style_map=p_style_map,
                t_style_map=t_style_map,
                used_fonts=used_fonts,
                page_num=page_num,
                mode=mode,
            )
        elif isinstance(block, Table):
            return self._render_table(
                table=block,
                auto_styles=auto_styles,
                p_style_map=p_style_map,
                t_style_map=t_style_map,
                col_style_map=col_style_map,
                cell_style_map=cell_style_map,
                used_fonts=used_fonts,
                page_num=page_num,
            )
        elif isinstance(block, ImageBlock):
            return self._render_image(
                img=block,
                pkg=pkg,
                image_counter=image_counter,
                page_num=page_num,
                mode=mode,
            )
        elif isinstance(block, VectorBlock):
            return self._render_vector(
                vec=block,
                auto_styles=auto_styles,
                page_num=page_num,
                page_width=page_width,
                page_height=page_height,
            )
        return ""

    def _render_paragraph(
        self,
        p: Paragraph,
        auto_styles: List[str],
        p_style_map: Dict[Tuple[str, str, str, str, str, str], str],
        t_style_map: Dict[Tuple[str, float, str, bool, bool, bool, bool], str],
        used_fonts: Set[str],
        page_num: int,
        mode: ConversionMode,
    ) -> str:
        """Render a DIR Paragraph to <text:p> or <text:h>."""
        align_str = _ALIGN_MAP.get(p.alignment, "left")
        sp_before = f"{p.space_before:.1f}pt"
        sp_after = f"{p.space_after:.1f}pt"
        ind_l = f"{p.indent_left:.1f}pt"
        ind_r = f"{p.indent_right:.1f}pt"
        ind_f = f"{p.indent_first_line:.1f}pt"

        style_key = (align_str, sp_before, sp_after, ind_l, ind_r, ind_f)
        if style_key not in p_style_map:
            p_style_name = f"P{len(p_style_map) + 1}"
            p_style_map[style_key] = p_style_name

            props = [
                f'fo:text-align="{align_str}"',
                f'fo:margin-top="{sp_before}"',
                f'fo:margin-bottom="{sp_after}"',
                f'fo:margin-left="{ind_l}"',
                f'fo:margin-right="{ind_r}"',
                f'fo:text-indent="{ind_f}"',
            ]
            if p.line_spacing > 0:
                props.append(f'fo:line-height="{int(round(p.line_spacing * 100))}%"')

            auto_styles.append(
                f'  <style:style style:name="{p_style_name}" style:family="paragraph">\n'
                f'    <style:paragraph-properties {" ".join(props)}/>\n'
                f'  </style:style>'
            )
        else:
            p_style_name = p_style_map[style_key]

        runs_xml: List[str] = []
        for r in p.runs:
            runs_xml.append(self._render_run(r, auto_styles, t_style_map, used_fonts))

        content_str = "".join(runs_xml)

        if p.heading_level:
            level_num = p.heading_level.value
            elem_xml = f'      <text:h text:outline-level="{level_num}" text:style-name="{p_style_name}">{content_str}</text:h>'
        elif p.list_marker:
            elem_xml = (
                f'      <text:list>\n'
                f'        <text:list-item>\n'
                f'          <text:p text:style-name="{p_style_name}">{content_str}</text:p>\n'
                f'        </text:list-item>\n'
                f'      </text:list>'
            )
        else:
            elem_xml = f'      <text:p text:style-name="{p_style_name}">{content_str}</text:p>'

        if mode == ConversionMode.CANVAS and p.bbox is not None:
            x_pt = f"{p.bbox.x0:.1f}pt"
            y_pt = f"{p.bbox.y0:.1f}pt"
            w_pt = f"{p.bbox.width + 24.0:.1f}pt"
            h_pt = f"{p.bbox.height:.1f}pt"
            return (
                f'        <draw:frame draw:style-name="Frame_Default" svg:x="{x_pt}" svg:y="{y_pt}" '
                f'svg:width="{w_pt}" svg:height="{h_pt}" text:anchor-type="page" text:anchor-page-num="{page_num}">\n'
                f'          <draw:text-box>\n'
                f'    {elem_xml}\n'
                f'          </draw:text-box>\n'
                f'        </draw:frame>'
            )

        return elem_xml

    def _render_run(
        self,
        run: TextRun,
        auto_styles: List[str],
        t_style_map: Dict[Tuple[str, float, str, bool, bool, bool, bool], str],
        used_fonts: Set[str],
    ) -> str:
        """Render a TextRun to <text:span>."""
        font = run.font_name or "Helvetica"
        used_fonts.add(font)
        hex_c = _color_to_odf(run.color)
        t_key = (
            font,
            round(run.font_size, 1),
            hex_c,
            run.is_bold,
            run.is_italic,
            run.is_underline,
            run.is_strikethrough,
        )

        if t_key not in t_style_map:
            t_style_name = f"T{len(t_style_map) + 1}"
            t_style_map[t_key] = t_style_name

            props = [
                f'style:font-name="{xml_escape(font)}"',
                f'fo:font-family="{xml_escape(font)}"',
                f'fo:font-size="{run.font_size:.1f}pt"',
                f'fo:color="{hex_c}"',
            ]
            if run.is_bold:
                props.append('fo:font-weight="bold"')
            if run.is_italic:
                props.append('fo:font-style="italic"')
            if run.is_underline:
                props.append('style:text-underline-style="solid"')
            if run.is_strikethrough:
                props.append('style:text-line-through-style="solid"')

            auto_styles.append(
                f'  <style:style style:name="{t_style_name}" style:family="text">\n'
                f'    <style:text-properties {" ".join(props)}/>\n'
                f'  </style:style>'
            )
        else:
            t_style_name = t_style_map[t_key]

        escaped_txt = xml_escape(run.text)
        return f'<text:span text:style-name="{t_style_name}">{escaped_txt}</text:span>'

    def _render_table(
        self,
        table: Table,
        auto_styles: List[str],
        p_style_map: Dict[Tuple[str, str, str, str, str, str], str],
        t_style_map: Dict[Tuple[str, float, str, bool, bool, bool, bool], str],
        col_style_map: Dict[float, str],
        cell_style_map: Dict[Tuple[Optional[str], str], str],
        used_fonts: Set[str],
        page_num: int,
    ) -> str:
        """Render a Table into <table:table> with column styles, headers, and cells."""
        tbl_name = f"Table_{id(table)}"
        lines = [
            f'      <table:table table:name="{tbl_name}">',
        ]

        # Register column width styles
        for w in table.col_widths:
            w_rounded = round(w, 1)
            if w_rounded not in col_style_map:
                col_sname = f"Col_{len(col_style_map) + 1}"
                col_style_map[w_rounded] = col_sname
                auto_styles.append(
                    f'  <style:style style:name="{col_sname}" style:family="table-column">\n'
                    f'    <style:table-column-properties style:column-width="{w_rounded:.1f}pt"/>\n'
                    f'  </style:style>'
                )
            else:
                col_sname = col_style_map[w_rounded]

            lines.append(f'        <table:table-column table:style-name="{col_sname}"/>')

        # Table rows
        for row in table.rows:
            is_hdr = row.is_header
            if is_hdr:
                lines.append('        <table:table-header-rows>')
            lines.append('        <table:table-row>')

            for cell in row.cells:
                bg_hex = _color_to_odf(cell.background_color) if cell.background_color else None
                border_str = "0.5pt solid #000000" if cell.borders else "none"

                cell_key = (bg_hex, border_str)
                if cell_key not in cell_style_map:
                    cell_sname = f"Cell_{len(cell_style_map) + 1}"
                    cell_style_map[cell_key] = cell_sname

                    c_props: List[str] = [f'fo:border="{border_str}"']
                    if bg_hex:
                        c_props.append(f'fo:background-color="{bg_hex}"')
                    auto_styles.append(
                        f'  <style:style style:name="{cell_sname}" style:family="table-cell">\n'
                        f'    <style:table-cell-properties {" ".join(c_props)}/>\n'
                        f'  </style:style>'
                    )
                else:
                    cell_sname = cell_style_map[cell_key]

                span_attrs: List[str] = []
                if cell.col_span > 1:
                    span_attrs.append(f'table:number-columns-spanned="{cell.col_span}"')
                if cell.row_span > 1:
                    span_attrs.append(f'table:number-rows-spanned="{cell.row_span}"')

                span_str = (" " + " ".join(span_attrs)) if span_attrs else ""
                lines.append(f'          <table:table-cell office:value-type="string" table:style-name="{cell_sname}"{span_str}>')

                if not cell.content:
                    lines.append('            <text:p/>')
                else:
                    for b in cell.content:
                        if isinstance(b, Paragraph):
                            lines.append(
                                self._render_paragraph(
                                    b,
                                    auto_styles=auto_styles,
                                    p_style_map=p_style_map,
                                    t_style_map=t_style_map,
                                    used_fonts=used_fonts,
                                    page_num=page_num,
                                    mode=ConversionMode.FLOW,
                                )
                            )

                lines.append('          </table:table-cell>')

                # Emit covered cells for col_span
                if cell.col_span > 1:
                    for _ in range(cell.col_span - 1):
                        lines.append('          <table:covered-table-cell/>')

            lines.append('        </table:table-row>')
            if is_hdr:
                lines.append('        </table:table-header-rows>')

        lines.append('      </table:table>')
        return "\n".join(lines)

    def _render_image(
        self,
        img: ImageBlock,
        pkg: ODFPackage,
        image_counter: List[int],
        page_num: int,
        mode: ConversionMode,
    ) -> str:
        """Embed raster image and render <draw:frame>."""
        idx = image_counter[0]
        image_counter[0] += 1

        part_name = f"Pictures/image{idx}.png"
        pkg.add_part(part_name, img.png_bytes, media_type=MEDIA_TYPE_IMAGE_PNG)

        alt_text = xml_escape(img.alt_text or f"Image_{idx}")
        w_pt = f"{img.bbox.width:.1f}pt"
        h_pt = f"{img.bbox.height:.1f}pt"

        if mode == ConversionMode.CANVAS:
            x_pt = f"{img.bbox.x0:.1f}pt"
            y_pt = f"{img.bbox.y0:.1f}pt"
            return (
                f'        <draw:frame draw:name="{alt_text}" draw:style-name="Frame_Default" '
                f'svg:x="{x_pt}" svg:y="{y_pt}" svg:width="{w_pt}" svg:height="{h_pt}" '
                f'text:anchor-type="page" text:anchor-page-num="{page_num}">\n'
                f'          <draw:image xlink:href="{part_name}" xlink:type="simple" xlink:show="embed" xlink:actuate="onLoad"/>\n'
                f'        </draw:frame>'
            )
        else:
            return (
                f'      <text:p>\n'
                f'        <draw:frame draw:name="{alt_text}" draw:style-name="Frame_Default" '
                f'svg:width="{w_pt}" svg:height="{h_pt}" text:anchor-type="paragraph">\n'
                f'          <draw:image xlink:href="{part_name}" xlink:type="simple" xlink:show="embed" xlink:actuate="onLoad"/>\n'
                f'        </draw:frame>\n'
                f'      </text:p>'
            )

    def _render_vector(
        self,
        vec: VectorBlock,
        auto_styles: List[str],
        page_num: int,
        page_width: float,
        page_height: float,
    ) -> str:
        """Render a VectorBlock to ODF <draw:path>."""
        if not vec.svg_path:
            return ""

        v_style_name = f"V{len(auto_styles) + 1}"
        props: List[str] = [
            'style:wrap="none"',
            'style:vertical-pos="from-top"',
            'style:vertical-rel="page"',
            'style:horizontal-pos="from-left"',
            'style:horizontal-rel="page"',
        ]

        if vec.stroke_color is not None and vec.stroke_width > 0:
            stroke_hex = _color_to_odf(vec.stroke_color)
            props.append(f'svg:stroke-color="{stroke_hex}"')
            props.append(f'svg:stroke-width="{vec.stroke_width:.2f}pt"')
            if vec.stroke_color.a < 1.0:
                props.append(f'svg:stroke-opacity="{vec.stroke_color.a:.2f}"')
        else:
            props.append('draw:stroke="none"')

        if vec.fill_color is not None:
            fill_hex = _color_to_odf(vec.fill_color)
            props.append('draw:fill="solid"')
            props.append(f'draw:fill-color="{fill_hex}"')
            if vec.fill_color.a < 1.0:
                props.append(f'draw:opacity="{vec.fill_color.a:.2f}"')
        else:
            props.append('draw:fill="none"')

        auto_styles.append(
            f'  <style:style style:name="{v_style_name}" style:family="graphic">\n'
            f'    <style:graphic-properties {" ".join(props)}/>\n'
            f'  </style:style>'
        )

        escaped_d = xml_escape(vec.svg_path)
        sw = max(0.5, vec.stroke_width)
        bx0 = vec.bbox.x0
        by0 = vec.bbox.y0
        bw = max(sw, vec.bbox.width)
        bh = max(sw, vec.bbox.height)

        return (
            f'        <draw:path draw:style-name="{v_style_name}" svg:d="{escaped_d}" '
            f'svg:x="{bx0:.1f}pt" svg:y="{by0:.1f}pt" svg:width="{bw:.1f}pt" svg:height="{bh:.1f}pt" '
            f'svg:viewBox="{bx0:.1f} {by0:.1f} {bw:.1f} {bh:.1f}" '
            f'text:anchor-type="page" text:anchor-page-num="{page_num}"/>'
        )

    def _build_styles_xml(
        self,
        first_page: DocumentPage,
        mode: ConversionMode = ConversionMode.FLOW,
    ) -> bytes:
        """Generate styles.xml declaring page layout, margins, and headers/footers."""
        w_pt = f"{first_page.width:.1f}pt"
        h_pt = f"{first_page.height:.1f}pt"
        if mode == ConversionMode.CANVAS:
            m_t = "0pt"
            m_b = "0pt"
            m_l = "0pt"
            m_r = "0pt"
        else:
            m_t = f"{first_page.margin_top:.1f}pt"
            m_b = f"{first_page.margin_bottom:.1f}pt"
            m_l = f"{first_page.margin_left:.1f}pt"
            m_r = f"{first_page.margin_right:.1f}pt"

        header_xml = ""
        if first_page.header and first_page.header.content:
            hdr_text = xml_escape(first_page.header.content[0].text)
            header_xml = (
                f'    <style:header>\n'
                f'      <text:p text:style-name="Header">{hdr_text}</text:p>\n'
                f'    </style:header>'
            )

        footer_xml = ""
        if first_page.footer and first_page.footer.content:
            ftr_text = xml_escape(first_page.footer.content[0].text)
            footer_xml = (
                f'    <style:footer>\n'
                f'      <text:p text:style-name="Footer">{ftr_text}</text:p>\n'
                f'    </style:footer>'
            )

        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-styles xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
                        xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
                        xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
                        xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"
                        xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
                        xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"
                        xmlns:xlink="http://www.w3.org/1999/xlink"
                        xmlns:dc="http://purl.org/dc/elements/1.1/"
                        xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0"
                        xmlns:number="urn:oasis:names:tc:opendocument:xmlns:datastyle:1.0"
                        xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0"
                        office:version="1.3">
  <office:styles>
    <style:style style:name="Standard" style:family="paragraph" style:class="text"/>
    <style:style style:name="Heading" style:family="paragraph" style:parent-style-name="Standard" style:next-style-name="Standard">
      <style:text-properties fo:font-weight="bold"/>
    </style:style>
    <style:style style:name="Header" style:family="paragraph" style:parent-style-name="Standard">
      <style:text-properties fo:font-size="9pt" fo:color="#7F7F7F"/>
    </style:style>
    <style:style style:name="Footer" style:family="paragraph" style:parent-style-name="Standard">
      <style:text-properties fo:font-size="9pt" fo:color="#7F7F7F"/>
    </style:style>
  </office:styles>
  <office:automatic-styles>
    <style:page-layout style:name="PM1">
      <style:page-layout-properties fo:page-width="{w_pt}" fo:page-height="{h_pt}"
                                    fo:margin-top="{m_t}" fo:margin-bottom="{m_b}"
                                    fo:margin-left="{m_l}" fo:margin-right="{m_r}"/>
      <style:header-style>
        <style:header-footer-properties fo:min-height="36pt"/>
      </style:header-style>
      <style:footer-style>
        <style:header-footer-properties fo:min-height="36pt"/>
      </style:footer-style>
    </style:page-layout>
  </office:automatic-styles>
  <office:master-styles>
    <style:master-page style:name="Standard" style:page-layout-name="PM1">
{header_xml}
{footer_xml}
    </style:master-page>
  </office:master-styles>
</office:document-styles>"""
        return xml.strip().encode("utf-8")

    @staticmethod
    def _build_meta_xml(metadata: Dict[str, str]) -> bytes:
        """Generate meta.xml containing document metadata."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        title = xml_escape(metadata.get("Title", ""))
        author = xml_escape(metadata.get("Author", "anyconvert"))
        subject = xml_escape(metadata.get("Subject", ""))

        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-meta xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
                      xmlns:dc="http://purl.org/dc/elements/1.1/"
                      xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0"
                      office:version="1.3">
  <office:meta>
    <meta:generator>anyconvert</meta:generator>
    <dc:title>{title}</dc:title>
    <dc:creator>{author}</dc:creator>
    <dc:subject>{subject}</dc:subject>
    <dc:date>{now_iso}</dc:date>
  </office:meta>
</office:document-meta>"""
        return xml.strip().encode("utf-8")


__all__ = ["OdtEmitter"]
