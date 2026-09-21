"""Universal Document Intermediate Representation (DIR) models, builder, and validator."""

from __future__ import annotations

from anyconvert.ir.builder import DocumentIRBuilder
from anyconvert.ir.model import (
    Alignment,
    BlockNode,
    Border,
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
from anyconvert.ir.validator import validate_document_ir

__all__ = [
    "Alignment",
    "HeadingLevel",
    "TextRun",
    "Paragraph",
    "Border",
    "TableCell",
    "TableRow",
    "Table",
    "ImageBlock",
    "VectorBlock",
    "BlockNode",
    "PageHeaderFooter",
    "DocumentPage",
    "DocumentIR",
    "DocumentIRBuilder",
    "validate_document_ir",
]
