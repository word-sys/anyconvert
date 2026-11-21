"""LaTeX (.tex) academic document emitter package."""

from __future__ import annotations

from anyconvert.emitters.latex.emitter import (
    LatexEmitter,
    escape_latex_text,
    escape_latex_url,
)
from anyconvert.emitters.latex.math import (
    UNICODE_TO_LATEX_MATH,
    classify_math_font,
    contains_math_symbol,
    decode_math_font_text,
    detect_script_kind,
    is_math_font,
    render_latex_math_runs,
    translate_math_text_to_latex,
)

__all__ = [
    "LatexEmitter",
    "UNICODE_TO_LATEX_MATH",
    "classify_math_font",
    "contains_math_symbol",
    "decode_math_font_text",
    "detect_script_kind",
    "escape_latex_text",
    "escape_latex_url",
    "is_math_font",
    "render_latex_math_runs",
    "translate_math_text_to_latex",
]
