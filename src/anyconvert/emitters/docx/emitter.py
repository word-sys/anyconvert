"""Pure-Python WordprocessingML (DOCX) emitter conforming to ISO/IEC 29500."""

from __future__ import annotations

import datetime
from typing import Dict, List, Optional, Set, Union
import zipfile

from anyconvert.common.color import Color
from anyconvert.common.geometry import BoundingBox
from anyconvert.emitters.base import (
    BaseEmitter,
    ConversionMode,
    color_to_hex,
    pt_to_dxa,
    pt_to_emu,
    pt_to_half_pt,
    xml_escape,
)
from anyconvert.emitters.docx.numbering import build_default_numbering_xml
from anyconvert.emitters.docx.styles import build_default_styles_xml
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
from anyconvert.packaging.opc import (
    CT_CORE_PROPERTIES,
    CT_EXTENDED_PROPERTIES,
    CT_PNG,
    CT_WORDPROCESSING_DOCUMENT,
    CT_WORDPROCESSING_FONTTABLE,
    CT_WORDPROCESSING_FOOTER,
    CT_WORDPROCESSING_HEADER,
    CT_WORDPROCESSING_NUMBERING,
    CT_WORDPROCESSING_SETTINGS,
    CT_WORDPROCESSING_STYLES,
    OPCPackage,
    RT_CORE_PROPERTIES,
    RT_EXTENDED_PROPERTIES,
    RT_FONTTABLE,
    RT_FOOTER,
    RT_HEADER,
    RT_IMAGE,
    RT_NUMBERING,
    RT_OFFICE_DOCUMENT,
    RT_SETTINGS,
    RT_STYLES,
)


_ALIGN_MAP: Dict[Alignment, str] = {
    Alignment.LEFT: "left",
    Alignment.CENTER: "center",
    Alignment.RIGHT: "right",
    Alignment.JUSTIFIED: "both",
}

_HEADING_STYLE_MAP: Dict[HeadingLevel, str] = {
    HeadingLevel.H1: "Heading1",
    HeadingLevel.H2: "Heading2",
    HeadingLevel.H3: "Heading3",
    HeadingLevel.H4: "Heading4",
    HeadingLevel.H5: "Heading5",
    HeadingLevel.H6: "Heading6",
}


