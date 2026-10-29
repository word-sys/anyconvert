"""PPTX (PresentationML) emitter conforming to ISO/IEC 29500."""

from __future__ import annotations

from anyconvert.emitters.pptx.emitter import PptxEmitter
from anyconvert.emitters.pptx.shapes import render_vector_shape

__all__ = ["PptxEmitter", "render_vector_shape"]
