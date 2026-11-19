"""EPUB 3.3 chapter splitting and reflowable XHTML content generation engine.

Splits DocumentIR hierarchies into right-sized XHTML chapter files at major
heading boundaries (H1) or page boundaries, emitting standards-compliant
XHTML documents with embedded typography, packaged image references, and
heading anchors synchronized with the EPUB navigation document.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import List, Optional, Sequence, Tuple, Union

from anyconvert.emitters.base import color_to_hex, xml_escape
from anyconvert.emitters.epub.nav import EPUB_OPS_NS, TocEntry, XHTML_NS
from anyconvert.ir.model import (
    Alignment,
    BlockNode,
    DocumentIR,
    HeadingLevel,
    ImageBlock,
    Paragraph,
    Table,
    TableCell,
    TableRow,
    TextRun,
    VectorBlock,
)
from anyconvert.packaging.epub import MEDIA_TYPE_PNG, infer_epub_media_type

DEFAULT_EPUB_CSS = """\
@charset "UTF-8";

html, body {
  margin: 0;
  padding: 0;
}

body {
  font-family: Georgia, "Times New Roman", serif;
  font-size: 1em;
  line-height: 1.55;
  color: #1a1a1a;
  margin: 1em 1.2em;
}

h1, h2, h3, h4, h5, h6 {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  line-height: 1.25;
  margin-top: 1.4em;
  margin-bottom: 0.5em;
  page-break-after: avoid;
  break-after: avoid;
}

h1 { font-size: 1.7em; border-bottom: 1px solid #d0d7de; padding-bottom: 0.25em; }
h2 { font-size: 1.4em; }
h3 { font-size: 1.2em; }
h4 { font-size: 1.05em; }

p {
  margin: 0.65em 0;
  orphans: 2;
  widows: 2;
}

ul, ol {
  margin: 0.65em 0;
  padding-left: 1.6em;
}

li {
  margin: 0.25em 0;
}

code, pre {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.9em;
}

table {
  border-collapse: collapse;
  width: 100%;
  margin: 1em 0;
  font-size: 0.92em;
}

th, td {
  border: 1px solid #c9d1d9;
  padding: 0.45em 0.65em;
  text-align: left;
  vertical-align: top;
}

th {
  background-color: #f6f8fa;
  font-weight: bold;
}

figure {
  margin: 1em 0;
  text-align: center;
  page-break-inside: avoid;
  break-inside: avoid;
}

figure img, svg {
  max-width: 100%;
  height: auto;
}

figcaption {
  font-size: 0.85em;
  color: #57606a;
  margin-top: 0.35em;
}

nav#toc ol {
  list-style-type: none;
  padding-left: 1.1em;
}

nav#toc > ol {
  padding-left: 0;
}

