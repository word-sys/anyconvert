"""Pure-Python PresentationML (PPTX) emitter conforming to ISO/IEC 29500."""

from __future__ import annotations

import datetime
from typing import Dict, List, Optional, Set
import zipfile

from anyconvert.common.color import Color
from anyconvert.common.geometry import BoundingBox
from anyconvert.emitters.base import (
    BaseEmitter,
    ConversionMode,
    color_to_hex,
    pt_to_emu,
    pt_to_hundredth_pt,
    xml_escape,
)
from anyconvert.emitters.pptx.theme import (
    build_presentation_xml,
    build_slide_layout_xml,
    build_slide_master_xml,
    build_theme_xml,
)
from anyconvert.exceptions import SerializationError
from anyconvert.ir.model import (
    Alignment,
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
)
from anyconvert.packaging.opc import (
    CT_CORE_PROPERTIES,
    CT_DRAWINGML_THEME,
    CT_EXTENDED_PROPERTIES,
    CT_PNG,
    CT_PRESENTATION_DOCUMENT,
    CT_PRESENTATION_SLIDE,
    CT_PRESENTATION_SLIDELAYOUT,
    CT_PRESENTATION_SLIDEMASTER,
    OPCPackage,
    OPCPart,
    RT_CORE_PROPERTIES,
    RT_EXTENDED_PROPERTIES,
    RT_IMAGE,
    RT_OFFICE_DOCUMENT,
    RT_SLIDE,
    RT_SLIDELAYOUT,
    RT_SLIDEMASTER,
    RT_THEME,
)


_ALIGN_MAP: Dict[Alignment, str] = {
    Alignment.LEFT: "left",
    Alignment.CENTER: "ctr",
    Alignment.RIGHT: "right",
    Alignment.JUSTIFIED: "just",
}


