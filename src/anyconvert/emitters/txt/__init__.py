"""Plaintext format emitters (Flow and Canvas modes)."""

from __future__ import annotations

from typing import Optional

from anyconvert.emitters.base import BaseEmitter, ConversionMode
from anyconvert.emitters.txt.canvas import TxtCanvasEmitter
from anyconvert.emitters.txt.flow import TxtFlowEmitter
from anyconvert.ir.model import DocumentIR


class TxtEmitter(BaseEmitter):
    """Unified Plaintext emitter dispatching between Flow (Markdown) and Canvas (2D grid) modes."""

    def __init__(
        self,
        char_width_pt: float = 6.0,
        line_height_pt: float = 12.0,
    ) -> None:
        self.flow_emitter = TxtFlowEmitter()
        self.canvas_emitter = TxtCanvasEmitter(
            char_width_pt=char_width_pt,
            line_height_pt=line_height_pt,
        )

    def emit(
        self,
        doc_ir: DocumentIR,
        mode: ConversionMode = ConversionMode.FLOW,
    ) -> bytes:
        """Serialize DocumentIR into UTF-8 plaintext according to specified mode."""
        if mode == ConversionMode.CANVAS:
            return self.canvas_emitter.emit(doc_ir, mode=mode)
        return self.flow_emitter.emit(doc_ir, mode=mode)


__all__ = [
    "TxtEmitter",
    "TxtFlowEmitter",
    "TxtCanvasEmitter",
]
