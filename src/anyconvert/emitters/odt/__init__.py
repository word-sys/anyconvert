"""ODT (OASIS OpenDocument Text) emitter conforming to ISO/IEC 26300."""

from __future__ import annotations

from anyconvert.emitters.odt.content import render_vector_path_odt
from anyconvert.emitters.odt.emitter import OdtEmitter

__all__ = ["OdtEmitter", "render_vector_path_odt"]
