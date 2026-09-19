"""Color representations and color space conversions.

Supports RGBA, DeviceGray, DeviceRGB, DeviceCMYK, and Hex color models
with standard color conversion equations adhering to PDF 32000-1 specifications.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


def _clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp a numerical value between min_val and max_val."""
    return max(min_val, min(value, max_val))


def _clamp_int(value: int, min_val: int = 0, max_val: int = 255) -> int:
    """Clamp an integer value between min_val and max_val."""
    return max(min_val, min(value, max_val))


@dataclass(frozen=True, slots=True)
class Color:
    """Represents an RGBA color.

    Attributes:
        r: Red component (0 to 255).
        g: Green component (0 to 255).
        b: Blue component (0 to 255).
        a: Alpha transparency component (0.0 to 1.0, default 1.0 = fully opaque).
    """

    r: int
    g: int
    b: int
    a: float = 1.0

    def __post_init__(self) -> None:
        """Validate and clamp color bounds."""
        r_clamped = _clamp_int(int(self.r), 0, 255)
        g_clamped = _clamp_int(int(self.g), 0, 255)
        b_clamped = _clamp_int(int(self.b), 0, 255)
        a_clamped = _clamp(float(self.a), 0.0, 1.0)

        # Frozen dataclass assignment via object.__setattr__
        object.__setattr__(self, "r", r_clamped)
        object.__setattr__(self, "g", g_clamped)
        object.__setattr__(self, "b", b_clamped)
        object.__setattr__(self, "a", a_clamped)

    @property
    def hex(self) -> str:
        """Hexadecimal representation without leading hash (e.g. 'FF00AA')."""
        return f"{self.r:02X}{self.g:02X}{self.b:02X}"

    @property
    def hex_with_hash(self) -> str:
        """Hexadecimal representation with leading hash (e.g. '#FF00AA')."""
        return f"#{self.hex}"

    @property
    def hex_with_alpha(self) -> str:
        """Hexadecimal RGBA representation (e.g. 'FF00AAFF')."""
        alpha_byte = int(round(self.a * 255.0))
        return f"{self.hex}{alpha_byte:02X}"

    @property
    def is_transparent(self) -> bool:
        """Return True if completely transparent."""
        return self.a <= 0.0

    @property
    def is_opaque(self) -> bool:
        """Return True if completely opaque."""
        return self.a >= 1.0

    @classmethod
    def from_rgb(cls, r: int, g: int, b: int, a: float = 1.0) -> Color:
        """Create a Color from integer RGB values (0-255)."""
        return cls(r=r, g=g, b=b, a=a)

    @classmethod
    def from_rgb_float(cls, r: float, g: float, b: float, a: float = 1.0) -> Color:
        """Create a Color from normalized float RGB values (0.0 - 1.0)."""
        return cls(
            r=int(round(_clamp(r, 0.0, 1.0) * 255.0)),
            g=int(round(_clamp(g, 0.0, 1.0) * 255.0)),
            b=int(round(_clamp(b, 0.0, 1.0) * 255.0)),
            a=_clamp(a, 0.0, 1.0),
        )

    @classmethod
    def from_gray(cls, gray: float, a: float = 1.0) -> Color:
        """Create a Color from a DeviceGray level (0.0 = black, 1.0 = white).

        Args:
            gray: Luminance level from 0.0 to 1.0.
            a: Alpha transparency from 0.0 to 1.0.

        Returns:
            Color: Grayscale color.
        """
        val = int(round(_clamp(gray, 0.0, 1.0) * 255.0))
        return cls(r=val, g=val, b=val, a=_clamp(a, 0.0, 1.0))

    @classmethod
    def from_cmyk(cls, c: float, m: float, y: float, k: float, a: float = 1.0) -> Color:
        """Create a Color from DeviceCMYK subtractive components (0.0 - 1.0).

        Conversion formula from PDF 32000-1 §8.6.4.2:
            R = 255 * (1 - C) * (1 - K)
            G = 255 * (1 - M) * (1 - K)
            B = 255 * (1 - Y) * (1 - K)

        Args:
            c: Cyan component (0.0 - 1.0).
            m: Magenta component (0.0 - 1.0).
            y: Yellow component (0.0 - 1.0).
            k: Key/Black component (0.0 - 1.0).
            a: Alpha transparency (0.0 - 1.0).

        Returns:
            Color: Converted RGB Color.
        """
        c_clamped = _clamp(c, 0.0, 1.0)
        m_clamped = _clamp(m, 0.0, 1.0)
        y_clamped = _clamp(y, 0.0, 1.0)
        k_clamped = _clamp(k, 0.0, 1.0)

        r = int(round(255.0 * (1.0 - c_clamped) * (1.0 - k_clamped)))
        g = int(round(255.0 * (1.0 - m_clamped) * (1.0 - k_clamped)))
        b = int(round(255.0 * (1.0 - y_clamped) * (1.0 - k_clamped)))

        return cls(r=r, g=g, b=b, a=_clamp(a, 0.0, 1.0))

    def to_cmyk(self) -> Tuple[float, float, float, float]:
        """Convert RGB color to standard CMYK values (0.0 - 1.0).

        Returns:
            Tuple[float, float, float, float]: (c, m, y, k) components.
        """
        r_f = self.r / 255.0
        g_f = self.g / 255.0
        b_f = self.b / 255.0

        k = 1.0 - max(r_f, g_f, b_f)
        if k >= 1.0:
            return (0.0, 0.0, 0.0, 1.0)

        c = (1.0 - r_f - k) / (1.0 - k)
        m = (1.0 - g_f - k) / (1.0 - k)
        y = (1.0 - b_f - k) / (1.0 - k)

        return (
            _clamp(c, 0.0, 1.0),
            _clamp(m, 0.0, 1.0),
            _clamp(y, 0.0, 1.0),
            _clamp(k, 0.0, 1.0),
        )

    @classmethod
    def from_hex(cls, hex_str: str, alpha: float | None = None) -> Color:
        """Parse a color from a hexadecimal string.

        Supported formats:
            - '#RGB' or 'RGB'
            - '#RGBA' or 'RGBA'
            - '#RRGGBB' or 'RRGGBB'
            - '#RRGGBBAA' or 'RRGGBBAA'

        Args:
            hex_str: Hexadecimal string representation.
            alpha: Optional override for alpha transparency.

        Returns:
            Color: Parsed Color instance.

        Raises:
            ValueError: If hex string is malformed.
        """
        cleaned = hex_str.strip().lstrip("#")
        length = len(cleaned)

        try:
            if length == 3:  # RGB
                r = int(cleaned[0] * 2, 16)
                g = int(cleaned[1] * 2, 16)
                b = int(cleaned[2] * 2, 16)
                a = 1.0 if alpha is None else alpha
            elif length == 4:  # RGBA
                r = int(cleaned[0] * 2, 16)
                g = int(cleaned[1] * 2, 16)
                b = int(cleaned[2] * 2, 16)
                a_parsed = int(cleaned[3] * 2, 16) / 255.0
                a = a_parsed if alpha is None else alpha
            elif length == 6:  # RRGGBB
                r = int(cleaned[0:2], 16)
                g = int(cleaned[2:4], 16)
                b = int(cleaned[4:6], 16)
                a = 1.0 if alpha is None else alpha
            elif length == 8:  # RRGGBBAA
                r = int(cleaned[0:2], 16)
                g = int(cleaned[2:4], 16)
                b = int(cleaned[4:6], 16)
                a_parsed = int(cleaned[6:8], 16) / 255.0
                a = a_parsed if alpha is None else alpha
            else:
                raise ValueError(f"Invalid hex color length ({length}): {hex_str!r}")
        except ValueError as err:
            raise ValueError(f"Failed to parse hex color {hex_str!r}: {err}") from err

        return cls(r=r, g=g, b=b, a=_clamp(a, 0.0, 1.0))

    def to_rgb_tuple(self) -> Tuple[int, int, int]:
        """Convert to (r, g, b) integer tuple."""
        return (self.r, self.g, self.b)

    def to_rgba_tuple(self) -> Tuple[int, int, int, float]:
        """Convert to (r, g, b, a) tuple."""
        return (self.r, self.g, self.b, self.a)

    def to_float_tuple(self) -> Tuple[float, float, float, float]:
        """Convert to (r, g, b, a) normalized float tuple in range 0.0 - 1.0."""
        return (self.r / 255.0, self.g / 255.0, self.b / 255.0, self.a)

    def with_alpha(self, new_alpha: float) -> Color:
        """Return a copy of this color with a modified alpha value."""
        return Color(self.r, self.g, self.b, a=_clamp(new_alpha, 0.0, 1.0))

    def blend_over(self, background: Color) -> Color:
        """Perform standard Porter-Duff 'source-over' alpha compositing over a background.

        Args:
            background: Background color beneath this color.

        Returns:
            Color: Result of alpha compositing.
        """
        src_a = self.a
        dst_a = background.a
        out_a = src_a + dst_a * (1.0 - src_a)

        if out_a <= 0.0:
            return Color(0, 0, 0, 0.0)

        src_r = self.r / 255.0
        src_g = self.g / 255.0
        src_b = self.b / 255.0

        dst_r = background.r / 255.0
        dst_g = background.g / 255.0
        dst_b = background.b / 255.0

        out_r = (src_r * src_a + dst_r * dst_a * (1.0 - src_a)) / out_a
        out_g = (src_g * src_a + dst_g * dst_a * (1.0 - src_a)) / out_a
        out_b = (src_b * src_a + dst_b * dst_a * (1.0 - src_a)) / out_a

        return Color(
            r=int(round(_clamp(out_r, 0.0, 1.0) * 255.0)),
            g=int(round(_clamp(out_g, 0.0, 1.0) * 255.0)),
            b=int(round(_clamp(out_b, 0.0, 1.0) * 255.0)),
            a=_clamp(out_a, 0.0, 1.0),
        )


# Standard palette constants
BLACK = Color(0, 0, 0, 1.0)
WHITE = Color(255, 255, 255, 1.0)
TRANSPARENT = Color(0, 0, 0, 0.0)
RED = Color(255, 0, 0, 1.0)
GREEN = Color(0, 255, 0, 1.0)
BLUE = Color(0, 0, 255, 1.0)
GRAY = Color(128, 128, 128, 1.0)
LIGHT_GRAY = Color(211, 211, 211, 1.0)
DARK_GRAY = Color(64, 64, 64, 1.0)
