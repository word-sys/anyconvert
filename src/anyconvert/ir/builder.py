"""Document Intermediate Representation (DIR) builder engine.

Transforms raw content streams, vector paths, raster images, and clustered layout
features into strictly typed, verified DocumentIR and DocumentPage hierarchies.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from anyconvert.common.color import Color
from anyconvert.common.geometry import BoundingBox, Point
from anyconvert.exceptions import IRBuilderError
from anyconvert.ir.model import (
    Alignment as DIRAlignment,
    BlockNode,
    Border,
    DocumentIR,
    DocumentPage,
    HeadingLevel as DIRHeadingLevel,
    ImageBlock,
    PageHeaderFooter,
    Paragraph,
    Table,
    TableCell,
    TableRow,
    TextRun,
    VectorBlock,
)
from anyconvert.ir.validator import validate_document_ir
from anyconvert.layout.cluster import (
    TextLine,
    TextWord,
    cluster_characters_to_words,
    cluster_words_to_lines,
)
from anyconvert.layout.flow import (
    detect_repeating_headers_footers,
    partition_page_flow,
)
from anyconvert.layout.headings import (
    HeadingLevel as LayoutHeadingLevel,
    classify_headings,
    compute_modal_body_font_size,
)
from anyconvert.layout.lists import process_list_paragraphs
from anyconvert.layout.paragraph import (
    Alignment as LayoutAlignment,
    ParagraphCluster,
    cluster_lines_to_paragraphs,
)
from anyconvert.layout.spatial import normalize_bbox_pdf_to_doc
from anyconvert.layout.table import (
    TableLayout,
    detect_borderless_tables,
    detect_tables_from_vectors,
)
from anyconvert.layout.xycut import linearize_reading_order, recursive_xy_cut
from anyconvert.pdf.content.interpreter import (
    ImageElement,
    InterpreterOutput,
    TextElement,
    VectorElement,
)
from anyconvert.pdf.graphics.image import PDFImage
from anyconvert.pdf.xref import XRefResolver
from anyconvert.utils.png import encode_gray_png


# Mapping between layout alignment and DIR alignment
_ALIGN_MAP = {
    LayoutAlignment.LEFT: DIRAlignment.LEFT,
    LayoutAlignment.CENTER: DIRAlignment.CENTER,
    LayoutAlignment.RIGHT: DIRAlignment.RIGHT,
    LayoutAlignment.JUSTIFIED: DIRAlignment.JUSTIFIED,
}

_HEADING_MAP = {
    1: DIRHeadingLevel.H1,
    2: DIRHeadingLevel.H2,
    3: DIRHeadingLevel.H3,
    4: DIRHeadingLevel.H4,
    5: DIRHeadingLevel.H5,
    6: DIRHeadingLevel.H6,
}


def _create_fallback_png() -> bytes:
    """Generate a valid 1x1 transparent PNG fallback."""
    return encode_gray_png(1, 1, b"\x00", bit_depth=8)


def _words_to_runs(words: Sequence[TextWord]) -> List[TextRun]:
    """Coalesce adjacent words sharing identical styling into cohesive TextRuns."""
    if not words:
        return []

    runs: List[TextRun] = []
    curr_text: List[str] = []
    curr_font = words[0].font_name
    curr_size = words[0].font_size
    curr_color = words[0].color
    curr_bold = words[0].is_bold
    curr_italic = words[0].is_italic
    curr_bbox: Optional[BoundingBox] = words[0].bbox

    for i, w in enumerate(words):
        same_style = (
            w.font_name == curr_font
            and abs(w.font_size - curr_size) <= 0.1
            and w.color == curr_color
            and w.is_bold == curr_bold
            and w.is_italic == curr_italic
        )

        word_str = w.text + (" " if i < len(words) - 1 else "")

        if same_style:
            curr_text.append(word_str)
            if curr_bbox is not None:
                curr_bbox = curr_bbox.union(w.bbox)
        else:
            runs.append(
                TextRun(
                    text="".join(curr_text),
                    font_name=curr_font,
                    font_size=curr_size,
                    color=curr_color,
                    is_bold=curr_bold,
                    is_italic=curr_italic,
                    bbox=curr_bbox,
                )
            )
            curr_text = [word_str]
            curr_font = w.font_name
            curr_size = w.font_size
            curr_color = w.color
            curr_bold = w.is_bold
            curr_italic = w.is_italic
            curr_bbox = w.bbox

    if curr_text:
        runs.append(
            TextRun(
                text="".join(curr_text),
                font_name=curr_font,
                font_size=curr_size,
                color=curr_color,
                is_bold=curr_bold,
                is_italic=curr_italic,
                bbox=curr_bbox,
            )
        )

    return runs


def _paragraph_cluster_to_dir(p: ParagraphCluster) -> Paragraph:
    """Convert a layout ParagraphCluster into a DIR Paragraph."""
    all_words: List[TextWord] = []
    for line in p.lines:
        all_words.extend(line.words)

    runs = _words_to_runs(all_words)
    dir_align = _ALIGN_MAP.get(p.alignment, DIRAlignment.LEFT)
    dir_heading = _HEADING_MAP.get(p.heading_level) if p.heading_level else None

    return Paragraph(
        runs=runs,
        alignment=dir_align,
        heading_level=dir_heading,
        line_spacing=p.line_spacing,
        space_before=p.space_before,
        space_after=p.space_after,
        indent_left=p.indent_left,
        indent_right=p.indent_right,
        indent_first_line=p.indent_first_line,
        list_marker=p.list_marker,
        list_level=p.list_level,
        bbox=p.bbox,
    )


def _table_layout_to_dir(tbl_layout: TableLayout) -> Table:
    """Convert a layout TableLayout into a DIR Table."""
    dir_rows: List[TableRow] = []

    for r in tbl_layout.rows:
        dir_cells: List[TableCell] = []
        for c in r.cells:
            cell_paragraphs: List[BlockNode] = []
            if c.lines:
                p_clusters = cluster_lines_to_paragraphs(c.lines, container_bbox=c.bbox)
                for pc in p_clusters:
                    cell_paragraphs.append(_paragraph_cluster_to_dir(pc))

            borders: Dict[str, Border] = {}
            if tbl_layout.has_borders:
                borders["top"] = Border(style="solid", width=1.0)
                borders["bottom"] = Border(style="solid", width=1.0)
                borders["left"] = Border(style="solid", width=1.0)
                borders["right"] = Border(style="solid", width=1.0)

            dir_cells.append(
                TableCell(
                    content=cell_paragraphs,
                    col_span=c.col_span,
                    row_span=c.row_span,
                    width=c.bbox.width,
                    height=c.bbox.height,
                    background_color=c.background_color,
                    borders=borders,
                )
            )

        dir_rows.append(
            TableRow(
                cells=dir_cells,
                height=r.bbox.height,
                is_header=r.is_header,
            )
        )

    return Table(
        rows=dir_rows,
        col_widths=tbl_layout.col_widths,
        alignment=DIRAlignment.CENTER,
        bbox=tbl_layout.bbox,
    )


def _flip_svg_path_y(svg_path: str, page_height: float) -> str:
    """Transform SVG path coordinates from PDF space (bottom-up) to doc space (top-down)."""
    tokens = svg_path.split()
    res: List[str] = []
    i = 0
    n = len(tokens)
    while i < n:
        cmd = tokens[i]
        res.append(cmd)
        i += 1
        if cmd in ("M", "L"):
            if i + 1 < n:
                try:
                    x = float(tokens[i])
                    y = float(tokens[i + 1])
                    res.append(f"{x:.2f}")
                    res.append(f"{page_height - y:.2f}")
                except ValueError:
                    res.append(tokens[i])
                    res.append(tokens[i + 1])
                i += 2
        elif cmd == "C":
            for _ in range(3):
                if i + 1 < n:
                    try:
                        x = float(tokens[i])
                        y = float(tokens[i + 1])
                        res.append(f"{x:.2f}")
                        res.append(f"{page_height - y:.2f}")
                    except ValueError:
                        res.append(tokens[i])
                        res.append(tokens[i + 1])
                    i += 2
        elif cmd == "Z":
            pass
    return " ".join(res)


class DocumentIRBuilder:
    """Builder engine orchestrating layout synthesis into validated DocumentIR."""

    __slots__ = ("_resolver",)

    def __init__(self, resolver: Optional[XRefResolver] = None) -> None:
        self._resolver = resolver

    def build_page(
        self,
        output: InterpreterOutput,
        page_width: float,
        page_height: float,
        page_number: int = 1,
        known_headers: Optional[Set[str]] = None,
        known_footers: Optional[Set[str]] = None,
        mode: Union[Any, str] = "flow",
    ) -> DocumentPage:
        """Construct a DocumentPage from evaluated content interpreter output.

        Args:
            output: Elements extracted by ContentInterpreter.
            page_width: Page width in points.
            page_height: Page height in points.
            page_number: 1-indexed page sequence number.
            known_headers: Confirmed repeating running header strings.
            known_footers: Confirmed repeating running footer strings.
            mode: ConversionMode or str ("flow" or "canvas").

        Returns:
            Fully structured DocumentPage instance.
        """
        # 1. Cluster characters to words and words to lines
        words = cluster_characters_to_words(output.text_elements, page_height=page_height)
        all_lines = cluster_words_to_lines(words)

        # 2. Partition marginal flow (headers, footers, page numbers)
        flow_partition = partition_page_flow(
            lines=all_lines,
            page_height=page_height,
            known_headers=known_headers,
            known_footers=known_footers,
        )

        body_lines = flow_partition.body_lines

        # 3. Detect vector and borderless tables (only in FLOW mode)
        detected_tables = detect_tables_from_vectors(
            vectors=output.vector_elements,
            lines=body_lines,
            page_height=page_height,
        )
        mode_val = str(getattr(mode, "value", mode)).lower()
        is_canvas = mode_val == "canvas"
        if not detected_tables and not is_canvas:
            detected_tables = detect_borderless_tables(body_lines)

        # Track elements absorbed into tables
        table_line_ids: Set[int] = set()
        for tbl in detected_tables:
            for row in tbl.rows:
                for cell in row.cells:
                    for l in cell.lines:
                        table_line_ids.add(id(l))

        free_lines = [l for l in body_lines if id(l) not in table_line_ids]

        # 4. Normalize vector and image elements to document space
        norm_vectors: List[VectorBlock] = []
        for v in output.vector_elements:
            if v.bbox is not None:
                vb = normalize_bbox_pdf_to_doc(v.bbox, page_height)
                # Skip thin ruling vectors that belong to table borders
                if detected_tables and any(tbl.bbox.intersects(vb) for tbl in detected_tables):
                    continue
                norm_vectors.append(
                    VectorBlock(
                        svg_path=_flip_svg_path_y(v.svg_path, page_height),
                        bbox=vb,
                        fill_color=v.fill_color,
                        stroke_color=v.stroke_color,
                        stroke_width=v.stroke_width,
                    )
                )

        norm_images: List[ImageBlock] = []
        for im in output.image_elements:
            im_box = normalize_bbox_pdf_to_doc(im.bbox, page_height)
            png_data: bytes = b""
            fmt = "png"
            if im.stream is not None:
                try:
                    pdf_img = PDFImage.from_stream(im.stream, resolver=self._resolver)
                    png_data = pdf_img.to_png()
                    fmt = pdf_img.format
                except Exception:
                    png_data = _create_fallback_png()
            else:
                png_data = _create_fallback_png()

            norm_images.append(
                ImageBlock(
                    png_bytes=png_data,
                    bbox=im_box,
                    alt_text=im.name,
                    format=fmt,
                )
            )

        # 5. Recursive XY-Cut on remaining text lines
        xy_tree = recursive_xy_cut(free_lines)
        layout_blocks = linearize_reading_order(xy_tree)

        # 6. Synthesize Paragraphs from LayoutBlocks
        all_clusters: List[ParagraphCluster] = []
        for lb in layout_blocks:
            if lb.lines:
                if is_canvas:
                    for line in lb.lines:
                        all_clusters.append(
                            ParagraphCluster(
                                lines=[line],
                                bbox=line.bbox,
                                alignment=LayoutAlignment.LEFT,
                                line_spacing=1.15,
                            )
                        )
                else:
                    clusters = cluster_lines_to_paragraphs(lb.lines, container_bbox=lb.bbox)
                    all_clusters.extend(clusters)

        # Classify headings and lists globally across all page clusters
        if all_clusters:
            modal_body_size = compute_modal_body_font_size(all_clusters)
            classify_headings(all_clusters, body_size=modal_body_size)
            process_list_paragraphs(all_clusters)

        dir_paragraphs = [_paragraph_cluster_to_dir(pc) for pc in all_clusters]


        # 7. Convert Tables to DIR
        dir_tables = [_table_layout_to_dir(tbl) for tbl in detected_tables]

        # 8. Interleave all block nodes sorted by vertical position (Y0)
        all_blocks: List[Tuple[float, float, BlockNode]] = []
        for p in dir_paragraphs:
            b = p.bbox if p.bbox is not None else BoundingBox(0, 0, 0, 0)
            all_blocks.append((b.y0, b.x0, p))
        for t in dir_tables:
            b = t.bbox if t.bbox is not None else BoundingBox(0, 0, 0, 0)
            all_blocks.append((b.y0, b.x0, t))
        for img in norm_images:
            all_blocks.append((img.bbox.y0, img.bbox.x0, img))
        for vec in norm_vectors:
            all_blocks.append((vec.bbox.y0, vec.bbox.x0, vec))

        all_blocks.sort(key=lambda item: (round(item[0], 1), item[1]))
        final_blocks: List[BlockNode] = [b for _, _, b in all_blocks]

        # 9. Format Headers and Footers
        header_lines = list(flow_partition.headers)
        footer_lines = list(flow_partition.footers)
        for pnum in flow_partition.page_numbers:
            if pnum.bbox.y0 <= 72.0:
                header_lines.append(pnum)
            else:
                footer_lines.append(pnum)

        header_dir: Optional[PageHeaderFooter] = None
        if header_lines:
            h_clusters = cluster_lines_to_paragraphs(header_lines)
            header_dir = PageHeaderFooter(
                content=[_paragraph_cluster_to_dir(hc) for hc in h_clusters],
                is_footer=False,
            )

        footer_dir: Optional[PageHeaderFooter] = None
        if footer_lines:
            f_clusters = cluster_lines_to_paragraphs(footer_lines)
            footer_dir = PageHeaderFooter(
                content=[_paragraph_cluster_to_dir(fc) for fc in f_clusters],
                is_footer=True,
            )

        # Dynamic margin calculation
        valid_bboxes = [b.bbox for _, _, b in all_blocks if b.bbox is not None]
        margin_l = min((bbox.x0 for bbox in valid_bboxes), default=72.0)
        margin_r = min((page_width - bbox.x1 for bbox in valid_bboxes), default=72.0)
        margin_l = max(36.0, min(72.0, margin_l))
        margin_r = max(36.0, min(72.0, margin_r))

        return DocumentPage(
            page_number=page_number,
            width=page_width,
            height=page_height,
            margin_left=margin_l,
            margin_right=margin_r,
            margin_top=72.0,
            margin_bottom=72.0,
            blocks=final_blocks,
            header=header_dir,
            footer=footer_dir,
        )

    def build_document(
        self,
        pages: Sequence[DocumentPage],
        metadata: Optional[Dict[str, str]] = None,
    ) -> DocumentIR:
        """Combine structured pages into a validated DocumentIR hierarchy.

        Args:
            pages: Sequence of DocumentPage instances.
            metadata: Document metadata dictionary (Title, Author, Subject, etc.).

        Returns:
            Validated DocumentIR container.

        Raises:
            IRBuilderError: If page list is empty or validation fails.
        """
        if not pages:
            raise IRBuilderError("Cannot build DocumentIR with empty page sequence")

        doc_ir = DocumentIR(
            pages=list(pages),
            metadata=metadata if metadata is not None else {},
        )

        validate_document_ir(doc_ir)
        return doc_ir


__all__ = [
    "DocumentIRBuilder",
]
