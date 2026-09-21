"""Structural integrity and invariant validation engine for DocumentIR.

Verifies page geometry, margin bounds, block topologies, table grid consistency,
and image integrity prior to serialization.
"""

from __future__ import annotations

from anyconvert.exceptions import IRValidationError
from anyconvert.ir.model import (
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
from anyconvert.utils.png import PNG_SIGNATURE


def validate_document_ir(doc_ir: DocumentIR) -> None:
    """Validate all structural invariants of a DocumentIR instance.

    Args:
        doc_ir: DocumentIR container to validate.

    Raises:
        IRValidationError: If any structural, geometric, or typographic invariant is violated.
    """
    if not isinstance(doc_ir, DocumentIR):
        raise IRValidationError(f"Expected DocumentIR instance, got {type(doc_ir).__name__}")

    if not doc_ir.pages:
        raise IRValidationError("DocumentIR must contain at least one DocumentPage")

    for idx, page in enumerate(doc_ir.pages):
        _validate_page(page, expected_page_num=idx + 1)


def _validate_page(page: DocumentPage, expected_page_num: int) -> None:
    """Validate a single document page."""
    if not isinstance(page, DocumentPage):
        raise IRValidationError(f"Expected DocumentPage, got {type(page).__name__}")

    if page.page_number <= 0:
        raise IRValidationError(f"Invalid page_number {page.page_number}; must be >= 1")

    # Dimensions
    if page.width <= 0.0 or page.height <= 0.0:
        raise IRValidationError(
            f"Page {page.page_number} has non-positive dimensions: {page.width}x{page.height}"
        )

    # Margins
    if page.margin_left < 0.0 or page.margin_right < 0.0:
        raise IRValidationError(f"Page {page.page_number} has negative horizontal margins")
    if page.margin_top < 0.0 or page.margin_bottom < 0.0:
        raise IRValidationError(f"Page {page.page_number} has negative vertical margins")

    if page.margin_left + page.margin_right >= page.width:
        raise IRValidationError(
            f"Page {page.page_number} horizontal margins ({page.margin_left} + {page.margin_right}) "
            f"exceed or equal page width ({page.width})"
        )

    if page.margin_top + page.margin_bottom >= page.height:
        raise IRValidationError(
            f"Page {page.page_number} vertical margins ({page.margin_top} + {page.margin_bottom}) "
            f"exceed or equal page height ({page.height})"
        )

    # Headers and footers
    if page.header is not None:
        _validate_header_footer(page.header, is_footer=False, page_num=page.page_number)
    if page.footer is not None:
        _validate_header_footer(page.footer, is_footer=True, page_num=page.page_number)

    # Blocks
    for b_idx, block in enumerate(page.blocks):
        _validate_block(block, page_num=page.page_number, block_idx=b_idx)


def _validate_header_footer(hf: PageHeaderFooter, is_footer: bool, page_num: int) -> None:
    """Validate header or footer container."""
    region_name = "Footer" if is_footer else "Header"
    if hf.is_footer != is_footer:
        raise IRValidationError(
            f"Page {page_num} {region_name} has mismatched is_footer flag: {hf.is_footer}"
        )
    for p in hf.content:
        if not isinstance(p, Paragraph):
            raise IRValidationError(
                f"Page {page_num} {region_name} content must be Paragraphs, got {type(p).__name__}"
            )
        _validate_paragraph(p, page_num=page_num)


def _validate_block(block: BlockNode, page_num: int, block_idx: int) -> None:
    """Dispatch validation for block node types."""
    if isinstance(block, Paragraph):
        _validate_paragraph(block, page_num)
    elif isinstance(block, Table):
        _validate_table(block, page_num)
    elif isinstance(block, ImageBlock):
        _validate_image(block, page_num)
    elif isinstance(block, VectorBlock):
        _validate_vector(block, page_num)
    else:
        raise IRValidationError(
            f"Page {page_num} block #{block_idx} has invalid type: {type(block).__name__}"
        )


def _validate_paragraph(p: Paragraph, page_num: int) -> None:
    """Validate paragraph runs, alignments, and indentations."""
    if p.heading_level is not None and not isinstance(p.heading_level, HeadingLevel):
        raise IRValidationError(
            f"Page {page_num} paragraph has invalid heading_level: {p.heading_level!r}"
        )

    if p.line_spacing <= 0.0:
        raise IRValidationError(
            f"Page {page_num} paragraph line_spacing must be positive, got {p.line_spacing}"
        )

    if p.list_level < 0:
        raise IRValidationError(
            f"Page {page_num} paragraph list_level must be non-negative, got {p.list_level}"
        )

    for r_idx, run in enumerate(p.runs):
        if not isinstance(run, TextRun):
            raise IRValidationError(
                f"Page {page_num} paragraph run #{r_idx} is not a TextRun"
            )
        if run.font_size <= 0.0:
            raise IRValidationError(
                f"Page {page_num} run #{r_idx} has non-positive font_size: {run.font_size}"
            )
        if not run.font_name:
            raise IRValidationError(
                f"Page {page_num} run #{r_idx} has empty font_name"
            )


def _validate_table(table: Table, page_num: int) -> None:
    """Validate table structure, rows, column widths, and cell spans."""
    if not table.rows:
        raise IRValidationError(f"Page {page_num} Table must contain at least one TableRow")

    if not table.col_widths:
        raise IRValidationError(f"Page {page_num} Table must specify col_widths")

    for w in table.col_widths:
        if w < 0.0:
            raise IRValidationError(f"Page {page_num} Table has negative col_width: {w}")

    for r_idx, row in enumerate(table.rows):
        if not isinstance(row, TableRow):
            raise IRValidationError(f"Page {page_num} Table row #{r_idx} is not a TableRow")
        if not row.cells:
            raise IRValidationError(f"Page {page_num} Table row #{r_idx} has no cells")

        for c_idx, cell in enumerate(row.cells):
            if not isinstance(cell, TableCell):
                raise IRValidationError(
                    f"Page {page_num} Table cell ({r_idx}, {c_idx}) is not a TableCell"
                )
            if cell.col_span < 1 or cell.row_span < 1:
                raise IRValidationError(
                    f"Page {page_num} Table cell ({r_idx}, {c_idx}) spans must be >= 1, "
                    f"got col_span={cell.col_span}, row_span={cell.row_span}"
                )
            # Validate nested content
            for nested_block in cell.content:
                _validate_block(nested_block, page_num=page_num, block_idx=0)


def _validate_image(img: ImageBlock, page_num: int) -> None:
    """Validate image payload, format, and dimensions."""
    if not img.png_bytes:
        raise IRValidationError(f"Page {page_num} ImageBlock has empty png_bytes")

    if img.format == "png":
        if not img.png_bytes.startswith(PNG_SIGNATURE):
            raise IRValidationError(f"Page {page_num} ImageBlock has invalid PNG signature")
    elif img.format == "jpeg":
        if not img.png_bytes.startswith(b"\xFF\xD8\xFF"):
            raise IRValidationError(f"Page {page_num} ImageBlock has invalid JPEG signature")

    if img.bbox.width <= 0.0 or img.bbox.height <= 0.0:
        raise IRValidationError(
            f"Page {page_num} ImageBlock has non-positive bbox: {img.bbox.width}x{img.bbox.height}"
        )


def _validate_vector(vec: VectorBlock, page_num: int) -> None:
    """Validate vector shape svg_path and bbox."""
    if not vec.svg_path:
        raise IRValidationError(f"Page {page_num} VectorBlock has empty svg_path")

    if vec.bbox.width < 0.0 or vec.bbox.height < 0.0:
        raise IRValidationError(
            f"Page {page_num} VectorBlock has negative dimensions: {vec.bbox.width}x{vec.bbox.height}"
        )


__all__ = [
    "validate_document_ir",
]
