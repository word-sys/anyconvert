"""Pure-Python OASIS OpenDocument Presentation (ODP) emitter conforming to ISO/IEC 26300."""

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
    MIMETYPE_ODP,
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


class OdpEmitter(BaseEmitter):
    """Pure-Python ODP (OpenDocument Presentation) emitter mapping pages to slides."""

    def emit(
        self,
        doc_ir: DocumentIR,
        mode: ConversionMode = ConversionMode.FLOW,
    ) -> bytes:
        """Serialize a DocumentIR structure into an ISO/IEC 26300 compliant ODP package.

        Args:
            doc_ir: Validated DocumentIR instance.
            mode: ConversionMode (shapes are positioned by spatial geometry).

        Returns:
            Raw bytes of the emitted .odp ZIP archive.
        """
        if not doc_ir.pages:
            raise SerializationError("Cannot emit ODP from empty DocumentIR")

        pkg = ODFPackage(mimetype=MIMETYPE_ODP)

        first_page = doc_ir.pages[0]

        # 1. Build content.xml with presentation slides
        content_xml = self._build_content_xml(doc_ir=doc_ir, pkg=pkg)
        pkg.add_part("content.xml", content_xml, media_type=MEDIA_TYPE_TEXT_XML)

        # 2. Build styles.xml (slide dimensions)
        styles_xml = self._build_styles_xml(first_page=first_page)
        pkg.add_part("styles.xml", styles_xml, media_type=MEDIA_TYPE_TEXT_XML)

        # 3. Build meta.xml
        meta_xml = self._build_meta_xml(metadata=doc_ir.metadata)
        pkg.add_part("meta.xml", meta_xml, media_type=MEDIA_TYPE_TEXT_XML)

        return pkg.to_bytes()

    def _build_content_xml(
        self,
        doc_ir: DocumentIR,
        pkg: ODFPackage,
    ) -> bytes:
        """Generate content.xml with automatic styles and presentation slides."""
        auto_styles: List[str] = []
        slide_elements: List[str] = []

        # Default drawing page style and graphic style
        auto_styles.append('  <style:style style:name="dp1" style:family="drawing-page"/>')
        auto_styles.append(
            '  <style:style style:name="gr1" style:family="graphic">\n'
            '    <style:graphic-properties draw:fill="none" draw:stroke="none"/>\n'
            '  </style:style>'
        )

        p_style_map: Dict[Tuple[str, str, str], str] = {}
        t_style_map: Dict[Tuple[str, float, str, bool, bool, bool, bool], str] = {}
        col_style_map: Dict[float, str] = {}
        cell_style_map: Dict[Tuple[Optional[str], str], str] = {}
        image_counter = [1]

        for page_idx, page in enumerate(doc_ir.pages):
            page_num = page_idx + 1
            shapes_xml: List[str] = []

            # If header/footer present, add as text shapes
            if page.header:
                for p in page.header.content:
                    shapes_xml.append(
                        self._render_paragraph_shape(
                            p=p,
                            auto_styles=auto_styles,
                            p_style_map=p_style_map,
                            t_style_map=t_style_map,
                        )
                    )

            for block in page.blocks:
                if isinstance(block, Paragraph):
                    shapes_xml.append(
                        self._render_paragraph_shape(
                            p=block,
                            auto_styles=auto_styles,
                            p_style_map=p_style_map,
                            t_style_map=t_style_map,
                        )
                    )
                elif isinstance(block, Table):
                    shapes_xml.append(
                        self._render_table_shape(
                            table=block,
                            auto_styles=auto_styles,
                            p_style_map=p_style_map,
                            t_style_map=t_style_map,
                            col_style_map=col_style_map,
                            cell_style_map=cell_style_map,
                        )
                    )
                elif isinstance(block, ImageBlock):
                    shapes_xml.append(
                        self._render_image_shape(
                            img=block,
                            pkg=pkg,
                            image_counter=image_counter,
                        )
                    )

            if page.footer:
                for p in page.footer.content:
                    shapes_xml.append(
                        self._render_paragraph_shape(
                            p=p,
                            auto_styles=auto_styles,
                            p_style_map=p_style_map,
                            t_style_map=t_style_map,
                        )
                    )

            slide_elements.append(
                f'      <draw:page draw:name="page{page_num}" draw:style-name="dp1" draw:master-page-name="Default">\n'
                + "\n".join(shapes_xml)
                + "\n      </draw:page>"
            )

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
            '                         xmlns:presentation="urn:oasis:names:tc:opendocument:xmlns:presentation:1.0"',
            '                         office:version="1.3">',
            '  <office:automatic-styles>',
            "\n".join(auto_styles),
            '  </office:automatic-styles>',
            '  <office:body>',
            '    <office:presentation>',
            "\n".join(slide_elements),
            '    </office:presentation>',
            '  </office:body>',
            '</office:document-content>',
        ]
        return "\n".join(xml_lines).encode("utf-8")

    def _render_paragraph_shape(
        self,
        p: Paragraph,
        auto_styles: List[str],
        p_style_map: Dict[Tuple[str, str, str], str],
        t_style_map: Dict[Tuple[str, float, str, bool, bool, bool, bool], str],
    ) -> str:
        """Render a Paragraph into a positioned text box frame."""
        bbox = p.bbox or BoundingBox(72, 72, 400, 100)
        x_pt = f"{bbox.x0:.1f}pt"
        y_pt = f"{bbox.y0:.1f}pt"
        w_pt = f"{bbox.width:.1f}pt"
        h_pt = f"{bbox.height:.1f}pt"

        align_str = _ALIGN_MAP.get(p.alignment, "left")
        sp_before = f"{p.space_before:.1f}pt"
        sp_after = f"{p.space_after:.1f}pt"

        style_key = (align_str, sp_before, sp_after)
        if style_key not in p_style_map:
            p_style_name = f"P{len(p_style_map) + 1}"
            p_style_map[style_key] = p_style_name
            auto_styles.append(
                f'  <style:style style:name="{p_style_name}" style:family="paragraph">\n'
                f'    <style:paragraph-properties fo:text-align="{align_str}" '
                f'fo:margin-top="{sp_before}" fo:margin-bottom="{sp_after}"/>\n'
                f'  </style:style>'
            )
        else:
            p_style_name = p_style_map[style_key]

        runs_xml: List[str] = []
        for r in p.runs:
            runs_xml.append(self._render_run(r, auto_styles, t_style_map))

        content_str = "".join(runs_xml)
        tb_id = f"TextBox_{id(p)}"

        return f"""        <draw:frame draw:name="{tb_id}" draw:style-name="gr1" svg:x="{x_pt}" svg:y="{y_pt}" svg:width="{w_pt}" svg:height="{h_pt}">
          <draw:text-box>
            <text:p text:style-name="{p_style_name}">{content_str}</text:p>
          </draw:text-box>
        </draw:frame>"""

    def _render_run(
        self,
        run: TextRun,
        auto_styles: List[str],
        t_style_map: Dict[Tuple[str, float, str, bool, bool, bool, bool], str],
    ) -> str:
        """Render a TextRun to <text:span>."""
        font = run.font_name or "Helvetica"
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

    def _render_image_shape(
        self,
        img: ImageBlock,
        pkg: ODFPackage,
        image_counter: List[int],
    ) -> str:
        """Embed raster image and render Presentation picture frame."""
        idx = image_counter[0]
        image_counter[0] += 1

        part_name = f"Pictures/image{idx}.png"
        pkg.add_part(part_name, img.png_bytes, media_type=MEDIA_TYPE_IMAGE_PNG)

        alt_text = xml_escape(img.alt_text or f"Picture_{idx}")
        x_pt = f"{img.bbox.x0:.1f}pt"
        y_pt = f"{img.bbox.y0:.1f}pt"
        w_pt = f"{img.bbox.width:.1f}pt"
        h_pt = f"{img.bbox.height:.1f}pt"

        return f"""        <draw:frame draw:name="{alt_text}" draw:style-name="gr1" svg:x="{x_pt}" svg:y="{y_pt}" svg:width="{w_pt}" svg:height="{h_pt}">
          <draw:image xlink:href="{part_name}" xlink:type="simple" xlink:show="embed" xlink:actuate="onLoad"/>
        </draw:frame>"""

    def _render_table_shape(
        self,
        table: Table,
        auto_styles: List[str],
        p_style_map: Dict[Tuple[str, str, str], str],
        t_style_map: Dict[Tuple[str, float, str, bool, bool, bool, bool], str],
        col_style_map: Dict[float, str],
        cell_style_map: Dict[Tuple[Optional[str], str], str],
    ) -> str:
        """Render a Table into a positioned frame containing a table."""
        bbox = table.bbox or BoundingBox(72, 100, 450, 200)
        x_pt = f"{bbox.x0:.1f}pt"
        y_pt = f"{bbox.y0:.1f}pt"
        w_pt = f"{bbox.width:.1f}pt"
        h_pt = f"{bbox.height:.1f}pt"

        tbl_name = f"Table_{id(table)}"
        lines = [
            f'        <draw:frame draw:name="{tbl_name}" draw:style-name="gr1" svg:x="{x_pt}" svg:y="{y_pt}" svg:width="{w_pt}" svg:height="{h_pt}">',
            f'          <table:table table:name="{tbl_name}">',
        ]

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

            lines.append(f'            <table:table-column table:style-name="{col_sname}"/>')

        for row in table.rows:
            lines.append('            <table:table-row>')
            for cell in row.cells:
                bg_hex = _color_to_odf(cell.background_color) if cell.background_color else None
                border_str = "0.5pt solid #000000" if cell.borders else "none"

                cell_key = (bg_hex, border_str)
                if cell_key not in cell_style_map:
                    cell_sname = f"Cell_{len(cell_style_map) + 1}"
                    cell_style_map[cell_key] = cell_sname
                    c_props = [f'fo:border="{border_str}"']
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

                lines.append(f'              <table:table-cell office:value-type="string" table:style-name="{cell_sname}"{span_str}>')

                if not cell.content:
                    lines.append('                <text:p/>')
                else:
                    for b in cell.content:
                        if isinstance(b, Paragraph):
                            runs_str = "".join(self._render_run(r, auto_styles, t_style_map) for r in b.runs)
                            lines.append(f'                <text:p>{runs_str}</text:p>')

                lines.append('              </table:table-cell>')
                if cell.col_span > 1:
                    for _ in range(cell.col_span - 1):
                        lines.append('              <table:covered-table-cell/>')

            lines.append('            </table:table-row>')

        lines.extend([
            '          </table:table>',
            '        </draw:frame>',
        ])
        return "\n".join(lines)

    def _build_styles_xml(self, first_page: DocumentPage) -> bytes:
        """Generate styles.xml declaring presentation slide dimensions."""
        w_pt = f"{first_page.width:.1f}pt"
        h_pt = f"{first_page.height:.1f}pt"

        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-styles xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
                        xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
                        xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
                        xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
                        xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"
                        xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0"
                        xmlns:presentation="urn:oasis:names:tc:opendocument:xmlns:presentation:1.0"
                        office:version="1.3">
  <office:styles>
    <style:style style:name="Standard" style:family="paragraph"/>
  </office:styles>
  <office:automatic-styles>
    <style:page-layout style:name="PM1">
      <style:page-layout-properties fo:page-width="{w_pt}" fo:page-height="{h_pt}"
                                    fo:margin-top="0pt" fo:margin-bottom="0pt"
                                    fo:margin-left="0pt" fo:margin-right="0pt"/>
    </style:page-layout>
  </office:automatic-styles>
  <office:master-styles>
    <style:master-page style:name="Default" style:page-layout-name="PM1"/>
  </office:master-styles>
</office:document-styles>"""
        return xml.strip().encode("utf-8")

    @staticmethod
    def _build_meta_xml(metadata: Dict[str, str]) -> bytes:
        """Generate meta.xml containing presentation metadata."""
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


__all__ = ["OdpEmitter"]