class DocxEmitter(BaseEmitter):
    """Pure-Python DOCX (WordprocessingML) emitter supporting Flow and Canvas modes."""

    def emit(
        self,
        doc_ir: DocumentIR,
        mode: ConversionMode = ConversionMode.FLOW,
    ) -> bytes:
        """Serialize a DocumentIR structure into a valid DOCX ZIP container archive.

        Args:
            doc_ir: Validated DocumentIR instance.
            mode: ConversionMode.FLOW (reflowable) or ConversionMode.CANVAS (absolute positioning).

        Returns:
            Raw bytes of the emitted .docx file.
        """
        if not doc_ir.pages:
            raise SerializationError("Cannot emit DOCX from empty DocumentIR")

        pkg = OPCPackage()

        # 1. Package-level relationships
        pkg.add_package_relationship(RT_OFFICE_DOCUMENT, "word/document.xml")
        pkg.add_package_relationship(RT_CORE_PROPERTIES, "docProps/core.xml")
        pkg.add_package_relationship(RT_EXTENDED_PROPERTIES, "docProps/app.xml")

        # 2. Add static Word parts
        pkg.add_part(
            "word/styles.xml",
            build_default_styles_xml(),
            content_type=CT_WORDPROCESSING_STYLES,
        )
        pkg.add_part(
            "word/numbering.xml",
            build_default_numbering_xml(),
            content_type=CT_WORDPROCESSING_NUMBERING,
        )
        pkg.add_part(
            "word/settings.xml",
            self._build_settings_xml(),
            content_type=CT_WORDPROCESSING_SETTINGS,
        )

        # Track fonts used across document
        used_fonts: Set[str] = {"Calibri", "Arial"}
        image_counter = 1

        # 3. Document part relationships and content
        doc_rels: Dict[str, str] = {}  # target -> rel_id

        # Headers and footers
        header_rel_id: Optional[str] = None
        footer_rel_id: Optional[str] = None

        first_page = doc_ir.pages[0]
        if first_page.header and first_page.header.content:
            hdr_xml = self._build_header_footer_xml(first_page.header, is_footer=False, used_fonts=used_fonts)
            pkg.add_part("word/header1.xml", hdr_xml, content_type=CT_WORDPROCESSING_HEADER)
            header_rel_id = "rIdHdr"
            doc_rels["header1.xml"] = header_rel_id

        if first_page.footer and first_page.footer.content:
            ftr_xml = self._build_header_footer_xml(first_page.footer, is_footer=True, used_fonts=used_fonts)
            pkg.add_part("word/footer1.xml", ftr_xml, content_type=CT_WORDPROCESSING_FOOTER)
            footer_rel_id = "rIdFtr"
            doc_rels["footer1.xml"] = footer_rel_id

        # 4. Generate word/document.xml content
        body_xml_lines: List[str] = []

        total_pages = len(doc_ir.pages)
        for page_idx, page in enumerate(doc_ir.pages):
            # Page content blocks
            for block in page.blocks:
                b_xml = self._render_block(
                    block=block,
                    pkg=pkg,
                    doc_rels=doc_rels,
                    used_fonts=used_fonts,
                    image_counter_ref=[image_counter],
                    mode=mode,
                )
                if b_xml:
                    body_xml_lines.append(b_xml)
                image_counter = pkg_images_count(pkg) + 1

            # Insert page break between pages (except last)
            if page_idx < total_pages - 1:
                body_xml_lines.append(
                    '    <w:p><w:r><w:br w:type="page"/></w:r></w:p>'
                )

        # Section properties on last page (or overall document)
        pg_w = pt_to_dxa(first_page.width)
        pg_h = pt_to_dxa(first_page.height)
        m_top = pt_to_dxa(first_page.margin_top)
        m_bottom = pt_to_dxa(first_page.margin_bottom)
        m_left = pt_to_dxa(first_page.margin_left)
        m_right = pt_to_dxa(first_page.margin_right)

        sect_lines = [
            "    <w:sectPr>",
        ]
        if header_rel_id:
            sect_lines.append(f'      <w:headerReference w:type="default" r:id="{header_rel_id}"/>')
        if footer_rel_id:
            sect_lines.append(f'      <w:footerReference w:type="default" r:id="{footer_rel_id}"/>')

        sect_lines.extend([
            f'      <w:pgSz w:w="{pg_w}" w:h="{pg_h}"/>',
            f'      <w:pgMar w:top="{m_top}" w:right="{m_right}" w:bottom="{m_bottom}" '
            f'w:left="{m_left}" w:header="720" w:footer="720" w:gutter="0"/>',
            "    </w:sectPr>",
        ])
        body_xml_lines.extend(sect_lines)

        document_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"\n'
            '            xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"\n'
            '            xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"\n'
            '            xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"\n'
            '            xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"\n'
            '            xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">\n'
            "  <w:body>\n"
            + "\n".join(body_xml_lines)
            + "\n  </w:body>\n</w:document>"
        )

        doc_part = pkg.add_part(
            "word/document.xml",
            document_xml.encode("utf-8"),
            content_type=CT_WORDPROCESSING_DOCUMENT,
        )

        # Connect document relationships
        doc_part.add_relationship(RT_STYLES, "styles.xml")
        doc_part.add_relationship(RT_NUMBERING, "numbering.xml")
        doc_part.add_relationship(RT_SETTINGS, "settings.xml")
        doc_part.add_relationship(RT_FONTTABLE, "fontTable.xml")

        if header_rel_id:
            doc_part.add_relationship(RT_HEADER, "header1.xml", rel_id=header_rel_id)
        if footer_rel_id:
            doc_part.add_relationship(RT_FOOTER, "footer1.xml", rel_id=footer_rel_id)

        # Add image relationships
        for target, rel_id in doc_rels.items():
            if target.startswith("media/"):
                doc_part.add_relationship(RT_IMAGE, target, rel_id=rel_id)

        # 5. Add fontTable.xml
        pkg.add_part(
            "word/fontTable.xml",
            self._build_font_table_xml(used_fonts),
            content_type=CT_WORDPROCESSING_FONTTABLE,
        )

        # 6. Add docProps/core.xml & app.xml
        pkg.add_part(
            "docProps/core.xml",
            self._build_core_properties_xml(doc_ir.metadata),
            content_type=CT_CORE_PROPERTIES,
        )
        pkg.add_part(
            "docProps/app.xml",
            self._build_app_properties_xml(total_pages),
            content_type=CT_EXTENDED_PROPERTIES,
        )

        return pkg.to_bytes()

    def _render_block(
        self,
        block: BlockNode,
        pkg: OPCPackage,
        doc_rels: Dict[str, str],
        used_fonts: Set[str],
        image_counter_ref: List[int],
        mode: ConversionMode,
    ) -> str:
        """Render a single BlockNode to WordprocessingML XML string."""
        if isinstance(block, Paragraph):
            return self._render_paragraph(block, used_fonts=used_fonts, mode=mode)
        elif isinstance(block, Table):
            return self._render_table(block, used_fonts=used_fonts)
        elif isinstance(block, ImageBlock):
            return self._render_image(
                img=block,
                pkg=pkg,
                doc_rels=doc_rels,
                image_counter_ref=image_counter_ref,
                mode=mode,
            )
        elif isinstance(block, VectorBlock):
            # For vector shapes without rasterization, render container placeholder or path
            return ""
        return ""

    def _render_paragraph(
        self,
        p: Paragraph,
        used_fonts: Set[str],
        mode: ConversionMode,
    ) -> str:
        """Render a DIR Paragraph to <w:p>."""
        p_pr_elements: List[str] = []

        # 1. Heading style (sequence #1)
        if p.heading_level and p.heading_level in _HEADING_STYLE_MAP:
            style_name = _HEADING_STYLE_MAP[p.heading_level]
            p_pr_elements.append(f'      <w:pStyle w:val="{style_name}"/>')

        # 2. Canvas mode absolute frame placement (sequence #5)
        if mode == ConversionMode.CANVAS and p.bbox is not None:
            w_dxa = pt_to_dxa(p.bbox.width)
            h_dxa = pt_to_dxa(p.bbox.height)
            x_dxa = pt_to_dxa(p.bbox.x0)
            y_dxa = pt_to_dxa(p.bbox.y0)
            p_pr_elements.append(
                f'      <w:framePr w:w="{w_dxa}" w:h="{h_dxa}" w:hRule="atLeast" '
                f'w:x="{x_dxa}" w:y="{y_dxa}" w:hAnchor="page" w:vAnchor="page" w:wrap="none"/>'
            )

        # 3. Lists & bullets (sequence #7)
        if p.list_marker:
            num_id = 1 if p.list_marker in ("•", "o", "▪", "-", "*", "–", "—") else 2
            ilvl = max(0, min(8, p.list_level))
            p_pr_elements.append(
                f'      <w:numPr><w:ilvl w:val="{ilvl}"/><w:numId w:val="{num_id}"/></w:numPr>'
            )

        # 4. Spacing (sequence #21)
        sp_before = pt_to_dxa(p.space_before)
        sp_after = pt_to_dxa(p.space_after)
        line_val = int(round(240 * p.line_spacing)) if p.line_spacing > 0 else 240
        if sp_before > 0 or sp_after > 0 or line_val != 240:
            p_pr_elements.append(
                f'      <w:spacing w:before="{sp_before}" w:after="{sp_after}" '
                f'w:line="{line_val}" w:lineRule="auto"/>'
            )

        # 5. Indentation (sequence #22)
        ind_left = pt_to_dxa(p.indent_left)
        ind_right = pt_to_dxa(p.indent_right)
        ind_first = pt_to_dxa(p.indent_first_line)
        if ind_left > 0 or ind_right > 0 or ind_first != 0:
            ind_attrs: List[str] = []
            if ind_left > 0:
                ind_attrs.append(f'w:left="{ind_left}"')
            if ind_right > 0:
                ind_attrs.append(f'w:right="{ind_right}"')
            if ind_first > 0:
                ind_attrs.append(f'w:firstLine="{ind_first}"')
            elif ind_first < 0:
                ind_attrs.append(f'w:hanging="{-ind_first}"')
            p_pr_elements.append(f'      <w:ind {" ".join(ind_attrs)}/>')

        # 6. Alignment (sequence #26)
        jc_val = _ALIGN_MAP.get(p.alignment, "left")
        if jc_val != "left":
            p_pr_elements.append(f'      <w:jc w:val="{jc_val}"/>')

        runs_xml: List[str] = []
        for run in p.runs:
            runs_xml.append(self._render_run(run, used_fonts=used_fonts))

        p_pr_str = ""
        if p_pr_elements:
            p_pr_str = "    <w:pPr>\n" + "\n".join(p_pr_elements) + "\n    </w:pPr>\n"

        return f"    <w:p>\n{p_pr_str}" + "\n".join(runs_xml) + "\n    </w:p>"

    def _render_run(self, run: TextRun, used_fonts: Set[str]) -> str:
        """Render a TextRun to <w:r>."""
        r_pr_elements: List[str] = []

        font = run.font_name or "Calibri"
        used_fonts.add(font)
        r_pr_elements.append(
            f'        <w:rFonts w:ascii="{xml_escape(font)}" w:hAnsi="{xml_escape(font)}"/>'
        )

        if run.is_bold:
            r_pr_elements.append("        <w:b/>")
        if run.is_italic:
            r_pr_elements.append("        <w:i/>")
        if run.is_underline:
            r_pr_elements.append('        <w:u w:val="single"/>')
        if run.is_strikethrough:
            r_pr_elements.append("        <w:strike/>")

        # Color (skip default black)
        hex_c = color_to_hex(run.color)
        if hex_c != "000000":
            r_pr_elements.append(f'        <w:color w:val="{hex_c}"/>')

        # Font size (in half-points)
        sz_val = pt_to_half_pt(run.font_size)
        r_pr_elements.append(f'        <w:sz w:val="{sz_val}"/>')
        r_pr_elements.append(f'        <w:szCs w:val="{sz_val}"/>')

        r_pr_str = ""
        if r_pr_elements:
            r_pr_str = "      <w:rPr>\n" + "\n".join(r_pr_elements) + "\n      </w:rPr>\n"

        escaped_txt = xml_escape(run.text)
        return f"      <w:r>\n{r_pr_str}        <w:t xml:space=\"preserve\">{escaped_txt}</w:t>\n      </w:r>"

    def _render_table(self, table: Table, used_fonts: Set[str]) -> str:
        """Render a DIR Table to <w:tbl>."""
        lines = [
            "    <w:tbl>",
            "      <w:tblPr>",
            '        <w:tblStyle w:val="TableGrid"/>',
            '        <w:tblW w:w="0" w:type="auto"/>',
            f'        <w:jc w:val="{_ALIGN_MAP.get(table.alignment, "center")}"/>',
            "      </w:tblPr>",
            "      <w:tblGrid>",
        ]

        for w in table.col_widths:
            lines.append(f'        <w:gridCol w:w="{pt_to_dxa(w)}"/>')
        lines.append("      </w:tblGrid>")

        for row in table.rows:
            lines.append("      <w:tr>")
            r_pr: List[str] = []
            if row.height > 0:
                r_pr.append(f'        <w:trHeight w:val="{pt_to_dxa(row.height)}" w:hRule="atLeast"/>')
            if row.is_header:
                r_pr.append("        <w:tblHeader/>")
            if r_pr:
                lines.append("        <w:trPr>\n" + "\n".join(r_pr) + "\n        </w:trPr>")

            for cell in row.cells:
                lines.append("        <w:tc>")
                tc_pr: List[str] = [
                    f'          <w:tcW w:w="{pt_to_dxa(cell.width)}" w:type="dxa"/>'
                ]
                if cell.col_span > 1:
                    tc_pr.append(f'          <w:gridSpan w:val="{cell.col_span}"/>')
                if cell.row_span > 1:
                    tc_pr.append('          <w:vMerge w:val="restart"/>')

                if cell.background_color is not None:
                    c_hex = color_to_hex(cell.background_color)
                    tc_pr.append(f'          <w:shd w:val="clear" w:color="auto" w:fill="{c_hex}"/>')

                lines.append("          <w:tcPr>\n" + "\n".join(tc_pr) + "\n          </w:tcPr>")

                if not cell.content:
                    lines.append("          <w:p/>")
                else:
                    for b in cell.content:
                        if isinstance(b, Paragraph):
                            lines.append(self._render_paragraph(b, used_fonts=used_fonts, mode=ConversionMode.FLOW))
                        elif isinstance(b, Table):
                            lines.append(self._render_table(b, used_fonts=used_fonts))

                lines.append("        </w:tc>")
            lines.append("      </w:tr>")

        lines.append("    </w:tbl>")
        return "\n".join(lines)

    def _render_image(
        self,
        img: ImageBlock,
        pkg: OPCPackage,
        doc_rels: Dict[str, str],
        image_counter_ref: List[int],
        mode: ConversionMode,
    ) -> str:
        """Embed raster image and render DrawingML element."""
        img_num = image_counter_ref[0]
        image_counter_ref[0] += 1

        img_part_name = f"word/media/image{img_num}.png"
        rel_target = f"media/image{img_num}.png"

        pkg.add_part(img_part_name, img.png_bytes, content_type=CT_PNG)

        rel_id = f"rIdImg{img_num}"
        doc_rels[rel_target] = rel_id

        cx_emu = pt_to_emu(img.bbox.width)
        cy_emu = pt_to_emu(img.bbox.height)
        alt_str = xml_escape(img.alt_text or f"Picture {img_num}")

        if mode == ConversionMode.CANVAS:
            x_emu = pt_to_emu(img.bbox.x0)
            y_emu = pt_to_emu(img.bbox.y0)
            drawing_xml = f"""    <w:p>
      <w:r>
        <w:drawing>
          <wp:anchor distT="0" distB="0" distL="0" distR="0" simplePos="0" relativeHeight="251658240"
                     behindDoc="0" locked="0" layoutInCell="1" allowOverlap="1">
            <wp:simplePos x="0" y="0"/>
            <wp:positionH relativeFrom="page">
              <wp:posOffset>{x_emu}</wp:posOffset>
            </wp:positionH>
            <wp:positionV relativeFrom="page">
              <wp:posOffset>{y_emu}</wp:posOffset>
            </wp:positionV>
            <wp:extent cx="{cx_emu}" cy="{cy_emu}"/>
            <wp:effectExtent l="0" t="0" r="0" b="0"/>
            <wp:wrapNone/>
            <wp:docPr id="{img_num}" name="{alt_str}"/>
            <wp:cNvGraphicFramePr/>
            <a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
              <a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
                <pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">
                  <pic:nvPicPr>
                    <pic:cNvPr id="{img_num}" name="{alt_str}"/>
                    <pic:cNvPicPr/>
                  </pic:nvPicPr>
                  <pic:blipFill>
                    <a:blip r:embed="{rel_id}"/>
                    <a:stretch><a:fillRect/></a:stretch>
                  </pic:blipFill>
                  <pic:spPr>
                    <a:xfrm>
                      <a:off x="0" y="0"/>
                      <a:ext cx="{cx_emu}" cy="{cy_emu}"/>
                    </a:xfrm>
                    <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
                  </pic:spPr>
                </pic:pic>
              </a:graphicData>
            </a:graphic>
          </wp:anchor>
        </w:drawing>
      </w:r>
    </w:p>"""
        else:
            drawing_xml = f"""    <w:p>
      <w:r>
        <w:drawing>
          <wp:inline distT="0" distB="0" distL="0" distR="0">
            <wp:extent cx="{cx_emu}" cy="{cy_emu}"/>
            <wp:effectExtent l="0" t="0" r="0" b="0"/>
            <wp:docPr id="{img_num}" name="{alt_str}"/>
            <wp:cNvGraphicFramePr/>
            <a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
              <a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
                <pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">
                  <pic:nvPicPr>
                    <pic:cNvPr id="{img_num}" name="{alt_str}"/>
                    <pic:cNvPicPr/>
                  </pic:nvPicPr>
                  <pic:blipFill>
                    <a:blip r:embed="{rel_id}"/>
                    <a:stretch><a:fillRect/></a:stretch>
                  </pic:blipFill>
                  <pic:spPr>
                    <a:xfrm>
                      <a:off x="0" y="0"/>
                      <a:ext cx="{cx_emu}" cy="{cy_emu}"/>
                    </a:xfrm>
                    <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
                  </pic:spPr>
                </pic:pic>
              </a:graphicData>
            </a:graphic>
          </wp:inline>
        </w:drawing>
      </w:r>
    </w:p>"""

        return drawing_xml

    def _build_header_footer_xml(
        self,
        hf: PageHeaderFooter,
        is_footer: bool,
        used_fonts: Set[str],
    ) -> bytes:
        """Generate word/header1.xml or word/footer1.xml content."""
        root_tag = "w:ftr" if is_footer else "w:hdr"
        style_id = "Footer" if is_footer else "Header"

        p_lines: List[str] = []
        for p in hf.content:
            p_lines.append(
                f'  <w:p>\n    <w:pPr><w:pStyle w:val="{style_id}"/></w:pPr>\n'
                + "\n".join(self._render_run(r, used_fonts) for r in p.runs)
                + "\n  </w:p>"
            )

        if not p_lines:
            p_lines.append(f'  <w:p><w:pPr><w:pStyle w:val="{style_id}"/></w:pPr></w:p>')

        xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<{root_tag} xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"\n'
            '       xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">\n'
            + "\n".join(p_lines)
            + f"\n</{root_tag}>"
        )
        return xml.encode("utf-8")

    @staticmethod
    def _build_settings_xml() -> bytes:
        """Generate word/settings.xml content."""
        xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:defaultTabStop w:val="720"/>
  <w:characterSpacingControl w:val="doNotCompress"/>
  <w:compat>
    <w:compatSetting w:name="compatibilityMode" w:uri="http://schemas.microsoft.com/office/word" w:val="15"/>
  </w:compat>
