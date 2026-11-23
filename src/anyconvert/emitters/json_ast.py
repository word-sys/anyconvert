"""JSON AST emitter wrapping the DocumentIR JSON serializer."""

from __future__ import annotations

from typing import Optional

from anyconvert.emitters.base import BaseEmitter, ConversionMode
from anyconvert.exceptions import SerializationError
from anyconvert.ir.model import DocumentIR
from anyconvert.ir.serializer import serialize_document_ir


class JsonEmitter(BaseEmitter):
    """Emitter serializing DocumentIR into UTF-8 JSON AST bytes."""

    __slots__ = ("indent", "include_images", "ensure_ascii", "validate")

    def __init__(
        self,
        indent: Optional[int] = 2,
        include_images: bool = True,
        ensure_ascii: bool = False,
        validate: bool = True,
    ) -> None:
        self.indent: Optional[int] = indent
        self.include_images: bool = include_images
        self.ensure_ascii: bool = ensure_ascii
        self.validate: bool = validate

    def emit(
        self,
        doc_ir: DocumentIR,
        mode: ConversionMode = ConversionMode.FLOW,
    ) -> bytes:
        """Serialize DocumentIR into UTF-8 encoded JSON AST bytes."""
        if not doc_ir.pages:
            raise SerializationError("Cannot emit JSON AST from empty DocumentIR")
        json_text = serialize_document_ir(
            doc_ir,
            indent=self.indent,
            include_images=self.include_images,
            ensure_ascii=self.ensure_ascii,
            validate=self.validate,
        )
        return (json_text + "\n").encode("utf-8")


__all__ = ["JsonEmitter"]
