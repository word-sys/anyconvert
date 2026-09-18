"""
Document Layout Analysis (DLA) engine for anyconvert.
Deconstructs PDF pages into structured reading-order blocks, paragraphs, headings, and lists.
"""

from collections import Counter
import re
from typing import Dict, List, Optional, Tuple, Union
from pathlib import Path

import pymupdf

from anyconvert.analysis.images import extract_page_images
from anyconvert.core.models import (
    Block,
    Color,
    Document,
    Hyperlink,
    ImageBlock,
    Page,
    ParagraphBlock,
    Point,
    Rect,
    TextLine,
    TextRun,
    TOCItem,
    VectorShapeBlock,
)
from anyconvert.core.options import ConversionOptions

# Regex patterns for list detection
BULLET_PATTERN = re.compile(
    r"^([\u2022\u25cf\u25cb\u25aa\u25ab\u25fe\u25fd\u2219\u2043\u00b7\uf0b7\u25a0\u25a1\u25c6\u25c7\u25b6\u2023\-\*•·])\s*(.*)"
)
NUMBERED_LIST_PATTERN = re.compile(r"^(\d+[\.\)]|[a-zA-Z][\.\)])\s+(.*)")


def parse_color_int(color_val: int, alpha: float = 1.0) -> Color:
    """Convert an integer RGB value (e.g. from PyMuPDF span) into a Color object."""
    r = (color_val >> 16) & 0xFF
    g = (color_val >> 8) & 0xFF
    b = color_val & 0xFF
    return Color(r, g, b, alpha)


def is_span_bold(span: dict) -> bool:
    """Determine if a text span is bold from flags or font name."""
    flags = span.get("flags", 0)
    if flags & (1 << 4):
        return True
    font_lower = span.get("font", "").lower()
    return any(w in font_lower for w in ("bold", "heavy", "black", "semibold", "medium"))


def is_span_italic(span: dict) -> bool:
    """Determine if a text span is italic from flags or font name."""
    flags = span.get("flags", 0)
    if flags & (1 << 1):
        return True
    font_lower = span.get("font", "").lower()
    return any(w in font_lower for w in ("italic", "oblique"))


def detect_columns(blocks_dict: List[dict], page_width: float) -> List[Tuple[float, float]]:
    """
    Detect multi-column layout boundaries (e.g. 2-column or 3-column documents).
    Returns a list of (x_start, x_end) ranges for each column.
    """
    if not blocks_dict or len(blocks_dict) < 4:
        return [(0.0, page_width)]

    # Collect horizontal centers of text blocks
    centers = []
    for b in blocks_dict:
        if b.get("type") == 0:  # Text block
            bbox = b.get("bbox", (0, 0, 0, 0))
            w = bbox[2] - bbox[0]
            # Ignore wide blocks spanning more than 60% of the page (e.g. headers/titles)
            if w < page_width * 0.55:
                centers.append((bbox[0] + bbox[2]) / 2.0)

    if not centers or len(centers) < 4:
        return [(0.0, page_width)]

    # Check for 2-column distribution (left half vs right half)
    mid_page = page_width / 2.0
    left_centers = [c for c in centers if c < mid_page]
    right_centers = [c for c in centers if c >= mid_page]

    if len(left_centers) >= 3 and len(right_centers) >= 3:
        # Two column layout detected
        return [(0.0, mid_page), (mid_page, page_width)]

    return [(0.0, page_width)]


def sort_blocks_in_reading_order(
    blocks_dict: List[dict], columns: List[Tuple[float, float]]
) -> List[dict]:
    """
    Sort blocks respecting column flow:
    - Full-width blocks (spanning multiple columns) are ordered by vertical y position.
    - Columnar blocks are grouped by column left-to-right, and vertically top-to-bottom.
    """
    if len(columns) <= 1:
        return sorted(blocks_dict, key=lambda b: (b.get("bbox", (0, 0, 0, 0))[1], b.get("bbox", (0, 0, 0, 0))[0]))

    def get_sort_key(b: dict) -> Tuple[int, float, float]:
        bbox = b.get("bbox", (0, 0, 0, 0))
        x0, y0, x1, y1 = bbox
        width = x1 - x0

        # Full-width header or banner: process in column 0 by vertical position
        if width > (columns[0][1] - columns[0][0]) * 1.3:
            col_idx = 0
        else:
            center_x = (x0 + x1) / 2.0
            col_idx = 0
            for i, (c_start, c_end) in enumerate(columns):
                if c_start <= center_x <= c_end:
                    col_idx = i
                    break
        return (col_idx, y0, x0)

    return sorted(blocks_dict, key=get_sort_key)


def compute_body_font_size(doc: pymupdf.Document) -> float:
    """Find the most prevalent font size across the document (the body text size)."""
    font_sizes: Counter[float] = Counter()
    sample_pages = range(min(5, doc.page_count))

    for p_idx in sample_pages:
        page = doc[p_idx]
        d = page.get_text("dict")
        for block in d.get("blocks", []):
            if block.get("type") == 0:
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = span.get("text", "").strip()
                        if text:
                            size = round(span.get("size", 11.0), 1)
                            font_sizes[size] += len(text)

    if font_sizes:
        return font_sizes.most_common(1)[0][0]
    return 11.0


def extract_page_links(page: pymupdf.Page) -> List[Hyperlink]:
    """Extract all active clickable links on the page."""
    links: List[Hyperlink] = []
    try:
        raw_links = page.get_links()
        for lnk in raw_links:
            r = lnk.get("from")
            if r:
                rect = Rect(r.x0, r.y0, r.x1, r.y1)
                uri = lnk.get("uri")
                target_page = lnk.get("page")
                links.append(Hyperlink(bbox=rect, uri=uri, target_page=target_page))
    except Exception:
        pass
    return links