</w:settings>"""
        return xml.strip().encode("utf-8")

    @staticmethod
    def _build_font_table_xml(fonts: Set[str]) -> bytes:
        """Generate word/fontTable.xml content."""
        lines = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<w:fonts xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">',
        ]
        for f in sorted(fonts):
            escaped_f = xml_escape(f)
            lines.append(f'  <w:font w:name="{escaped_f}">')
            lines.append(f'    <w:pitch w:val="variable"/>')
            lines.append(f'  </w:font>')
        lines.append("</w:fonts>")
        return "\n".join(lines).encode("utf-8")

    @staticmethod
    def _build_core_properties_xml(metadata: Dict[str, str]) -> bytes:
        """Generate docProps/core.xml content."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        title = xml_escape(metadata.get("Title", ""))
        author = xml_escape(metadata.get("Author", "anyconvert"))
        subject = xml_escape(metadata.get("Subject", ""))

        xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
                   xmlns:dc="http://purl.org/dc/elements/1.1/"
                   xmlns:dcterms="http://purl.org/dc/terms/"
                   xmlns:dcmitype="http://purl.org/dc/dcmitype/"
                   xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>{title}</dc:title>
  <dc:creator>{author}</dc:creator>
  <dc:subject>{subject}</dc:subject>
  <cp:lastModifiedBy>{author}</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">{now_iso}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{now_iso}</dcterms:modified>
</cp:coreProperties>"""
        return xml.strip().encode("utf-8")

    @staticmethod
    def _build_app_properties_xml(total_pages: int) -> bytes:
        """Generate docProps/app.xml content."""
        xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
            xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>anyconvert</Application>
  <DocSecurity>0</DocSecurity>
  <ScaleCrop>false</ScaleCrop>
  <Pages>{total_pages}</Pages>
  <Words>0</Words>
  <Characters>0</Characters>
  <Company></Company>
  <Lines>0</Lines>
  <Paragraphs>0</Paragraphs>
  <TotalTime>1</TotalTime>
  <AppVersion>16.0000</AppVersion>
</Properties>"""
        return xml.strip().encode("utf-8")


def pkg_images_count(pkg: OPCPackage) -> int:
    """Count how many media images are currently registered in package."""
    return sum(1 for name in pkg.parts if name.startswith("word/media/"))


__all__ = ["DocxEmitter"]