nav#toc a {
  text-decoration: none;
  color: #0969da;
}
"""

_UNORDERED_BULLET_RE = re.compile(
    r"^[\s]*([•·○●▪■▫–—\*\-]|[\u2022\u00b7\u25cb\u25cf\u25aa\u25a0\u25ab\u2013\u2014\u2713\u27a4])\s+"
)
_ORDERED_NUMBER_RE = re.compile(
    r"^[\s]*(\(?\d+[\.\)]|\(?[a-zA-Z][\.\)]|\(?[ivxlcdmIVXLCDM]+[\.\)])\s+"
)
_URL_RE = re.compile(r"^(https?://|mailto:)[^\s]+$")
_MONOSPACE_KEYWORDS = (
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


class ChapterSplitStrategy(str, Enum):
    """Strategy controlling how DocumentIR content is paginated into XHTML chapters."""

    AUTO = "auto"
    HEADING = "heading"
    PAGE = "page"


def resolve_split_strategy(
    strategy: Union[ChapterSplitStrategy, str],
) -> ChapterSplitStrategy:
    """Normalize ChapterSplitStrategy from enum or string."""
    if isinstance(strategy, ChapterSplitStrategy):
        return strategy
    if isinstance(strategy, str):
        norm = strategy.lower().strip()
        if norm == "auto":
            return ChapterSplitStrategy.AUTO
        if norm == "heading":
            return ChapterSplitStrategy.HEADING
        if norm == "page":
            return ChapterSplitStrategy.PAGE
        raise ValueError(
            f"Invalid EPUB chapter split strategy: {strategy!r}. Must be 'auto', 'heading', or 'page'."
        )
    raise TypeError(
        f"Invalid split strategy type: {type(strategy).__name__}. Must be ChapterSplitStrategy or str."
    )


@dataclass(slots=True)
class ChapterSection:
    """Logical chapter slice produced by splitting a DocumentIR."""

    index: int
    chapter_id: str
    href: str
    title: str
    blocks: List[BlockNode] = field(default_factory=list)
    page_numbers: List[int] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ExtractedImageAsset:
    """Binary image asset extracted during chapter rendering for OEBPS packaging."""

    item_id: str
    href: str
    media_type: str
    data: bytes


@dataclass(slots=True)
class RenderedChapter:
    """Serialized XHTML chapter along with its discovered TOC entries and flags."""

    chapter_id: str
    href: str
    title: str
    xhtml_bytes: bytes
    toc_entries: List[TocEntry] = field(default_factory=list)
    has_svg: bool = False


def _has_any_h1(doc_ir: DocumentIR) -> bool:
    """Return True if any page block in doc_ir is an H1 heading paragraph."""
    for page in doc_ir.pages:
        for block in page.blocks:
            if (
                isinstance(block, Paragraph)
                and block.heading_level == HeadingLevel.H1
                and block.text.strip()
            ):
                return True
    return False


def _derive_chapter_title(
    blocks: Sequence[BlockNode],
    chapter_index: int,
    fallback_prefix: str = "Chapter",
) -> str:
    """Infer a chapter title from its first major heading or fallback label."""
    for block in blocks:
        if isinstance(block, Paragraph) and block.heading_level in (
            HeadingLevel.H1,
            HeadingLevel.H2,
            HeadingLevel.H3,
        ):
            txt = block.text.strip()
            if txt:
                return txt
    return f"{fallback_prefix} {chapter_index}"


def split_document_into_chapters(
    doc_ir: DocumentIR,
    strategy: Union[ChapterSplitStrategy, str] = ChapterSplitStrategy.AUTO,
    max_pages_per_chapter: int = 10,
) -> List[ChapterSection]:
    """Split DocumentIR into separate XHTML chapters at H1 or page boundaries.

    Args:
        doc_ir: Source DocumentIR containing one or more pages.
        strategy: 'auto' (H1 if present else page splits for multi-page docs),
            'heading' (split at H1 or max_pages_per_chapter), or 'page' (1 page per chapter).
        max_pages_per_chapter: Safety ceiling on pages grouped into one chapter
            to keep individual XHTML files fast on low-memory e-readers.

    Returns:
        Non-empty list of ChapterSection slices.
    """
    mode = resolve_split_strategy(strategy)
    page_cap = max(1, int(max_pages_per_chapter))

    if not doc_ir.pages:
        return []

    use_page_splits = mode == ChapterSplitStrategy.PAGE or (
        mode == ChapterSplitStrategy.AUTO
        and len(doc_ir.pages) > 1
        and not _has_any_h1(doc_ir)
    )

    sections: List[ChapterSection] = []

    if use_page_splits:
        for idx, page in enumerate(doc_ir.pages, start=1):
            title = _derive_chapter_title(page.blocks, idx, fallback_prefix="Page")
            sections.append(
                ChapterSection(
                    index=idx,
                    chapter_id=f"ch{idx}",
                    href=f"Text/chapter_{idx}.xhtml",
                    title=title,
                    blocks=list(page.blocks),
                    page_numbers=[page.page_number],
                )
            )
        return sections

    # Heading-driven splitting (with max_pages_per_chapter safety cap)
    curr_blocks: List[BlockNode] = []
    curr_pages: List[int] = []

    def _flush() -> None:
        if not curr_blocks and not curr_pages:
            return
        ch_idx = len(sections) + 1
        title = _derive_chapter_title(curr_blocks, ch_idx, fallback_prefix="Chapter")
        sections.append(
            ChapterSection(
                index=ch_idx,
                chapter_id=f"ch{ch_idx}",
                href=f"Text/chapter_{ch_idx}.xhtml",
                title=title,
                blocks=list(curr_blocks),
                page_numbers=list(curr_pages),
            )
        )
        curr_blocks.clear()
        curr_pages.clear()

    for page in doc_ir.pages:
        if curr_blocks and len(curr_pages) >= page_cap:
            _flush()

        if page.page_number not in curr_pages:
            curr_pages.append(page.page_number)

        for block in page.blocks:
            is_h1 = (
                isinstance(block, Paragraph)
                and block.heading_level == HeadingLevel.H1
                and bool(block.text.strip())
            )
            if is_h1 and curr_blocks:
                _flush()
                curr_pages.append(page.page_number)
            curr_blocks.append(block)

    _flush()

    if not sections:
        sections.append(
            ChapterSection(
                index=1,
                chapter_id="ch1",
                href="Text/chapter_1.xhtml",
                title=doc_ir.metadata.get("Title", "").strip() or "Chapter 1",
                blocks=[],
                page_numbers=[doc_ir.pages[0].page_number],
            )
        )

    return sections


class ChapterRenderer:
    """Strict XHTML 1.1 / EPUB 3.3 renderer for individual ChapterSection objects."""

    __slots__ = (
        "language",
        "stylesheet_href",
        "max_toc_level",
        "_image_counter",
        "_heading_counter",
        "extracted_images",
    )

    def __init__(
        self,
        language: str = "en",
        stylesheet_href: Optional[str] = "../Styles/style.css",
        max_toc_level: int = 3,
    ) -> None:
        self.language: str = language.strip().replace("_", "-") or "en"
        self.stylesheet_href: Optional[str] = stylesheet_href
        self.max_toc_level: int = max(1, min(6, max_toc_level))
        self._image_counter: int = 0
        self._heading_counter: int = 0
        self.extracted_images: List[ExtractedImageAsset] = []

    def render_chapter(self, chapter: ChapterSection) -> RenderedChapter:
        """Render a ChapterSection into a valid EPUB 3.3 XHTML document."""
        chapter_toc: List[TocEntry] = []
        has_svg_flag = [False]
        body_lines = self._render_blocks(
            chapter.blocks,
            chapter_href=chapter.href,
            toc_out=chapter_toc,
            has_svg_flag=has_svg_flag,
            indent="      ",
        )

        if not body_lines:
            body_lines.append("      <p>&#160;</p>")

        head_lines: List[str] = [
            "  <head>",
            '    <meta charset="utf-8"/>',
            f"    <title>{xml_escape(chapter.title)}</title>",
        ]
        if self.stylesheet_href:
            head_lines.append(
                f'    <link rel="stylesheet" type="text/css" href="{xml_escape(self.stylesheet_href)}"/>'
            )
        head_lines.append("  </head>")

        lines: List[str] = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            "<!DOCTYPE html>",
            (
                f'<html xmlns="{XHTML_NS}" xmlns:epub="{EPUB_OPS_NS}" '
                f'xml:lang="{xml_escape(self.language)}" lang="{xml_escape(self.language)}">'
            ),
        ]
        lines.extend(head_lines)
        lines.append("  <body>")
        lines.append(f'    <section epub:type="chapter" id="{xml_escape(chapter.chapter_id)}">')
        lines.extend(body_lines)
        lines.append("    </section>")
        lines.append("  </body>")
        lines.append("</html>")

        return RenderedChapter(
            chapter_id=chapter.chapter_id,
            href=chapter.href,
            title=chapter.title,
            xhtml_bytes="\n".join(lines).encode("utf-8"),
            toc_entries=chapter_toc,
            has_svg=has_svg_flag[0],
        )

    def _render_blocks(
        self,
        blocks: Sequence[BlockNode],
        chapter_href: str,
        toc_out: List[TocEntry],
        has_svg_flag: List[bool],
        indent: str,
    ) -> List[str]:
        """Render a sequence of BlockNodes, grouping contiguous list items."""
        lines: List[str] = []
        i = 0
        n = len(blocks)

        while i < n:
            block = blocks[i]
            if isinstance(block, Paragraph):
                is_list, list_type = self._detect_list_type(block)
                if is_list and list_type:
                    items: List[Paragraph] = []
                    while i < n:
                        cand = blocks[i]
                        if isinstance(cand, Paragraph):
                            c_is_list, c_type = self._detect_list_type(cand)
                            if c_is_list and c_type == list_type:
                                items.append(cand)
                                i += 1
                                continue
                        break
                    lines.append(self._render_list(items, list_type, indent=indent))
                    continue

                rendered_p = self._render_paragraph(
                    block,
                    chapter_href=chapter_href,
                    toc_out=toc_out,
                    indent=indent,
                )
                if rendered_p:
                    lines.append(rendered_p)
                i += 1
            elif isinstance(block, Table):
                tbl_xhtml = self._render_table(block, indent=indent)
                if tbl_xhtml:
                    lines.append(tbl_xhtml)
                i += 1
            elif isinstance(block, ImageBlock):
                lines.append(self._render_image(block, indent=indent))
                i += 1
            elif isinstance(block, VectorBlock):
                vec_xhtml = self._render_vector(block, indent=indent)
                if vec_xhtml:
                    has_svg_flag[0] = True
                    lines.append(vec_xhtml)
                i += 1
            else:
                i += 1

        return lines

    def _detect_list_type(self, p: Paragraph) -> Tuple[bool, Optional[str]]:
        """Detect whether a Paragraph is an unordered ('ul') or ordered ('ol') list item."""
        if p.heading_level is not None:
            return False, None
        if p.list_marker:
            marker = p.list_marker.strip()
            if marker.endswith(".") or marker.endswith(")") or marker.isdigit():
                return True, "ol"
            return True, "ul"

        txt = p.text
        if not txt.strip():
            return False, None
        if _UNORDERED_BULLET_RE.match(txt):
            return True, "ul"
        if _ORDERED_NUMBER_RE.match(txt):
            return True, "ol"
        return False, None

    def _render_list(
        self,
        items: Sequence[Paragraph],
        list_type: str,
        indent: str,
    ) -> str:
        """Render grouped list paragraphs into <ul> or <ol> XHTML."""
        lines: List[str] = [f"{indent}<{list_type}>"]
        for p in items:
            content_html = self._render_list_item_runs(p)
            lines.append(f"{indent}  <li>{content_html}</li>")
        lines.append(f"{indent}</{list_type}>")
        return "\n".join(lines)

    def _render_list_item_runs(self, p: Paragraph) -> str:
        """Render runs of a list item while stripping leading bullet/number prefixes."""
        if not p.runs:
            return ""
        first_text = p.runs[0].text
        prefix = ""
        if p.list_marker and first_text.startswith(p.list_marker):
            prefix = p.list_marker
        else:
            m_ul = _UNORDERED_BULLET_RE.match(first_text)
            if m_ul:
                prefix = m_ul.group(0)
            else:
                m_ol = _ORDERED_NUMBER_RE.match(first_text)
                if m_ol:
                    prefix = m_ol.group(0)

        parts: List[str] = []
        for idx, run in enumerate(p.runs):
            if idx == 0 and prefix:
                parts.append(self._render_run(run, override_text=first_text[len(prefix) :]))
            else:
                parts.append(self._render_run(run))
        return "".join(parts).strip()

    def _render_paragraph(
        self,
        p: Paragraph,
        chapter_href: str,
        toc_out: List[TocEntry],
        indent: str,
    ) -> str:
        """Render a Paragraph into <h1-h6> or <p> with anchor IDs for H1-H3 TOC entries."""
        runs_xhtml = "".join(self._render_run(r) for r in p.runs)
        if not runs_xhtml.strip():
            return ""

        tag = "p"
        attrs: List[str] = []
        if p.heading_level is not None:
            lvl = max(1, min(6, p.heading_level.value))
            tag = f"h{lvl}"
            if lvl <= self.max_toc_level:
                self._heading_counter += 1
                anchor_id = f"heading-{self._heading_counter}"
                attrs.append(f'id="{anchor_id}"')
                toc_out.append(
                    TocEntry(
                        title=p.text.strip(),
                        href=f"{chapter_href}#{anchor_id}",
                        level=lvl,
                        entry_id=anchor_id,
                    )
                )

        if p.alignment == Alignment.CENTER:
            attrs.append('style="text-align: center;"')
        elif p.alignment == Alignment.RIGHT:
            attrs.append('style="text-align: right;"')
        elif p.alignment == Alignment.JUSTIFIED:
            attrs.append('style="text-align: justify;"')

        attr_str = f" {' '.join(attrs)}" if attrs else ""
        return f"{indent}<{tag}{attr_str}>{runs_xhtml}</{tag}>"

    def _render_run(self, r: TextRun, override_text: Optional[str] = None) -> str:
        """Render an inline TextRun into strict XHTML markup."""
        raw_text = override_text if override_text is not None else r.text
        if not raw_text:
            return ""

        escaped = xml_escape(raw_text).replace("\n", "<br/>")
        fn_clean = r.font_name.lower().replace("-", "").replace("_", "").replace(" ", "")
        is_mono = any(k in fn_clean for k in _MONOSPACE_KEYWORDS)

        content = escaped
        if is_mono:
            content = f"<code>{content}</code>"
        if r.is_bold:
            content = f"<strong>{content}</strong>"
        if r.is_italic:
            content = f"<em>{content}</em>"
        if r.is_underline:
            content = f"<u>{content}</u>"
        if r.is_strikethrough:
            content = f"<s>{content}</s>"
        if r.baseline_offset > 0.5:
            content = f"<sup>{content}</sup>"
        elif r.baseline_offset < -0.5:
            content = f"<sub>{content}</sub>"

        styles: List[str] = []
        if r.color and (r.color.r, r.color.g, r.color.b) != (0, 0, 0):
            styles.append(f"color: #{color_to_hex(r.color)};")
        if styles:
            content = f'<span style="{" ".join(styles)}">{content}</span>'

        stripped = raw_text.strip()
        if _URL_RE.match(stripped) and not is_mono:
            content = f'<a href="{xml_escape(stripped)}">{content}</a>'

        return content

    def _render_table(self, table: Table, indent: str) -> str:
        """Render a Table node into valid XHTML <table> markup."""
        if not table.rows:
            return ""

        lines: List[str] = [f"{indent}<table>"]
        header_rows: List[TableRow] = [r for r in table.rows if r.is_header]
        body_rows: List[TableRow] = [r for r in table.rows if not r.is_header]

        if header_rows:
            lines.append(f"{indent}  <thead>")
            for row in header_rows:
                lines.append(self._render_table_row(row, is_header=True, indent=indent + "    "))
            lines.append(f"{indent}  </thead>")

        if body_rows:
            lines.append(f"{indent}  <tbody>")
            for row in body_rows:
                lines.append(self._render_table_row(row, is_header=False, indent=indent + "    "))
            lines.append(f"{indent}  </tbody>")

        lines.append(f"{indent}</table>")
        return "\n".join(lines)

    def _render_table_row(self, row: TableRow, is_header: bool, indent: str) -> str:
        """Render a TableRow into <tr> with <th>/<td> cells."""
        tag = "th" if is_header else "td"
        lines: List[str] = [f"{indent}<tr>"]
        for cell in row.cells:
            lines.append(self._render_table_cell(cell, tag=tag, indent=indent + "  "))
        lines.append(f"{indent}</tr>")
        return "\n".join(lines)

    def _render_table_cell(self, cell: TableCell, tag: str, indent: str) -> str:
        """Render a TableCell into <th> or <td> preserving col_span and row_span."""
        attrs: List[str] = []
        if cell.col_span > 1:
            attrs.append(f'colspan="{cell.col_span}"')
        if cell.row_span > 1:
            attrs.append(f'rowspan="{cell.row_span}"')
        attr_str = f" {' '.join(attrs)}" if attrs else ""

        parts: List[str] = []
        for block in cell.content:
            if isinstance(block, Paragraph):
                runs = "".join(self._render_run(r) for r in block.runs).strip()
                if runs:
                    parts.append(runs)
        inner = "<br/>".join(parts) if parts else "&#160;"
        return f"{indent}<{tag}{attr_str}>{inner}</{tag}>"

    def _render_image(self, img: ImageBlock, indent: str) -> str:
        """Package an ImageBlock as an OEBPS asset and emit a relative XHTML <figure>."""
        self._image_counter += 1
        idx = self._image_counter
        img.sync_format()
        ext = img.file_extension
        filename = f"img_{idx}{ext}"
        oebps_href = f"Images/{filename}"
        media_type = img.mime_type or infer_epub_media_type(oebps_href)
        if media_type == "application/octet-stream":
            media_type = MEDIA_TYPE_PNG

        self.extracted_images.append(
            ExtractedImageAsset(
                item_id=f"img_{idx}",
                href=oebps_href,
                media_type=media_type,
                data=img.image_bytes,
            )
        )

        alt_text = img.alt_text.strip() if img.alt_text else f"Image {idx}"
        alt_esc = xml_escape(alt_text)
        rel_src = f"../Images/{filename}"
        lines = [
            f"{indent}<figure>",
            f'{indent}  <img src="{xml_escape(rel_src)}" alt="{alt_esc}"/>',
        ]
        if img.alt_text and img.alt_text.strip():
            lines.append(f"{indent}  <figcaption>{alt_esc}</figcaption>")
        lines.append(f"{indent}</figure>")
        return "\n".join(lines)

    def _render_vector(self, vec: VectorBlock, indent: str) -> str:
        """Render a VectorBlock as an inline SVG element."""
        if not vec.svg_path:
            return ""
        w = max(1.0, vec.bbox.width) if vec.bbox else 100.0
        h = max(1.0, vec.bbox.height) if vec.bbox else 100.0
        vx = vec.bbox.x0 if vec.bbox else 0.0
        vy = vec.bbox.y0 if vec.bbox else 0.0
        fill = f"#{color_to_hex(vec.fill_color)}" if vec.fill_color else "none"
        stroke = f"#{color_to_hex(vec.stroke_color)}" if vec.stroke_color else "none"
        sw = f"{vec.stroke_width:.2f}"
        return (
            f"{indent}<figure>\n"
            f'{indent}  <svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="{vx:.2f} {vy:.2f} {w:.2f} {h:.2f}" width="{w:.2f}" height="{h:.2f}">\n'
            f'{indent}    <path d="{xml_escape(vec.svg_path)}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>\n'
            f"{indent}  </svg>\n"
            f"{indent}</figure>"
        )


__all__ = [
    "DEFAULT_EPUB_CSS",
    "ChapterSplitStrategy",
    "ChapterSection",
    "ExtractedImageAsset",
    "RenderedChapter",
    "ChapterRenderer",
    "resolve_split_strategy",
    "split_document_into_chapters",
]
