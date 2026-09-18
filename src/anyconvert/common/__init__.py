"""Common mathematical, geometrical, colorimetric, and I/O primitives for anyconvert."""

from __future__ import annotations

from anyconvert.common.color import (
    BLACK,
    BLUE,
    CYAN,
    DARK_GRAY,
    GRAY,
    GREEN,
    LIGHT_GRAY,
    MAGENTA,
    RED,
    TRANSPARENT,
    WHITE,
    YELLOW,
    Color,
)
from anyconvert.common.geometry import BoundingBox, Matrix3x3, Point, Size

from anyconvert.common.reader import (
    PDF_DELIMITERS,
    PDF_WHITESPACE,
    BitReader,
    ByteReader,
)

__all__ = [
    "Point",
    "Size",
    "BoundingBox",
    "Matrix3x3",
    "Color",
    "BLACK",
    "WHITE",
    "RED",
    "GREEN",
    "BLUE",
    "YELLOW",
    "CYAN",
    "MAGENTA",
    "GRAY",
    "LIGHT_GRAY",
    "DARK_GRAY",
    "TRANSPARENT",
    "ByteReader",
    "BitReader",
    "PDF_WHITESPACE",
    "PDF_DELIMITERS",
]

