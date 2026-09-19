"""Common primitives, geometry, color models, and utilities."""

from __future__ import annotations

from anyconvert.common.color import (
    BLACK,
    BLUE,
    DARK_GRAY,
    GRAY,
    GREEN,
    LIGHT_GRAY,
    RED,
    TRANSPARENT,
    WHITE,
    Color,
)
from anyconvert.common.geometry import (
    BoundingBox,
    Matrix3x3,
    Point,
    Size,
)
from anyconvert.common.logging import (
    configure_logging,
    get_logger,
)

__all__ = [
    "Point",
    "Size",
    "BoundingBox",
    "Matrix3x3",
    "Color",
    "BLACK",
    "WHITE",
    "TRANSPARENT",
    "RED",
    "GREEN",
    "BLUE",
    "GRAY",
    "LIGHT_GRAY",
    "DARK_GRAY",
    "get_logger",
    "configure_logging",
]
