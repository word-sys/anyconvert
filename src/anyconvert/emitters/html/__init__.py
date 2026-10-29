"""HTML5 document emitter package conforming to W3C HTML5 recommendations."""

from __future__ import annotations

from anyconvert.emitters.base import ConversionMode
from anyconvert.emitters.html.css import build_default_css
from anyconvert.emitters.html.emitter import HTMLEmitter

__all__ = [
    "HTMLEmitter",
    "ConversionMode",
    "build_default_css",
]