class PptxEmitter(BaseEmitter):
    """Pure-Python PPTX (PresentationML) emitter mapping pages to presentation slides."""

    def emit(
        self,
        doc_ir: DocumentIR,
        mode: ConversionMode = ConversionMode.FLOW,
    ) -> bytes:
        """Serialize a DocumentIR structure into a valid PPTX presentation archive.

        Args:
            doc_ir: Validated DocumentIR instance.
            mode: ConversionMode (in PPTX, shapes are positioned preserving spatial geometry).

        Returns:
            Raw bytes of the emitted .pptx file.
        """
        if not doc_ir.pages:
            raise SerializationError("Cannot emit PPTX from empty DocumentIR")

        pkg = OPCPackage()

        # 1. Package-level relationships
        pkg.add_package_relationship(RT_OFFICE_DOCUMENT, "ppt/presentation.xml")
        pkg.add_package_relationship(RT_CORE_PROPERTIES, "docProps/core.xml")
        pkg.add_package_relationship(RT_EXTENDED_PROPERTIES, "docProps/app.xml")

        # 2. Master, Layout, and Theme parts
        pkg.add_part(
            "ppt/slideMasters/slideMaster1.xml",
            build_slide_master_xml(),
            content_type=CT_PRESENTATION_SLIDEMASTER,
        )
        pkg.add_part(
            "ppt/slideLayouts/slideLayout1.xml",
            build_slide_layout_xml(),
            content_type=CT_PRESENTATION_SLIDELAYOUT,
        )
        pkg.add_part(
            "ppt/theme/theme1.xml",
            build_theme_xml(),
            content_type=CT_DRAWINGML_THEME,
        )

        # Connect Master and Layout relationships
        master_part = pkg.get_part("ppt/slideMasters/slideMaster1.xml")
        master_part.add_relationship(RT_SLIDELAYOUT, "../slideLayouts/slideLayout1.xml", rel_id="rIdLayout1")
        master_part.add_relationship(RT_THEME, "../theme/theme1.xml", rel_id="rIdTheme1")

        layout_part = pkg.get_part("ppt/slideLayouts/slideLayout1.xml")
        layout_part.add_relationship(RT_SLIDEMASTER, "../slideMasters/slideMaster1.xml", rel_id="rIdMaster1")

        # 3. Process slides for each DocumentPage
        first_page = doc_ir.pages[0]
        pres_width_emu = pt_to_emu(first_page.width)
        pres_height_emu = pt_to_emu(first_page.height)

        slide_rids: List[str] = []
        global_image_counter = [1]

        for idx, page in enumerate(doc_ir.pages):
            slide_num = idx + 1
            slide_part_name = f"ppt/slides/slide{slide_num}.xml"
            slide_rid = f"rIdSlide{slide_num}"
            slide_rids.append(slide_rid)

            slide_xml, slide_image_rels = self._build_slide_xml(
                page=page,
                pkg=pkg,
                slide_num=slide_num,
                global_image_counter=global_image_counter,
            )

            slide_part = pkg.add_part(
                slide_part_name,
                slide_xml.encode("utf-8"),
                content_type=CT_PRESENTATION_SLIDE,
            )

            # Slide relationships
            slide_part.add_relationship(
                RT_SLIDELAYOUT,
                "../slideLayouts/slideLayout1.xml",
                rel_id="rIdLayout1",
            )
            for target_rel, r_id in slide_image_rels.items():
                slide_part.add_relationship(RT_IMAGE, target_rel, rel_id=r_id)

        # 4. Generate ppt/presentation.xml and relationships
        pres_xml = build_presentation_xml(slide_rids, pres_width_emu, pres_height_emu)
        pres_part = pkg.add_part(
            "ppt/presentation.xml",
            pres_xml,
            content_type=CT_PRESENTATION_DOCUMENT,
        )

        pres_part.add_relationship(
            RT_SLIDEMASTER,
            "slideMasters/slideMaster1.xml",
            rel_id="rIdMaster1",
        )
        for idx, s_rid in enumerate(slide_rids):
            pres_part.add_relationship(
                RT_SLIDE,
                f"slides/slide{idx + 1}.xml",
                rel_id=s_rid,
            )

        # 5. Core and App properties
        pkg.add_part(
            "docProps/core.xml",
            self._build_core_properties_xml(doc_ir.metadata),
            content_type=CT_CORE_PROPERTIES,
        )
        pkg.add_part(
            "docProps/app.xml",
            self._build_app_properties_xml(len(doc_ir.pages)),
            content_type=CT_EXTENDED_PROPERTIES,
        )

        return pkg.to_bytes()

    def _build_slide_xml(
        self,
        page: DocumentPage,
        pkg: OPCPackage,
        slide_num: int,
        global_image_counter: List[int],
    ) -> tuple[str, Dict[str, str]]:
        """Generate XML for a single slide (<p:sld>)."""
        shape_elements: List[str] = []
        slide_image_rels: Dict[str, str] = {}
        shape_id = 2  # 1 is reserved for group

        # If header or footer present, render them
        if page.header:
            for p in page.header.content:
                shape_xml = self._render_paragraph_shape(p, shape_id=shape_id)
                shape_elements.append(shape_xml)
                shape_id += 1

        for block in page.blocks:
            if isinstance(block, Paragraph):
                shape_xml = self._render_paragraph_shape(block, shape_id=shape_id)
                shape_elements.append(shape_xml)
                shape_id += 1
            elif isinstance(block, Table):
                tbl_xml = self._render_table_shape(block, shape_id=shape_id)
                shape_elements.append(tbl_xml)
                shape_id += 1
            elif isinstance(block, ImageBlock):
                pic_xml = self._render_image_shape(
                    img=block,
                    pkg=pkg,
                    slide_num=slide_num,
                    shape_id=shape_id,
                    slide_image_rels=slide_image_rels,
                    global_image_counter=global_image_counter,
                )
                shape_elements.append(pic_xml)
                shape_id += 1

        if page.footer:
            for p in page.footer.content:
                shape_xml = self._render_paragraph_shape(p, shape_id=shape_id)
                shape_elements.append(shape_xml)
                shape_id += 1

        xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
       xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
       xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld>
    <p:spTree>
      <p:nvGrpSpPr>
        <p:cNvPr id="1" name=""/>
        <p:cNvGrpSpPr/>
        <p:nvPr/>
      </p:nvGrpSpPr>
      <p:grpSpPr>
        <a:xfrm>
          <a:off x="0" y="0"/>
          <a:ext cx="0" cy="0"/>
          <a:chOff x="0" y="0"/>
          <a:chExt cx="0" cy="0"/>
        </a:xfrm>
      </p:grpSpPr>
{"\n".join(shape_elements)}
    </p:spTree>
  </p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sld>"""
        return xml, slide_image_rels

    def _render_paragraph_shape(self, p: Paragraph, shape_id: int) -> str:
        """Render a Paragraph into a DrawingML text shape (<p:sp>)."""
        bbox = p.bbox or BoundingBox(72, 72, 400, 100)
        x_emu = pt_to_emu(bbox.x0)
        y_emu = pt_to_emu(bbox.y0)
        w_emu = pt_to_emu(bbox.width)
        h_emu = pt_to_emu(bbox.height)

        algn_val = _ALIGN_MAP.get(p.alignment, "left")

        runs_xml: List[str] = []
        for run in p.runs:
            sz_val = pt_to_hundredth_pt(run.font_size)
            b_val = ' b="1"' if run.is_bold else ""
            i_val = ' i="1"' if run.is_italic else ""
            u_val = ' u="sng"' if run.is_underline else ""
            strike_val = ' strike="sngStrike"' if run.is_strikethrough else ""
            hex_c = color_to_hex(run.color)
            font_name = xml_escape(run.font_name or "Calibri")

            runs_xml.append(f"""            <a:r>
              <a:rPr sz="{sz_val}"{b_val}{i_val}{u_val}{strike_val}>
                <a:solidFill><a:srgbClr val="{hex_c}"/></a:solidFill>
                <a:latin typeface="{font_name}"/>
              </a:rPr>
              <a:t>{xml_escape(run.text)}</a:t>
            </a:r>""")

        if not runs_xml:
            runs_xml.append("            <a:endParaRPr/>")

        runs_str = "\n".join(runs_xml)

        return f"""      <p:sp>
        <p:nvSpPr>
          <p:cNvPr id="{shape_id}" name="TextBox {shape_id}"/>
          <p:cNvSpPr txBox="1"/>
          <p:nvPr/>
        </p:nvSpPr>
        <p:spPr>
          <a:xfrm>
            <a:off x="{x_emu}" y="{y_emu}"/>
            <a:ext cx="{w_emu}" cy="{h_emu}"/>
          </a:xfrm>
          <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
          <a:noFill/>
        </p:spPr>
        <p:txBody>
          <a:bodyPr wrap="square" rtlCol="0">
            <a:spAutoFit/>
          </a:bodyPr>
          <a:lstStyle/>
          <a:p>
            <a:pPr algn="{algn_val}"/>
{runs_str}
          </a:p>
        </p:txBody>
      </p:sp>"""

    def _render_image_shape(
        self,
        img: ImageBlock,
        pkg: OPCPackage,
        slide_num: int,
        shape_id: int,
        slide_image_rels: Dict[str, str],
        global_image_counter: List[int],
    ) -> str:
        """Embed raster image and render PresentationML picture shape (<p:pic>)."""
        img_idx = global_image_counter[0]
        global_image_counter[0] += 1

        img_part_name = f"ppt/media/image{img_idx}.png"
        rel_target = f"../media/image{img_idx}.png"

        pkg.add_part(img_part_name, img.png_bytes, content_type=CT_PNG)

        rel_id = f"rIdImg{shape_id}"
        slide_image_rels[rel_target] = rel_id

        x_emu = pt_to_emu(img.bbox.x0)
        y_emu = pt_to_emu(img.bbox.y0)
        w_emu = pt_to_emu(img.bbox.width)
        h_emu = pt_to_emu(img.bbox.height)
        alt_str = xml_escape(img.alt_text or f"Picture {shape_id}")

        return f"""      <p:pic>
        <p:nvPicPr>
          <p:cNvPr id="{shape_id}" name="{alt_str}"/>
          <p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr>
          <p:nvPr/>
        </p:nvPicPr>
        <p:blipFill>
          <a:blip r:embed="{rel_id}"/>
          <a:stretch><a:fillRect/></a:stretch>
        </p:blipFill>
        <p:spPr>
          <a:xfrm>
            <a:off x="{x_emu}" y="{y_emu}"/>
            <a:ext cx="{w_emu}" cy="{h_emu}"/>
          </a:xfrm>
          <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
        </p:spPr>
      </p:pic>"""

    def _render_table_shape(self, table: Table, shape_id: int) -> str:
        """Render a Table into a DrawingML graphic frame with table element."""
        bbox = table.bbox or BoundingBox(72, 100, 450, 200)
        x_emu = pt_to_emu(bbox.x0)
        y_emu = pt_to_emu(bbox.y0)
        w_emu = pt_to_emu(bbox.width)
        h_emu = pt_to_emu(bbox.height)

        lines = [
            f'      <p:graphicFrame>',
            f'        <p:nvGraphicFramePr>',
            f'          <p:cNvPr id="{shape_id}" name="Table {shape_id}"/>',
            f'          <p:cNvGraphicFramePr><a:graphicFrameLocks noGrp="1"/></p:cNvGraphicFramePr>',
            f'          <p:nvPr/>',
            f'        </p:nvGraphicFramePr>',
            f'        <p:xfrm>',
            f'          <a:off x="{x_emu}" y="{y_emu}"/>',
            f'          <a:ext cx="{w_emu}" cy="{h_emu}"/>',
            f'        </p:xfrm>',
            f'        <a:graphic>',
            f'          <a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table">',
            f'            <a:tbl>',
            f'              <a:tblPr firstRow="1" bandRow="1"/>',
            f'              <a:tblGrid>',
        ]

        for cw in table.col_widths:
            lines.append(f'                <a:gridCol w="{pt_to_emu(cw)}"/>')
        lines.append('              </a:tblGrid>')

        for row in table.rows:
            r_h_emu = pt_to_emu(row.height) if row.height > 0 else 300000
            lines.append(f'              <a:tr h="{r_h_emu}">')
            for cell in row.cells:
                span_attrs: List[str] = []
                if cell.col_span > 1:
                    span_attrs.append(f'gridSpan="{cell.col_span}"')
                if cell.row_span > 1:
                    span_attrs.append(f'rowSpan="{cell.row_span}"')
                span_str = (" " + " ".join(span_attrs)) if span_attrs else ""

                lines.append(f'                <a:tc{span_str}>')
                lines.append('                  <a:txBody>')
                lines.append('                    <a:bodyPr/>')
                lines.append('                    <a:lstStyle/>')

                if not cell.content:
                    lines.append('                    <a:p><a:endParaRPr/></a:p>')
                else:
                    for b in cell.content:
                        if isinstance(b, Paragraph):
                            for r in b.runs:
                                sz = pt_to_hundredth_pt(r.font_size)
                                hex_c = color_to_hex(r.color)
                                lines.append(
                                    f'                    <a:p><a:r><a:rPr sz="{sz}">'
                                    f'<a:solidFill><a:srgbClr val="{hex_c}"/></a:solidFill></a:rPr>'
                                    f'<a:t>{xml_escape(r.text)}</a:t></a:r></a:p>'
                                )

                lines.append('                  </a:txBody>')
                lines.append('                  <a:tcPr>')
                if cell.background_color is not None:
                    lines.append(f'                    <a:solidFill><a:srgbClr val="{color_to_hex(cell.background_color)}"/></a:solidFill>')
                lines.append('                  </a:tcPr>')
                lines.append('                </a:tc>')
            lines.append('              </a:tr>')

        lines.extend([
            '            </a:tbl>',
            '          </a:graphicData>',
            '        </a:graphic>',
            '      </p:graphicFrame>',
        ])
        return "\n".join(lines)

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
    def _build_app_properties_xml(total_slides: int) -> bytes:
        """Generate docProps/app.xml content."""
        xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
            xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <TotalTime>0</TotalTime>
  <Words>0</Words>
  <Application>anyconvert</Application>
  <PresentationFormat>Custom</PresentationFormat>
  <Paragraphs>0</Paragraphs>
  <Slides>{total_slides}</Slides>
  <Notes>0</Notes>
  <HiddenSlides>0</HiddenSlides>
  <MMClips>0</MMClips>
  <ScaleCrop>false</ScaleCrop>
  <Company></Company>
  <AppVersion>16.0000</AppVersion>
</Properties>"""
        return xml.strip().encode("utf-8")


__all__ = ["PptxEmitter"]
