"""PPTX (PresentationML) emitter conforming to ISO/IEC 29500."""

from __future__ import annotations

from anyconvert.emitters.pptx.emitter import PptxEmitter
from anyconvert.emitters.pptx.shapes import render_vector_shape
from anyconvert.emitters.pptx.slides import (
    PPTX_MAX_SLIDE_EMU,
    PPTX_MAX_SLIDE_PT,
    PPTX_MIN_SLIDE_EMU,
    PPTX_MIN_SLIDE_PT,
    SlideDimensions,
    SlideTransform,
    classify_slide_orientation,
    compute_slide_dimensions,
    compute_slide_transform,
    infer_sld_sz_type,
)

__all__ = [
    "PPTX_MIN_SLIDE_PT",
    "PPTX_MAX_SLIDE_PT",
    "PPTX_MIN_SLIDE_EMU",
    "PPTX_MAX_SLIDE_EMU",
    "PptxEmitter",
    "SlideDimensions",
    "SlideTransform",
    "classify_slide_orientation",
    "compute_slide_dimensions",
    "compute_slide_transform",
    "infer_sld_sz_type",
    "render_vector_shape",
]
