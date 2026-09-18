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
from anyconvert.analysis.tables import detect_page_tables, filter_blocks_in_tables
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


def parse_rgb_tuple(rgb: Optional[Tuple[float, float, float]], alpha: float = 1.0) -> Optional[Color]:
    """Convert a PyMuPDF drawing color tuple (r, g, b float) to Color."""
    if not rgb:
        return None
    r = int(max(0.0, min(1.0, rgb[0])) * 255)
    g = int(max(0.0, min(1.0, rgb[1])) * 255)
    b = int(max(0.0, min(1.0, rgb[2])) * 255)
    return Color(r, g, b, alpha)


def extract_page_drawings(page: pymupdf.Page) -> List[VectorShapeBlock]:
    """Extract vector graphics from the PDF page."""
    drawings: List[VectorShapeBlock] = []
    try:
        for p in page.get_drawings():
            rect = p.get("rect")
            if not rect:
                continue
            r = Rect(rect.x0, rect.y0, rect.x1, rect.y1)
            
            # Skip tiny artifacts
            if r.width < 1.0 and r.height < 1.0:
                continue
                
            fill = parse_rgb_tuple(p.get("fill"), p.get("fill_opacity", 1.0))
            stroke = parse_rgb_tuple(p.get("color"), p.get("color_opacity", 1.0))
            width = p.get("width", 1.0)
            
            shape_type = "rect"
            if r.width <= 2.0 or r.height <= 2.0:
                shape_type = "line"
                
            drawings.append(
                VectorShapeBlock(
                    bbox=r,
                    shape_type=shape_type,
                    stroke_color=stroke,
                    fill_color=fill,
                    stroke_width=width,
                )
            )
    except Exception:
        pass
    return drawings


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


def compute_page_body_font_size(page_dict: dict, fallback: float = 11.0) -> float:
    """Find the most prevalent font size on a single page, falling back to document size."""
    font_sizes: Counter[float] = Counter()
    for block in page_dict.get("blocks", []):
        if block.get("type") == 0:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if text:
                        size = round(span.get("size", fallback), 1)
                        font_sizes[size] += len(text)

    if font_sizes:
        total_len = sum(font_sizes.values())
        most_common_size, count = font_sizes.most_common(1)[0]
        if total_len >= 60 and count >= total_len * 0.25:
            return most_common_size
    return fallback


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


def _build_paragraph(
    para_lines: List[TextLine],
    options: ConversionOptions,
    body_font_size: float,
) -> Optional[ParagraphBlock]:
    """Construct a ParagraphBlock from lines with heading and list detection."""
    if not para_lines:
        return None

    p_bbox = para_lines[0].bbox
    for l in para_lines[1:]:
        p_bbox = p_bbox.union(l.bbox)

    para = ParagraphBlock(lines=para_lines, bbox=p_bbox)
    para_text = para.text.strip()
    if not para_text:
        return None

    first_run = para_lines[0].runs[0]
    font_size = first_run.font_size
    is_bold = first_run.is_bold

    if options.detect_headings:
        is_candidate_heading = (
            len(para_lines) <= 2
            and len(para_text) <= 120
            and not para_text.endswith((",", ";", ":", "-", "...", "and", "or", "the", "to", "of", "in"))
        )
        if is_candidate_heading:
            if font_size >= body_font_size * 1.75:
                para.heading_level = 1
            elif font_size >= body_font_size * 1.35:
                para.heading_level = 2
            elif font_size >= body_font_size * 1.18 and (is_bold or font_size > body_font_size * 1.25):
                para.heading_level = 3
            elif font_size >= body_font_size * 1.12 and is_bold:
                para.heading_level = 4

    bullet_match = BULLET_PATTERN.match(para_text)
    if bullet_match:
        para.is_list_item = True
        para.list_bullet = bullet_match.group(1)
    else:
        numbered_match = NUMBERED_LIST_PATTERN.match(para_text)
        if numbered_match:
            para.is_list_item = True
            para.list_bullet = numbered_match.group(1)

    return para


def _sort_single_column_blocks(blocks: List[Block]) -> List[Block]:
    """Sort blocks within a column or page using horizontal band grouping."""
    if len(blocks) <= 1:
        return blocks

    sorted_by_y = sorted(blocks, key=lambda b: b.bbox.y0)
    bands: List[List[Block]] = []

    for block in sorted_by_y:
        placed = False
        r = block.bbox

        for band in bands:
            has_overlap = False
            for b in band:
                b_r = b.bbox
                v_overlap = max(0.0, min(r.y1, b_r.y1) - max(r.y0, b_r.y0))
                min_h = min(r.height, b_r.height)
                h_overlap = max(0.0, min(r.x1, b_r.x1) - max(r.x0, b_r.x0))
                min_w = min(r.width, b_r.width)

                if min_h > 0 and (v_overlap / min_h > 0.35 or abs(r.y0 - b_r.y0) < 16.0):
                    if min_w == 0 or (h_overlap / min_w < 0.5):
                        has_overlap = True
                        break

            if has_overlap:
                band.append(block)
                placed = True
                break

        if not placed:
            bands.append([block])

    bands.sort(key=lambda band: min(b.bbox.y0 for b in band))

    result: List[Block] = []
    for band in bands:
        band.sort(key=lambda b: b.bbox.x0)
        result.extend(band)

    return result


