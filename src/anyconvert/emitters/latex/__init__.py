"""LaTeX (.tex) academic document emitter package."""

from __future__ import annotations

from anyconvert.emitters.latex.emitter import (
    LatexEmitter,
    escape_latex_text,
    escape_latex_url,
)

__all__ = [
    "LatexEmitter",
    "escape_latex_text",
    "escape_latex_url",
]
