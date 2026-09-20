"""Base font abstractions, font metrics, and descriptor models.

Defines standardized font metric representations normalized to standard PDF 1/1000
typographic units adhering to PDF 32000-1 §9.2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

from anyconvert.common.geometry import BoundingBox


@dataclass(slots=True)
class FontMetrics:
    """Typographic metrics normalized to 1000 units per em (1/1000 font size).

    Attributes:
        units_per_em: Natural font units per em square (typically 1000 or 2048).
        ascender: Maximum typographic ascent (positive, in 1/1000 units).
        descender: Maximum typographic descent (negative, in 1/1000 units).
        cap_height: Height of uppercase characters (in 1/1000 units).
        x_height: Height of lowercase characters (in 1/1000 units).
        italic_angle: Italic angle in degrees counter-clockwise from vertical.
        is_bold: True if typeface has bold weight (> 600).
        is_italic: True if typeface is italic or oblique.
        is_monospace: True if typeface is fixed-pitch.
        default_width: Default advance width for unmapped glyphs.
        bbox: Font-wide bounding box encompassing all glyphs.
    """

    units_per_em: int = 1000
    ascender: float = 800.0
    descender: float = -200.0
    cap_height: float = 700.0
    x_height: float = 500.0
    italic_angle: float = 0.0
    is_bold: bool = False
    is_italic: bool = False
    is_monospace: bool = False
    default_width: float = 500.0
    bbox: Optional[BoundingBox] = None


@dataclass
class BaseFont:
    """Abstract base class for all PDF font resolvers.

    Attributes:
        name: PostScript or family font name.
        metrics: FontMetrics instance.
        widths: Mapping from character code or CID to advance width (1/1000 units).
        to_unicode_map: Mapping from character code or CID to Unicode string.
        is_standard_14: True if this font is one of the Standard 14 PDF fonts.
    """

    name: str
    metrics: FontMetrics = field(default_factory=FontMetrics)
    widths: Dict[int, float] = field(default_factory=dict)
    to_unicode_map: Dict[int, str] = field(default_factory=dict)
    is_standard_14: bool = False

    def get_width(self, char_code: int) -> float:
        """Return advance width for character code normalized to 1/1000 font units.

        Args:
            char_code: Character code or glyph CID.

        Returns:
            float: Advance width in 1/1000 units.
        """
        if char_code in self.widths:
            return self.widths[char_code]
        return self.metrics.default_width

    def to_unicode(self, char_code: int) -> str:
        """Translate character code to Unicode string.

        Args:
            char_code: Character code in content stream.

        Returns:
            str: Decoded Unicode string, or fallback character representation.
        """
        if char_code in self.to_unicode_map:
            return self.to_unicode_map[char_code]
        # Fallback to Latin-1 character if within valid byte range
        if 0 <= char_code <= 255:
            return chr(char_code)
        return "\ufffd"
