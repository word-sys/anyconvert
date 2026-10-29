"""HTML5 document emitter package conforming to W3C HTML5 recommendations."""

from __future__ import annotations

from anyconvert.emitters.base import ConversionMode
from anyconvert.emitters.html.canvas import CanvasHTMLRenderer, render_canvas_body
from anyconvert.emitters.html.css import build_default_css
from anyconvert.emitters.html.emitter import HTMLEmitter
from anyconvert.emitters.html.flow import FlowHTMLRenderer, render_flow_body
from anyconvert.emitters.html.packaging import (
    HTMLPackager,
    extract_embedded_images,
    is_self_contained,
    package_html,
)

__all__ = [
    "HTMLEmitter",
    "FlowHTMLRenderer",
    "render_flow_body",
    "CanvasHTMLRenderer",
    "render_canvas_body",
    "HTMLPackager",
    "package_html",
    "is_self_contained",
    "extract_embedded_images",
    "ConversionMode",
    "build_default_css",
]