def find_link_for_bbox(links: List[Hyperlink], bbox: Rect) -> Optional[str]:
    """Check if a text run falls inside a known hyperlink rectangle."""
    for link in links:
        if link.uri and link.bbox.intersects(bbox):
            return link.uri
    return None


def extract_page_layout(
    doc: pymupdf.Document,
    page: pymupdf.Page,
    options: ConversionOptions,
    body_font_size: float = 11.0,
) -> Page:
    """
    Parse a single PDF page into a structured IR Page object.
    """
    page_rect = page.rect
    page_model = Page(
        page_number=page.number,
        width=page_rect.width,
        height=page_rect.height,
        rotation=page.rotation,
    )

    links = extract_page_links(page)
    page_model.links = links

    # 1. Extract raw blocks from PyMuPDF dict
    page_dict = page.get_text("dict")
    raw_blocks = page_dict.get("blocks", [])

    # 2. Detect column structure and sort blocks
    columns = detect_columns(raw_blocks, page_rect.width)
    sorted_blocks = sort_blocks_in_reading_order(raw_blocks, columns)

    # 3. Process text blocks into paragraphs, headings, and lists
    for raw_block in sorted_blocks:
        b_type = raw_block.get("type", 0)

        if b_type == 0:  # Text block
            b_rect = raw_block.get("bbox", (0, 0, 0, 0))
            block_bbox = Rect(b_rect[0], b_rect[1], b_rect[2], b_rect[3])
            lines: List[TextLine] = []

            for raw_line in raw_block.get("lines", []):
                l_rect = raw_line.get("bbox", (0, 0, 0, 0))
                line_bbox = Rect(l_rect[0], l_rect[1], l_rect[2], l_rect[3])
                runs: List[TextRun] = []

                for raw_span in raw_line.get("spans", []):
                    span_text = raw_span.get("text", "")
                    if not span_text:
                        continue

                    s_rect = raw_span.get("bbox", (0, 0, 0, 0))
                    span_bbox = Rect(s_rect[0], s_rect[1], s_rect[2], s_rect[3])

                    uri = find_link_for_bbox(links, span_bbox)

                    run = TextRun(
                        text=span_text,
                        bbox=span_bbox,
                        font_name=raw_span.get("font", "sans-serif"),
                        font_size=raw_span.get("size", 11.0),
                        is_bold=is_span_bold(raw_span),
                        is_italic=is_span_italic(raw_span),
                        color=parse_color_int(raw_span.get("color", 0), raw_span.get("alpha", 1.0)),
                        hyperlink_uri=uri,
                    )
                    runs.append(run)

                if runs:
                    lines.append(
                        TextLine(
                            runs=runs,
                            bbox=line_bbox,
                            baseline=raw_line.get("baseline", line_bbox.y1),
                        )
                    )

            if lines:
                para = ParagraphBlock(lines=lines, bbox=block_bbox)

                # Determine heading level
                if options.detect_headings:
                    first_run = lines[0].runs[0]
                    font_size = first_run.font_size
                    is_bold = first_run.is_bold

                    if font_size >= body_font_size * 1.8:
                        para.heading_level = 1
                    elif font_size >= body_font_size * 1.4:
                        para.heading_level = 2
                    elif font_size >= body_font_size * 1.2 or (is_bold and font_size > body_font_size * 1.05):
                        para.heading_level = 3
                    elif font_size >= body_font_size * 1.1:
                        para.heading_level = 4

                # Determine bullet / list item status
                full_text = para.text
                bullet_match = BULLET_PATTERN.match(full_text)
                if bullet_match:
                    para.is_list_item = True
                    para.list_bullet = bullet_match.group(1)
                else:
                    numbered_match = NUMBERED_LIST_PATTERN.match(full_text)
                    if numbered_match:
                        para.is_list_item = True
                        para.list_bullet = numbered_match.group(1)

                page_model.blocks.append(para)

    # 4. Extract placed images if requested
    if options.extract_images:
        images = extract_page_images(doc, page)
        page_model.blocks.extend(images)

    return page_model


def extract_document_layout(
    source: Union[str, Path, bytes, pymupdf.Document],
    options: Optional[ConversionOptions] = None,
) -> Document:
    """
    Parse an entire PDF document into an Intermediate Representation Document.
    """
    opts = options or ConversionOptions()

    close_doc_on_finish = False
    if isinstance(source, pymupdf.Document):
        doc = source
    elif isinstance(source, bytes):
        doc = pymupdf.open(stream=source, filetype="pdf")
        close_doc_on_finish = True
    else:
        doc = pymupdf.open(str(source))
        close_doc_on_finish = True

    try:
        body_font_size = compute_body_font_size(doc)
        total_pages = doc.page_count
        pages_to_process = opts.parse_pages(total_pages)

        ir_doc = Document(metadata=doc.metadata or {})

        # Extract Table of Contents if available
        try:
            raw_toc = doc.get_toc()
            for item in raw_toc:
                lvl, title, page_num = item[0], item[1], item[2]
                ir_doc.toc.append(TOCItem(title=title, page=page_num - 1, level=lvl))
        except Exception:
            pass

        for page_idx in pages_to_process:
            if opts.cancellation_token:
                opts.cancellation_token.check_cancelled()

            if opts.progress_callback:
                opts.progress_callback(page_idx + 1, total_pages, f"Analyzing page layout {page_idx + 1}")

            page = doc[page_idx]
            ir_page = extract_page_layout(doc, page, opts, body_font_size=body_font_size)
            ir_doc.pages.append(ir_page)

        return ir_doc

    finally:
        if close_doc_on_finish:
            doc.close()
