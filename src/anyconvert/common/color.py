"""Color primitives and color space conversion utilities.

Implements the universal Color dataclass supporting RGBA, DeviceGray,
DeviceRGB, DeviceCMYK, and Hex formats with standard color-metric equations.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional, Tuple


def _clamp_int(val: int, min_val: int = 0, max_val: int = 255) -> int:
    """Clamp integer to [min_val, max_val]."""
    return max(min_val, min(max_val, int(round(val))))


def _clamp_float(val: float, min_val: float = 0.0, max_val: float = 1.0) -> float:
    """Clamp float to [min_val, max_val]."""
    return max(min_val, min(max_val, float(val)))


@dataclass(frozen=True)
class Color:
    """Immutable universal color representation in sRGB / RGBA space.

    Attributes:
        r: Red color channel intensity [0, 255].
        g: Green color channel intensity [0, 255].
        b: Blue color channel intensity [0, 255].
        a: Alpha transparency channel [0.0, 1.0], where 1.0 is fully opaque.
    """

    r: int
    g: int
    b: int
    a: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "r", _clamp_int(self.r))
        object.__setattr__(self, "g", _clamp_int(self.g))
        object.__setattr__(self, "b", _clamp_int(self.b))
        object.__setattr__(self, "a", _clamp_float(self.a))

    # --------------------------------------------------------------------------
    # Formatting Properties
    # --------------------------------------------------------------------------

    @property
    def hex(self) -> str:
        """Return 6-character uppercase RGB hex string: 'RRGGBB'."""
        return f"{self.r:02X}{self.g:02X}{self.b:02X}"

    @property
    def hex_with_hash(self) -> str:
        """Return hex string prefixed with hash: '#RRGGBB'."""
        return f"#{self.hex}"

    @property
    def rgba_hex(self) -> str:
        """Return 8-character uppercase RGBA hex string: 'RRGGBBAA'."""
        alpha_byte = _clamp_int(int(round(self.a * 255.0)))
        return f"{self.hex}{alpha_byte:02X}"

    @property
    def is_transparent(self) -> bool:
        """Test if the color is fully or effectively transparent."""
        return self.a <= 1e-4

    @property
    def luminance(self) -> float:
        """Compute relative luminance according to ITU-R BT.709.

        Range: [0.0, 1.0] where 0.0 is pure black and 1.0 is pure white.
        """
        # Linearize sRGB components
        def _linearize(c: int) -> float:
            v = c / 255.0
            return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

        return (
            0.2126 * _linearize(self.r)
            + 0.7152 * _linearize(self.g)
            + 0.0722 * _linearize(self.b)
        )

    @property
    def is_dark(self) -> bool:
        """True if the color's luminance is below 0.5 (ideal for choosing light text)."""
        return self.luminance < 0.5

    def to_rgba_tuple(self) -> Tuple[int, int, int, float]:
        """Return tuple of (r, g, b, a)."""
        return (self.r, self.g, self.b, self.a)

    def to_rgb_normalized(self) -> Tuple[float, float, float]:
        """Return normalized floating point (r, g, b) each in [0.0, 1.0]."""
        return (self.r / 255.0, self.g / 255.0, self.b / 255.0)

    def with_alpha(self, alpha: float) -> Color:
        """Return a copy of this color with a modified alpha value."""
        return Color(self.r, self.g, self.b, alpha)

    # --------------------------------------------------------------------------
    # Color Space Conversion Constructors
    # --------------------------------------------------------------------------

    @classmethod
    def from_rgb(cls, r: int, g: int, b: int, a: float = 1.0) -> Color:
        """Construct Color from integer RGB values in [0, 255]."""
        return cls(r, g, b, a)

    @classmethod
    def from_rgb_float(cls, r: float, g: float, b: float, a: float = 1.0) -> Color:
        """Construct Color from normalized float RGB values in [0.0, 1.0]."""
        return cls(
            _clamp_int(int(round(r * 255.0))),
            _clamp_int(int(round(g * 255.0))),
            _clamp_int(int(round(b * 255.0))),
            a,
        )

    @classmethod
    def from_gray(cls, gray: float, a: float = 1.0) -> Color:
        """Construct Color from DeviceGray normalized intensity [0.0, 1.0].

        0.0 = Black, 1.0 = White.
        """
        val = _clamp_int(int(round(gray * 255.0)))
        return cls(val, val, val, a)

    @classmethod
    def from_cmyk(
        cls, c: float, m: float, y: float, k: float, a: float = 1.0
    ) -> Color:
        """Construct Color from DeviceCMYK subtractive components in [0.0, 1.0].

        Transformation equations:
            R = 255 * (1 - C) * (1 - K)
            G = 255 * (1 - M) * (1 - K)
            B = 255 * (1 - Y) * (1 - K)
        """
        c = _clamp_float(c)
        m = _clamp_float(m)
        y = _clamp_float(y)
        k = _clamp_float(k)

        factor = 1.0 - k
        r = _clamp_int(int(round(255.0 * (1.0 - c) * factor)))
        g = _clamp_int(int(round(255.0 * (1.0 - m) * factor)))
        b = _clamp_int(int(round(255.0 * (1.0 - y) * factor)))
        return cls(r, g, b, a)

    @classmethod
    def from_hex(cls, hex_str: str, a: Optional[float] = None) -> Color:
        """Construct Color from hexadecimal string.

        Supports formats:
            - '#RGB', 'RGB'
            - '#RGBA', 'RGBA'
            - '#RRGGBB', 'RRGGBB'
            - '#RRGGBBAA', 'RRGGBBAA'
        """
        cleaned = hex_str.strip().lstrip("#")
        if not re.fullmatch(r"[0-9a-fA-F]+", cleaned):
            raise ValueError(f"Invalid hexadecimal color string: '{hex_str}'")

        length = len(cleaned)
        if length == 3:  # RGB
            r = int(cleaned[0] * 2, 16)
            g = int(cleaned[1] * 2, 16)
            b = int(cleaned[2] * 2, 16)
            alpha = a if a is not None else 1.0
        elif length == 4:  # RGBA
            r = int(cleaned[0] * 2, 16)
            g = int(cleaned[1] * 2, 16)
            b = int(cleaned[2] * 2, 16)
            alpha = a if a is not None else (int(cleaned[3] * 2, 16) / 255.0)
        elif length == 6:  # RRGGBB
            r = int(cleaned[0:2], 16)
            g = int(cleaned[2:4], 16)
            b = int(cleaned[4:6], 16)
            alpha = a if a is not None else 1.0
        elif length == 8:  # RRGGBBAA
            r = int(cleaned[0:2], 16)
            g = int(cleaned[2:4], 16)
            b = int(cleaned[4:6], 16)
            alpha = a if a is not None else (int(cleaned[6:8], 16) / 255.0)
        else:
            raise ValueError(
                f"Hex string '{hex_str}' must have 3, 4, 6, or 8 hex digits"
            )

        return cls(r, g, b, alpha)


# Predefined standard palette constants
BLACK = Color(0, 0, 0, 1.0)
WHITE = Color(255, 255, 255, 1.0)
RED = Color(255, 0, 0, 1.0)
GREEN = Color(0, 255, 0, 1.0)
BLUE = Color(0, 0, 255, 1.0)
YELLOW = Color(255, 255, 0, 1.0)
CYAN = Color(0, 255, 255, 1.0)
MAGENTA = Color(255, 0, 255, 1.0)
GRAY = Color(128, 128, 128, 1.0)
LIGHT_GRAY = Color(211, 211, 211, 1.0)
DARK_GRAY = Color(64, 64, 64, 1.0)
TRANSPARENT = Color(0, 0, 0, 0.0)

__all__ = [
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
]