def sort_page_blocks(
    blocks: List[Block],
    columns: Optional[List[Tuple[float, float]]] = None,
) -> List[Block]:
    """Sort page blocks in logical reading order respecting columns and horizontal bands."""
    if len(blocks) <= 1:
        return blocks

    if not columns or len(columns) <= 1:
        return _sort_single_column_blocks(blocks)

    col_width = columns[0][1] - columns[0][0]
    full_width_blocks: List[Block] = []
    col_blocks: Dict[int, List[Block]] = {i: [] for i in range(len(columns))}

    for b in blocks:
        w = b.bbox.width
        if w > col_width * 1.3:
            full_width_blocks.append(b)
        else:
            center_x = (b.bbox.x0 + b.bbox.x1) / 2.0
            col_idx = 0
            for i, (c_start, c_end) in enumerate(columns):
                if c_start <= center_x <= c_end:
                    col_idx = i
                    break
            col_blocks[col_idx].append(b)

    if not full_width_blocks:
        ordered: List[Block] = []
        for i in sorted(col_blocks.keys()):
            ordered.extend(_sort_single_column_blocks(col_blocks[i]))
        return ordered

    all_sorted: List[Block] = []
    full_width_sorted = sorted(full_width_blocks, key=lambda b: b.bbox.y0)

    for i in col_blocks:
        col_blocks[i] = _sort_single_column_blocks(col_blocks[i])

    current_col_pointers = {i: 0 for i in col_blocks}
    for fw in full_width_sorted:
        fw_y = fw.bbox.y0
        for i in sorted(col_blocks.keys()):
            while current_col_pointers[i] < len(col_blocks[i]):
                cb = col_blocks[i][current_col_pointers[i]]
                if cb.bbox.y0 < fw_y:
                    all_sorted.append(cb)
                    current_col_pointers[i] += 1
                else:
                    break
        all_sorted.append(fw)

    for i in sorted(col_blocks.keys()):
        while current_col_pointers[i] < len(col_blocks[i]):
            all_sorted.append(col_blocks[i][current_col_pointers[i]])
            current_col_pointers[i] += 1

    return all_sorted


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

    page_dict = page.get_text("dict")
    page_body_size = compute_page_body_font_size(page_dict, fallback=body_font_size)
    raw_blocks = page_dict.get("blocks", [])

    columns = detect_columns(raw_blocks, page_rect.width)
    sorted_blocks = sort_blocks_in_reading_order(raw_blocks, columns)

    for raw_block in sorted_blocks:
        b_type = raw_block.get("type", 0)

        if b_type == 0:  # Text block
            b_rect = raw_block.get("bbox", (0, 0, 0, 0))
            block_bbox = Rect(b_rect[0], b_rect[1], b_rect[2], b_rect[3])
            raw_lines = raw_block.get("lines", [])
            extracted_lines: List[TextLine] = []

            for raw_line in raw_lines:
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
                    extracted_lines.append(
                        TextLine(
                            runs=runs,
                            bbox=line_bbox,
                            baseline=raw_line.get("baseline", line_bbox.y1),
                        )
                    )

            # Split lines into distinct paragraphs by vertical gaps and blank lines
            current_para_lines: List[TextLine] = []
            for line in extracted_lines:
                line_text = line.text.strip()
                if not line_text:
                    if current_para_lines:
                        p = _build_paragraph(current_para_lines, options, page_body_size)
                        if p:
                            page_model.blocks.append(p)
                        current_para_lines = []
                    continue

                if current_para_lines:
                    prev_line = current_para_lines[-1]
                    gap = line.bbox.y0 - prev_line.bbox.y1
                    line_h = max(prev_line.bbox.height, 10.0)

                    if gap > max(line_h * 0.45, 6.0):
                        p = _build_paragraph(current_para_lines, options, page_body_size)
                        if p:
                            page_model.blocks.append(p)
                        current_para_lines = [line]
                        continue

                current_para_lines.append(line)

            if current_para_lines:
                p = _build_paragraph(current_para_lines, options, page_body_size)
                if p:
                    page_model.blocks.append(p)

    if options.detect_tables:
        tables = detect_page_tables(page, options)
        if tables:
            page_model.blocks = filter_blocks_in_tables(page_model.blocks, tables)
            page_model.blocks.extend(tables)

    if options.extract_images:
        images = extract_page_images(doc, page)
        page_model.blocks.extend(images)

    drawings = extract_page_drawings(page)
    standalone_drawings = []
    
    for d in drawings:
        if d.fill_color and d.bbox.width > 10 and d.bbox.height > 10:
            is_bg = False
            for b in page_model.blocks:
                if isinstance(b, ParagraphBlock):
                    # Check if drawing mostly overlaps the paragraph
                    h_overlap = max(0.0, min(d.bbox.x1, b.bbox.x1) - max(d.bbox.x0, b.bbox.x0))
                    v_overlap = max(0.0, min(d.bbox.y1, b.bbox.y1) - max(d.bbox.y0, b.bbox.y0))
                    overlap_area = h_overlap * v_overlap
                    
                    if b.bbox.area > 0 and (overlap_area / b.bbox.area) > 0.8:
                        b.background_color = d.fill_color
                        is_bg = True
            
            if not is_bg:
                standalone_drawings.append(d)
        else:
            standalone_drawings.append(d)
            
    page_model.blocks.extend(standalone_drawings)

    page_model.blocks = sort_page_blocks(page_model.blocks, columns=columns)

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
