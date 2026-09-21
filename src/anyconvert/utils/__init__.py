"""General utility tools for anyconvert."""

from __future__ import annotations

from anyconvert.utils.png import (
    COLOR_TYPE_GRAY,
    COLOR_TYPE_GRAY_ALPHA,
    COLOR_TYPE_INDEXED,
    COLOR_TYPE_RGB,
    COLOR_TYPE_RGBA,
    PNG_SIGNATURE,
    create_chunk,
    encode_gray_png,
    encode_png,
    encode_rgb_png,
    encode_rgba_png,
    parse_png,
)

__all__ = [
    "PNG_SIGNATURE",
    "COLOR_TYPE_GRAY",
    "COLOR_TYPE_RGB",
    "COLOR_TYPE_INDEXED",
    "COLOR_TYPE_GRAY_ALPHA",
    "COLOR_TYPE_RGBA",
    "create_chunk",
    "encode_png",
    "encode_rgba_png",
    "encode_rgb_png",
    "encode_gray_png",
    "parse_png",
]
