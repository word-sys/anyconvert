"""ODP (OASIS OpenDocument Presentation) emitter conforming to ISO/IEC 26300."""

from __future__ import annotations

from anyconvert.emitters.odp.content import (
    OdpSlideLayoutSpec,
    build_odp_page_layout_xml,
    build_odp_slide_layouts,
    compute_odp_page_orientation,
    render_vector_path_odp,
)
from anyconvert.emitters.odp.emitter import OdpEmitter

__all__ = [
    "OdpEmitter",
    "OdpSlideLayoutSpec",
    "build_odp_page_layout_xml",
    "build_odp_slide_layouts",
    "compute_odp_page_orientation",
    "render_vector_path_odp",
]
