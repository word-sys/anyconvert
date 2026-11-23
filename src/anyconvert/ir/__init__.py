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
    detect_image_format,
)
from anyconvert.ir.serializer import (
    JSON_AST_SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
    deserialize_document_ir,
    document_ir_from_dict,
    document_ir_to_dict,
    serialize_document_ir,
    validate_json_ast_schema,
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
    "JSON_AST_SCHEMA_VERSION",
    "SUPPORTED_SCHEMA_VERSIONS",
    "document_ir_to_dict",
    "document_ir_from_dict",
    "serialize_document_ir",
    "deserialize_document_ir",
    "validate_json_ast_schema",
    "validate_document_ir",
    "detect_image_format",
]
