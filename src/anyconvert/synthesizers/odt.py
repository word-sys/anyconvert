"""
Native OASIS OpenDocument Text (ODT) synthesizer for anyconvert.
Constructs valid .odt ZIP packages without third-party dependencies.
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
    Color,
)
from anyconvert.core.options import ConversionOptions


class OdtSynthesizer:
    """Serializes an IR Document directly into a valid OASIS OpenDocument .odt ZIP package."""

    def __init__(self, doc: Document, options: Optional[ConversionOptions] = None) -> None:
        self.doc = doc
        self.options = options or ConversionOptions()
        self.media_files: Dict[str, bytes] = {}
        self.automatic_styles: List[str] = []
        self.style_map: Dict[str, str] = {}
        self.next_style_id = 1

    def _get_or_create_span_style(self, run: TextRun) -> Optional[str]:
        font_name = run.font_name.split("+")[-1]
        sz_pt = f"{run.font_size:.1f}pt"
        hex_col = run.color.to_hex()
        is_bold = run.is_bold
        is_italic = run.is_italic
        is_underline = run.is_underline
        is_strikethrough = run.is_strikethrough

        key = (font_name, sz_pt, hex_col, is_bold, is_italic, is_underline, is_strikethrough)
        style_key = str(key)
        if style_key in self.style_map:
            return self.style_map[style_key]

        style_name = f"T{self.next_style_id}"
        self.next_style_id += 1
        self.style_map[style_key] = style_name

        props = [
            f'style:font-name="{xml_escape(font_name)}"',
            f'fo:font-size="{sz_pt}"',
        ]
        if is_bold:
            props.append('fo:font-weight="bold"')
        if is_italic:
            props.append('fo:font-style="italic"')
        if is_underline:
            props.append('style:text-underline-style="solid" style:text-underline-width="auto"')
        if is_strikethrough:
            props.append('style:text-line-through-style="solid"')
        if hex_col != "#000000":
            props.append(f'fo:color="{hex_col}"')

        style_xml = (
            f'    <style:style style:name="{style_name}" style:family="text">\n'
            f'      <style:text-properties {" ".join(props)}/>\n'
            f"    </style:style>"
        )
        self.automatic_styles.append(style_xml)
        return style_name

    def _get_or_create_shape_style(self, fill_color: Optional[Color], stroke_color: Optional[Color], stroke_width: float) -> str:
        key = (
            fill_color.to_hex() if fill_color else None,
            stroke_color.to_hex() if stroke_color else None,
            stroke_width
        )
        style_key = str(key)
        if style_key in self.style_map:
            return self.style_map[style_key]

        style_name = f"S{self.next_style_id}"
        self.next_style_id += 1
        self.style_map[style_key] = style_name

        props = []
        if fill_color:
            props.append(f'draw:fill="solid" draw:fill-color="{fill_color.to_hex()}"')
        else:
            props.append('draw:fill="none"')

        if stroke_color:
            props.append(f'draw:stroke="solid" svg:stroke-color="{stroke_color.to_hex()}" svg:stroke-width="{stroke_width}pt"')
        else:
            props.append('draw:stroke="none"')

        style_xml = (
            f'    <style:style style:name="{style_name}" style:family="graphic">\n'
            f'      <style:graphic-properties {" ".join(props)}/>\n'
            f"    </style:style>"
        )
        self.automatic_styles.append(style_xml)
        return style_name

    def _get_or_create_paragraph_style(self, block: ParagraphBlock) -> str:
        if not block.background_color:
            return "List" if block.is_list_item else "Standard"

        key = f"ParaBg_{block.background_color.to_hex()}"
        if key in self.style_map:
            return self.style_map[key]

        style_name = f"P{self.next_style_id}"
        self.next_style_id += 1
        self.style_map[key] = style_name

        parent_style = "List" if block.is_list_item else "Standard"
        style_xml = (
            f'    <style:style style:name="{style_name}" style:family="paragraph" style:parent-style-name="{parent_style}">\n'
            f'      <style:paragraph-properties fo:background-color="{block.background_color.to_hex()}"/>\n'
            f"    </style:style>"
        )
        self.automatic_styles.append(style_xml)
        return style_name

    def build_bytes(self) -> bytes:
        """Serialize document to in-memory ODT bytes."""
        out_buf = io.BytesIO()
        with zipfile.ZipFile(out_buf, "w") as zf:
            self._write_package(zf)
        return out_buf.getvalue()

    def build_file(self, target_path: Union[str, Path]) -> None:
        """Serialize document directly to an .odt file on disk."""
        path = Path(target_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(str(path), "w") as zf:
            self._write_package(zf)

    def _write_package(self, zf: zipfile.ZipFile) -> None:
        # Pre-process content to collect automatic styles and media
        content_body = self._build_body_content()
        content_xml = self._build_content_xml(content_body)

        # 1. mimetype MUST be first and uncompressed (ZIP_STORED)
        zf.writestr(
            "mimetype",
            "application/vnd.oasis.opendocument.text",
            compress_type=zipfile.ZIP_STORED,
        )

        # 2. Package manifest and XML entries
        zf.writestr("META-INF/manifest.xml", self._build_manifest_xml(), compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("styles.xml", self._build_styles_xml(), compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("meta.xml", self._build_meta_xml(), compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("content.xml", content_xml, compress_type=zipfile.ZIP_DEFLATED)

        # 3. Media images
        for path_in_zip, data in self.media_files.items():
            zf.writestr(path_in_zip, data, compress_type=zipfile.ZIP_DEFLATED)

    def _build_manifest_xml(self) -> str:
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2">',
            '  <manifest:file-entry manifest:full-path="/" manifest:version="1.2" manifest:media-type="application/vnd.oasis.opendocument.text"/>',
            '  <manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>',
            '  <manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/>',
            '  <manifest:file-entry manifest:full-path="meta.xml" manifest:media-type="text/xml"/>',
        ]
        for path_in_zip in self.media_files.keys():
            ext = path_in_zip.rsplit(".", 1)[-1].lower()
            media_type = f"image/{ext}" if ext in ("png", "jpeg", "webp") else "image/png"
            lines.append(f'  <manifest:file-entry manifest:full-path="{path_in_zip}" manifest:media-type="{media_type}"/>')

        lines.append("</manifest:manifest>")
        return "\n".join(lines)

    def _build_meta_xml(self) -> str:
        meta_title = xml_escape(self.doc.metadata.get("title", "")) if self.doc.metadata else ""
        meta_author = xml_escape(self.doc.metadata.get("author", "")) if self.doc.metadata else ""

        title_tag = f"    <dc:title>{meta_title}</dc:title>\n" if meta_title else ""
        creator_tag = f"    <dc:creator>{meta_author}</dc:creator>\n" if meta_author else ""

        return f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-meta xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0" xmlns:dc="http://purl.org/dc/elements/1.1/" office:version="1.2">
  <office:meta>
    <meta:generator>anyconvert</meta:generator>
{title_tag}{creator_tag}  </office:meta>
</office:document-meta>"""

    def _build_styles_xml(self) -> str:
        return """<?xml version="1.0" encoding="UTF-8"?>
<office:document-styles xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0" office:version="1.2">
  <office:styles>
    <style:style style:name="Standard" style:family="paragraph" style:class="text">
      <style:text-properties fo:font-size="11pt" fo:color="#000000"/>
    </style:style>
    <style:style style:name="Heading" style:family="paragraph" style:parent-style-name="Standard" style:class="chapter">
      <style:text-properties fo:font-weight="bold"/>
    </style:style>
    <style:style style:name="Heading_20_1" style:display-name="Heading 1" style:family="paragraph" style:parent-style-name="Heading" style:default-outline-level="1" style:class="chapter">
      <style:text-properties fo:font-size="24pt" fo:color="#1F497D"/>
    </style:style>
    <style:style style:name="Heading_20_2" style:display-name="Heading 2" style:family="paragraph" style:parent-style-name="Heading" style:default-outline-level="2" style:class="chapter">
      <style:text-properties fo:font-size="18pt" fo:color="#2E75B6"/>
    </style:style>
    <style:style style:name="Heading_20_3" style:display-name="Heading 3" style:family="paragraph" style:parent-style-name="Heading" style:default-outline-level="3" style:class="chapter">
      <style:text-properties fo:font-size="14pt" fo:color="#1F497D"/>
    </style:style>
    <style:style style:name="Heading_20_4" style:display-name="Heading 4" style:family="paragraph" style:parent-style-name="Heading" style:default-outline-level="4" style:class="chapter">
      <style:text-properties fo:font-size="12pt"/>
    </style:style>
    <style:style style:name="List" style:family="paragraph" style:parent-style-name="Standard">
      <style:paragraph-properties fo:margin-left="0.5in" fo:text-indent="-0.25in"/>
    </style:style>
    <style:style style:name="PageBreak" style:family="paragraph" style:parent-style-name="Standard">
      <style:paragraph-properties fo:break-before="page"/>
    </style:style>
  </office:styles>
</office:document-styles>"""

    def _build_content_xml(self, body_xml: str) -> str:
        styles_xml = "\n".join(self.automatic_styles)
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0" office:version="1.2">
  <office:automatic-styles>
    <style:style style:name="TableBordered" style:family="table">
      <style:table-properties style:width="100%" table:align="margins"/>
    </style:style>
    <style:style style:name="TableCell_Bordered" style:family="table-cell">
      <style:table-cell-properties fo:padding="4pt" fo:border="0.5pt solid #CCCCCC"/>
    </style:style>
    <style:style style:name="TableCell_Header" style:family="table-cell">
      <style:table-cell-properties fo:padding="4pt" fo:border="0.5pt solid #CCCCCC" fo:background-color="#F2F2F2"/>
    </style:style>
{styles_xml}
  </office:automatic-styles>
  <office:body>
    <office:text>
{body_xml}
    </office:text>
  </office:body>
