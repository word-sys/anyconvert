"""ODP (OASIS OpenDocument Presentation) emitter conforming to ISO/IEC 26300."""

from __future__ import annotations

from anyconvert.emitters.odp.content import render_vector_path_odp
from anyconvert.emitters.odp.emitter import OdpEmitter

__all__ = ["OdpEmitter", "render_vector_path_odp"]
