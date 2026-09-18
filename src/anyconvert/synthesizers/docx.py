"""
Native OpenXML WordprocessingML (DOCX) synthesizer for anyconvert.
Constructs valid .docx ZIP packages without third-party dependencies.
"""

import io
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union
from xml.sax.saxutils import escape as xml_escape
import zipfile

from anyconvert.core.models import (
    Document,
    ImageBlock,
    Page,
    ParagraphBlock,
    TableBlock,
    TextRun,
    VectorShapeBlock,
)
from anyconvert.core.options import ConversionOptions

# Conversion constants
PT_TO_DXA = 20  # 1 point = 20 twips/dxa
PT_TO_EMU = 12700  # 1 point = 12,700 English Metric Units (EMU)


class DocxSynthesizer:
    """Serializes an IR Document directly into a valid ECMA-376 .docx ZIP package."""

    def __init__(self, doc: Document, options: Optional[ConversionOptions] = None) -> None:
        self.doc = doc
        self.options = options or ConversionOptions()
        self.relationships: List[Tuple[str, str, str, Optional[str]]] = []  # (rId, type, target, target_mode)
        self.media_files: Dict[str, bytes] = {}  # zip_path -> bytes
        self.next_r_id = 1

    def _alloc_rel_id(self) -> str:
        r_id = f"rId{self.next_r_id}"
        self.next_r_id += 1
        return r_id

    def build_bytes(self) -> bytes:
        """Serialize document to in-memory DOCX bytes."""
        out_buf = io.BytesIO()
        with zipfile.ZipFile(out_buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            self._write_package(zf)
        return out_buf.getvalue()

    def build_file(self, target_path: Union[str, Path]) -> None:
        """Serialize document directly to a .docx file on disk."""
        path = Path(target_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(str(path), "w", compression=zipfile.ZIP_DEFLATED) as zf:
            self._write_package(zf)

    def _write_package(self, zf: zipfile.ZipFile) -> None:
        # Standard root relationships
        self.relationships.append((
            self._alloc_rel_id(),
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles",
            "styles.xml",
            None,
        ))
        self.relationships.append((
            self._alloc_rel_id(),
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings",
            "settings.xml",
            None,
        ))

        # Generate main document XML
        doc_xml = self._build_document_xml()

        # Write fixed OpenXML files
        zf.writestr("[Content_Types].xml", self._build_content_types_xml())
        zf.writestr("_rels/.rels", self._build_root_rels_xml())
        zf.writestr("word/styles.xml", self._build_styles_xml())
        zf.writestr("word/settings.xml", self._build_settings_xml())
        zf.writestr("word/_rels/document.xml.rels", self._build_doc_rels_xml())
        zf.writestr("word/document.xml", doc_xml)

        # Write embedded media files
        for media_path, data in self.media_files.items():
            zf.writestr(media_path, data)

    def _build_content_types_xml(self) -> str:
        return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="png" ContentType="image/png"/>
  <Default Extension="jpeg" ContentType="image/jpeg"/>
  <Default Extension="jpg" ContentType="image/jpeg"/>
  <Default Extension="webp" ContentType="image/webp"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>
</Types>"""

    def _build_root_rels_xml(self) -> str:
        return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

    def _build_doc_rels_xml(self) -> str:
        lines = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>']
        lines.append('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">')
        for r_id, rel_type, target, target_mode in self.relationships:
            mode_attr = f' TargetMode="{target_mode}"' if target_mode else ""
            lines.append(f'  <Relationship Id="{r_id}" Type="{rel_type}" Target="{target}"{mode_attr}/>')
        lines.append("</Relationships>")
        return "\n".join(lines)

    def _build_settings_xml(self) -> str:
        return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:defaultTabStop w:val="720"/>
</w:settings>"""

    def _build_styles_xml(self) -> str:
        return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:docDefaults>
    <w:rPrDefault>
      <w:rPr>
        <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/>
        <w:sz w:val="22"/>
        <w:color w:val="000000"/>
      </w:rPr>
    </w:rPrDefault>
  </w:docDefaults>
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal">
    <w:name w:val="Normal"/>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading1">
    <w:name w:val="heading 1"/>
    <w:rPr>
      <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/>
      <w:b/>
      <w:sz w:val="48"/>
      <w:color w:val="1F497D"/>
    </w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading2">
    <w:name w:val="heading 2"/>
    <w:rPr>
      <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/>
      <w:b/>
      <w:sz w:val="32"/>
      <w:color w:val="2E75B6"/>
    </w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading3">
    <w:name w:val="heading 3"/>
    <w:rPr>
      <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/>
      <w:b/>
      <w:sz w:val="26"/>
      <w:color w:val="1F497D"/>
    </w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading4">
    <w:name w:val="heading 4"/>
    <w:rPr>
      <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/>
      <w:b/>
      <w:sz w:val="24"/>
    </w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="ListBullet">
    <w:name w:val="List Bullet"/>
    <w:pPr>
      <w:ind w:left="720" w:hanging="360"/>
    </w:pPr>
  </w:style>
</w:styles>"""

    def _build_document_xml(self) -> str:
        lines = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>']
        lines.append(
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
            'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
            'xmlns:wps="http://schemas.openxmlformats.org/wordprocessingml/2010/wordprocessingShape" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        )
        lines.append("  <w:body>")

        page_w_pt = 612.0
        page_h_pt = 792.0

        for p_idx, page in enumerate(self.doc.pages):
            page_w_pt = page.width
            page_h_pt = page.height

            for block in page.blocks:
                if isinstance(block, ParagraphBlock):
                    if self.options.mode == "precise":
                        lines.append(self._render_paragraph_precise(block))
                    else:
                        lines.append(self._render_paragraph_flow(block))
                elif isinstance(block, TableBlock):
                    lines.append(self._render_table(block))
                elif isinstance(block, ImageBlock):
                    lines.append(self._render_image(block))
                elif isinstance(block, VectorShapeBlock):
                    lines.append(self._render_vector_shape(block))

            # Page break between pages (except after the final page)
            if p_idx < len(self.doc.pages) - 1:
                lines.append('    <w:p><w:r><w:br w:type="page"/></w:r></w:p>')

        # Document section properties (page width, height, margins)
        page_w_dxa = int(page_w_pt * PT_TO_DXA)
        page_h_dxa = int(page_h_pt * PT_TO_DXA)
        lines.append("    <w:sectPr>")
        lines.append(f'      <w:pgSz w:w="{page_w_dxa}" w:h="{page_h_dxa}"/>')
        lines.append('      <w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/>')
        lines.append("    </w:sectPr>")

        lines.append("  </w:body>")
        lines.append("</w:document>")
        return "\n".join(lines)

    def _render_paragraph_flow(self, block: ParagraphBlock) -> str:
        parts = ["    <w:p>"]

        # Paragraph properties
        p_pr = []
        if block.heading_level and 1 <= block.heading_level <= 4:
            p_pr.append(f'<w:pStyle w:val="Heading{block.heading_level}"/>')
        elif block.is_list_item:
            p_pr.append('<w:pStyle w:val="ListBullet"/>')

        if block.alignment != "left":
            p_pr.append(f'<w:jc w:val="{block.alignment}"/>')

        if block.background_color and not self.options.mode == "precise":
            hex_bg = block.background_color.to_hex().lstrip("#")
            p_pr.append(f'<w:shd w:val="clear" w:color="auto" w:fill="{hex_bg}"/>')

        if p_pr:
            parts.append(f"      <w:pPr>{''.join(p_pr)}</w:pPr>")

        for l_idx, line in enumerate(block.lines):
            if l_idx > 0:
                prev_line = block.lines[l_idx - 1]
                prev_text = prev_line.text
                curr_text = line.text
                if (
                    prev_text
                    and curr_text
                    and not prev_text.endswith((" ", "\t", "\n", "\r", "-", "—", "–"))
                    and not curr_text.startswith((" ", "\t", "\n", "\r"))
                ):
                    parts.append('<w:r><w:t xml:space="preserve"> </w:t></w:r>')

            for run in line.runs:
                parts.append(self._render_run(run))

        parts.append("    </w:p>")
        return "".join(parts)

    def _render_run(self, run: TextRun) -> str:
        text = run.text
        if not text:
            return ""

        escaped_text = xml_escape(text)

        r_pr = []
        font_name = run.font_name.split("+")[-1]  # Strip subset font prefix (e.g. ABCDEF+Calibri)
        r_pr.append(f'<w:rFonts w:ascii="{xml_escape(font_name)}" w:hAnsi="{xml_escape(font_name)}"/>')

        if run.is_bold:
            r_pr.append("<w:b/>")
        if run.is_italic:
            r_pr.append("<w:i/>")
        if run.is_underline:
            r_pr.append('<w:u w:val="single"/>')

        sz_half_pts = int(round(run.font_size * 2))
        r_pr.append(f'<w:sz w:val="{sz_half_pts}"/>')

        hex_color = run.color.to_hex().lstrip("#")
        if hex_color != "000000":
            r_pr.append(f'<w:color w:val="{hex_color}"/>')

        run_xml = (
            f"<w:r>"
            f"<w:rPr>{''.join(r_pr)}</w:rPr>"
            f'<w:t xml:space="preserve">{escaped_text}</w:t>'
            f"</w:r>"
        )

        if run.hyperlink_uri:
            rel_id = self._alloc_rel_id()
            self.relationships.append((
                rel_id,
                "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
                run.hyperlink_uri,
                "External",
            ))
            return f'<w:hyperlink r:id="{rel_id}">{run_xml}</w:hyperlink>'

        return run_xml

    def _render_table(self, table: TableBlock) -> str:
        lines = ["    <w:tbl>"]

        # Table Properties
        lines.append("      <w:tblPr>")
        lines.append('        <w:tblW w:w="0" w:type="auto"/>')
        lines.append("        <w:tblBorders>")
        lines.append('          <w:top w:val="single" w:sz="4" w:space="0" w:color="B0B0B0"/>')
        lines.append('          <w:bottom w:val="single" w:sz="4" w:space="0" w:color="B0B0B0"/>')
        lines.append('          <w:left w:val="none"/>')
        lines.append('          <w:right w:val="none"/>')
        lines.append('          <w:insideH w:val="single" w:sz="4" w:space="0" w:color="D0D0D0"/>')
        lines.append('          <w:insideV w:val="none"/>')
        lines.append("        </w:tblBorders>")
        lines.append("      </w:tblPr>")

        # Table Grid (column widths)
        total_w_dxa = int(table.bbox.width * PT_TO_DXA) if table.bbox.width > 0 else 8640
        col_w_dxa = max(720, total_w_dxa // max(1, table.cols))
        lines.append("      <w:tblGrid>")
        for _ in range(table.cols):
            lines.append(f'        <w:gridCol w:w="{col_w_dxa}"/>')
        lines.append("      </w:tblGrid>")

        matrix = table.as_matrix()
        for r_idx, row in enumerate(matrix):
            lines.append("      <w:tr>")
            for cell_text in row:
                lines.append("        <w:tc>")
                lines.append(f'          <w:tcPr><w:tcW w:w="{col_w_dxa}" w:type="dxa"/></w:tcPr>')
                is_header = (r_idx == 0)
                bold_tag = "<w:b/>" if is_header else ""
                escaped = xml_escape(cell_text.strip())
                lines.append(
                    f'          <w:p><w:r><w:rPr>{bold_tag}</w:rPr><w:t xml:space="preserve">{escaped}</w:t></w:r></w:p>'
                )
                lines.append("        </w:tc>")
            lines.append("      </w:tr>")

        lines.append("    </w:tbl>")
        lines.append("    <w:p/>")  # Space after table
        return "\n".join(lines)

    def _render_image(self, img: ImageBlock) -> str:
        img_idx = len(self.media_files) + 1
        ext = img.image_format.lower()
        if ext not in ("png", "jpeg", "jpg", "webp"):
            ext = "png"

        zip_path = f"word/media/image{img_idx}.{ext}"
        self.media_files[zip_path] = img.image_bytes

        rel_id = self._alloc_rel_id()
        self.relationships.append((
            rel_id,
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
            f"media/image{img_idx}.{ext}",
            None,
        ))

        # Size in EMUs
        width_pt = img.bbox.width if img.bbox.width > 0 else (img.width * 72.0 / 300.0 if img.width > 0 else 100.0)
        height_pt = img.bbox.height if img.bbox.height > 0 else (img.height * 72.0 / 300.0 if img.height > 0 else 100.0)
        cx_emu = int(width_pt * PT_TO_EMU)
        cy_emu = int(height_pt * PT_TO_EMU)

        doc_pr_id = img_idx
        return f"""    <w:p>
      <w:r>
        <w:drawing>
          <wp:inline distT="0" distB="0" distL="0" distR="0">
            <wp:extent cx="{cx_emu}" cy="{cy_emu}"/>
            <wp:docPr id="{doc_pr_id}" name="Picture {doc_pr_id}"/>
            <a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
              <a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
                <pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">
                  <pic:nvPicPr>
                    <pic:cNvPr id="{doc_pr_id}" name="Picture {doc_pr_id}"/>
                    <pic:cNvPicPr/>
                  </pic:nvPicPr>
                  <pic:blipFill>
                    <a:blip r:embed="{rel_id}"/>
                    <a:stretch><a:fillRect/></a:stretch>
                  </pic:blipFill>
                  <pic:spPr>
                    <a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx_emu}" cy="{cy_emu}"/></a:xfrm>
                    <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
                  </pic:spPr>
                </pic:pic>
              </a:graphicData>
            </a:graphic>
          </wp:inline>
        </w:drawing>
      </w:r>
    </w:p>"""

    def _render_paragraph_precise(self, block: ParagraphBlock) -> str:
        x_emu = int(block.bbox.x0 * PT_TO_EMU)
        y_emu = int(block.bbox.y0 * PT_TO_EMU)
        cx_emu = int((block.bbox.width + 10) * PT_TO_EMU)
        cy_emu = int((block.bbox.height + 10) * PT_TO_EMU)
        shape_id = self.next_r_id
        self.next_r_id += 1
        
        inner_p = self._render_paragraph_flow(block)
        
        bg_xml = ""
        if block.background_color:
            bg_xml = f'<a:solidFill><a:srgbClr val="{block.background_color.to_hex().lstrip("#")}"/></a:solidFill>'
        else:
            bg_xml = '<a:noFill/>'
            
        return f"""    <w:p>
      <w:pPr>
        <w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/>
      </w:pPr>
      <w:r>
        <w:drawing>
          <wp:anchor distT="0" distB="0" distL="0" distR="0" simplePos="0" relativeHeight="251658240" behindDoc="0" locked="0" layoutInCell="1" allowOverlap="1">
            <wp:simplePos x="0" y="0"/>
            <wp:positionH relativeFrom="page">
              <wp:posOffset>{x_emu}</wp:posOffset>
            </wp:positionH>
            <wp:positionV relativeFrom="page">
              <wp:posOffset>{y_emu}</wp:posOffset>
            </wp:positionV>
            <wp:extent cx="{cx_emu}" cy="{cy_emu}"/>
            <wp:docPr id="{shape_id}" name="Text Box {shape_id}"/>
            <wp:cNvGraphicFramePr/>
            <a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
              <a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingShape">
                <wps:wsp xmlns:wps="http://schemas.openxmlformats.org/wordprocessingml/2010/wordprocessingShape">
                  <wps:cNvSpPr txBox="1"/>
                  <wps:spPr>
                    <a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx_emu}" cy="{cy_emu}"/></a:xfrm>
                    <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
                    {bg_xml}
                    <a:ln><a:noFill/></a:ln>
                  </wps:spPr>
                  <wps:txbx>
                    <w:txbxContent>
                      {inner_p.strip()}
                    </w:txbxContent>
                  </wps:txbx>
                </wps:wsp>
              </a:graphicData>
            </a:graphic>
          </wp:anchor>
        </w:drawing>
      </w:r>
    </w:p>"""

    def _render_vector_shape(self, shape: VectorShapeBlock) -> str:
        x_emu = int(shape.bbox.x0 * PT_TO_EMU)
        y_emu = int(shape.bbox.y0 * PT_TO_EMU)
        cx_emu = int(max(1.0, shape.bbox.width) * PT_TO_EMU)
        cy_emu = int(max(1.0, shape.bbox.height) * PT_TO_EMU)
        shape_id = self.next_r_id
        self.next_r_id += 1

        fill_xml = ""
        if shape.fill_color:
            fill_xml = f'<a:solidFill><a:srgbClr val="{shape.fill_color.to_hex().lstrip("#")}"/></a:solidFill>'
        else:
            fill_xml = '<a:noFill/>'
            
        stroke_xml = ""
        if shape.stroke_color:
            w_emu = int(max(0.25, shape.stroke_width) * PT_TO_EMU)
            stroke_xml = f'<a:ln w="{w_emu}"><a:solidFill><a:srgbClr val="{shape.stroke_color.to_hex().lstrip("#")}"/></a:solidFill></a:ln>'
        else:
            stroke_xml = '<a:ln><a:noFill/></a:ln>'
            
        prst = "rect" if shape.shape_type == "rect" else "line"

        return f"""    <w:p>
      <w:pPr>
        <w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/>
      </w:pPr>
      <w:r>
        <w:drawing>
          <wp:anchor distT="0" distB="0" distL="0" distR="0" simplePos="0" relativeHeight="251658240" behindDoc="1" locked="0" layoutInCell="1" allowOverlap="1">
            <wp:simplePos x="0" y="0"/>
            <wp:positionH relativeFrom="page">
              <wp:posOffset>{x_emu}</wp:posOffset>
            </wp:positionH>
            <wp:positionV relativeFrom="page">
              <wp:posOffset>{y_emu}</wp:posOffset>
            </wp:positionV>
            <wp:extent cx="{cx_emu}" cy="{cy_emu}"/>
            <wp:docPr id="{shape_id}" name="Shape {shape_id}"/>
            <wp:cNvGraphicFramePr/>
            <a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
              <a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingShape">
                <wps:wsp xmlns:wps="http://schemas.openxmlformats.org/wordprocessingml/2010/wordprocessingShape">
                  <wps:cNvSpPr/>
                  <wps:spPr>
                    <a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx_emu}" cy="{cy_emu}"/></a:xfrm>
                    <a:prstGeom prst="{prst}"><a:avLst/></a:prstGeom>
                    {fill_xml}
                    {stroke_xml}
                  </wps:spPr>
                </wps:wsp>
              </a:graphicData>
            </a:graphic>
          </wp:anchor>
        </w:drawing>
      </w:r>
    </w:p>"""