</office:document-content>"""

    def _build_body_content(self) -> str:
        lines: List[str] = []

        for p_idx, page in enumerate(self.doc.pages):
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

            if p_idx < len(self.doc.pages) - 1:
                lines.append('      <text:p text:style-name="PageBreak"/>')

        return "\n".join(lines)

    def _render_paragraph_flow(self, block: ParagraphBlock) -> str:
        if block.heading_level and 1 <= block.heading_level <= 4:
            runs_xml = []
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
                        runs_xml.append("<text:s/>")
                for run in line.runs:
                    runs_xml.append(self._render_run(run))
            text_content = "".join(runs_xml)
            return f'      <text:h text:outline-level="{block.heading_level}" text:style-name="Heading_20_{block.heading_level}">{text_content}</text:h>'

        style_name = self._get_or_create_paragraph_style(block)
        runs_xml = []
        if block.is_list_item:
            bullet = block.list_bullet or "•"
            runs_xml.append(f'<text:span>{xml_escape(bullet)} </text:span>')

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
                    runs_xml.append("<text:s/>")

            for run in line.runs:
                runs_xml.append(self._render_run(run))

        return f'      <text:p text:style-name="{style_name}">{"".join(runs_xml)}</text:p>'

    def _render_run(self, run: TextRun) -> str:
        text = run.text
        if not text:
            return ""

        escaped_text = xml_escape(text).replace("  ", "&#160; ")
        style_name = self._get_or_create_span_style(run)

        span_xml = f'<text:span text:style-name="{style_name}">{escaped_text}</text:span>'

        if run.hyperlink_uri:
            return f'<text:a xlink:type="simple" xlink:href="{xml_escape(run.hyperlink_uri)}">{span_xml}</text:a>'

        return span_xml

    def _render_table(self, table: TableBlock) -> str:
        lines = [f'      <table:table table:name="Table_{table.bbox.x0:.0f}_{table.bbox.y0:.0f}" table:style-name="TableBordered">']
        lines.append(f'        <table:table-column table:number-columns-repeated="{table.cols}"/>')

        matrix = table.as_matrix()
        for r_idx, row in enumerate(matrix):
            lines.append("        <table:table-row>")
            for cell_text in row:
                is_header = (r_idx == 0)
                cell_style = "TableCell_Header" if is_header else "TableCell_Bordered"
                escaped = xml_escape(cell_text.strip())
                text_tag = f'<text:span style:font-weight="bold">{escaped}</text:span>' if is_header else escaped
                lines.append(
                    f'          <table:table-cell table:style-name="{cell_style}" office:value-type="string">'
                    f"<text:p>{text_tag}</text:p></table:table-cell>"
                )
            lines.append("        </table:table-row>")

        lines.append("      </table:table>")
        return "\n".join(lines)

    def _render_image(self, img: ImageBlock) -> str:
        img_idx = len(self.media_files) + 1
        ext = img.image_format.lower()
        if ext not in ("png", "jpeg", "jpg", "webp"):
            ext = "png"

        path_in_zip = f"Pictures/image{img_idx}.{ext}"
        self.media_files[path_in_zip] = img.image_bytes

        w_pt = img.bbox.width if img.bbox.width > 0 else (img.width * 72.0 / 300.0 if img.width > 0 else 100.0)
        h_pt = img.bbox.height if img.bbox.height > 0 else (img.height * 72.0 / 300.0 if img.height > 0 else 100.0)

        return (
            f'      <text:p><draw:frame draw:name="Image_{img_idx}" text:anchor-type="paragraph" '
            f'svg:width="{w_pt:.2f}pt" svg:height="{h_pt:.2f}pt">\n'
            f'        <draw:image xlink:href="{path_in_zip}" xlink:type="simple" xlink:show="embed" xlink:actuate="onLoad"/>\n'
            f"      </draw:frame></text:p>"
        )

    def _render_paragraph_precise(self, block: ParagraphBlock) -> str:
        x_pt = block.bbox.x0
        y_pt = block.bbox.y0
        w_pt = max(1.0, block.bbox.width + 10)
        h_pt = max(1.0, block.bbox.height + 10)
        
        inner_p = self._render_paragraph_flow(block)
        
        shape_style = self._get_or_create_shape_style(block.background_color, None, 0.0)

        return (
            f'      <text:p><draw:frame text:anchor-type="page" '
            f'svg:x="{x_pt:.2f}pt" svg:y="{y_pt:.2f}pt" svg:width="{w_pt:.2f}pt" svg:height="{h_pt:.2f}pt">\n'
            f'        <draw:text-box draw:style-name="{shape_style}">\n'
            f'    {inner_p}\n'
            f'        </draw:text-box>\n'
            f'      </draw:frame></text:p>'
        )

    def _render_vector_shape(self, shape: VectorShapeBlock) -> str:
        x_pt = shape.bbox.x0
        y_pt = shape.bbox.y0
        w_pt = max(1.0, shape.bbox.width)
        h_pt = max(1.0, shape.bbox.height)
        
        style_name = self._get_or_create_shape_style(shape.fill_color, shape.stroke_color, shape.stroke_width)
        
        tag = "draw:rect" if shape.shape_type == "rect" else "draw:line"
        
        if tag == "draw:line":
            return (
                f'      <text:p><draw:line text:anchor-type="page" '
                f'svg:x1="{x_pt:.2f}pt" svg:y1="{y_pt:.2f}pt" svg:x2="{x_pt + w_pt:.2f}pt" svg:y2="{y_pt + h_pt:.2f}pt" '
                f'draw:style-name="{style_name}"/></text:p>'
            )
            
        return (
            f'      <text:p><draw:rect text:anchor-type="page" '
            f'svg:x="{x_pt:.2f}pt" svg:y="{y_pt:.2f}pt" svg:width="{w_pt:.2f}pt" svg:height="{h_pt:.2f}pt" '
            f'draw:style-name="{style_name}"/></text:p>'
        )
