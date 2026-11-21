r"""RTF 1.9.1 embedded binary picture renderer (\pict\pngblip and \pict\jpegblip).

Encodes PNG and JPEG ImageBlock payloads into 7-bit ASCII hexadecimal \pict
groups with accurate twip display dimensions (\picwgoal, \pichgoal), intrinsic
pixel dimensions (\picw, \pich), proportional page-width clamping, and wrapped
hex lines for universal compatibility across Word, WordPad, and LibreOffice.
"""

from __future__ import annotations

import struct
from typing import List, Optional, Tuple

from anyconvert.emitters.base import pt_to_dxa
from anyconvert.emitters.rtf.unicode import encode_rtf_unicode
from anyconvert.ir.model import ImageBlock

DEFAULT_MAX_IMAGE_WIDTH_TWIPS = 9360  # 6.5 in
HEX_LINE_WIDTH = 78

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"

# JPEG SOF markers that carry frame height/width (excluding DHT=C4, JPG=C8, DAC=CC)
_JPEG_SOF_MARKERS = frozenset(
    {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
)


def detect_rtf_blip_type(data: bytes) -> Optional[str]:
    """Return '\\pngblip' or '\\jpegblip' if bytes match PNG/JPEG magic headers, else None."""
    if not data:
        return None
    if data.startswith(_PNG_MAGIC):
        return r"\pngblip"
    if data.startswith(_JPEG_MAGIC):
        return r"\jpegblip"
    return None


def parse_image_pixel_dimensions(data: bytes) -> Optional[Tuple[int, int]]:
    """Extract (width, height) in pixels from PNG IHDR or JPEG SOF markers."""
    if data.startswith(_PNG_MAGIC) and len(data) >= 24:
        if data[12:16] == b"IHDR":
            w, h = struct.unpack(">II", data[16:24])
            if w > 0 and h > 0:
                return int(w), int(h)
        return None

    if data.startswith(_JPEG_MAGIC):
        idx = 2
        n = len(data)
        while idx + 3 < n:
            if data[idx] != 0xFF:
                idx += 1
                continue
            while idx < n and data[idx] == 0xFF:
                idx += 1
            if idx >= n:
                break
            marker = data[idx]
            idx += 1
            if marker in (0xD8, 0xD9, 0x01) or (0xD0 <= marker <= 0xD7):
                continue
            if idx + 1 >= n:
                break
            seg_len = struct.unpack(">H", data[idx : idx + 2])[0]
            if seg_len < 2 or idx + seg_len > n:
                break
            if marker in _JPEG_SOF_MARKERS and seg_len >= 7:
                h, w = struct.unpack(">HH", data[idx + 3 : idx + 7])
                if w > 0 and h > 0:
                    return int(w), int(h)
                return None
            idx += seg_len

    return None


def encode_hex_lines(data: bytes, line_width: int = HEX_LINE_WIDTH) -> str:
    """Encode raw binary bytes into wrapped lowercase 7-bit ASCII hexadecimal lines."""
    hex_str = data.hex()
    step = max(2, line_width - (line_width % 2))
    lines: List[str] = [hex_str[i : i + step] for i in range(0, len(hex_str), step)]
    return "\n".join(lines)


def build_rtf_pict_group(
    img: ImageBlock,
    max_width_twips: int = DEFAULT_MAX_IMAGE_WIDTH_TWIPS,
) -> Optional[str]:
    """Build an RTF {\\pict\\pngblip...} or {\\pict\\jpegblip...} group for an ImageBlock.

    Returns None when image_bytes is empty or not a supported PNG/JPEG stream.
    """
    data = img.image_bytes
    blip_ctrl = detect_rtf_blip_type(data)
    if blip_ctrl is None:
        return None

    # Intrinsic pixel dimensions
    px_dims = parse_image_pixel_dimensions(data)
    if px_dims is not None:
        picw, pich = px_dims
    elif img.pixel_width and img.pixel_height:
        picw, pich = int(img.pixel_width), int(img.pixel_height)
    else:
        picw = max(1, int(round((img.bbox.width if img.bbox.width > 0 else 72.0) * 96.0 / 72.0)))
        pich = max(1, int(round((img.bbox.height if img.bbox.height > 0 else 72.0) * 96.0 / 72.0)))

    # Desired display size in twips
    if img.bbox.width > 0 and img.bbox.height > 0:
        w_goal = max(120, pt_to_dxa(img.bbox.width))
        h_goal = max(120, pt_to_dxa(img.bbox.height))
    else:
        # 96 DPI default: 1440 twips / 96 px = 15 twips per pixel
        w_goal = max(120, picw * 15)
        h_goal = max(120, pich * 15)

    # Clamp proportionally within printable page width
    if max_width_twips > 0 and w_goal > max_width_twips:
        scale = max_width_twips / float(w_goal)
        w_goal = max_width_twips
        h_goal = max(120, int(round(h_goal * scale)))

    hex_body = encode_hex_lines(data)
    return (
        f"{{\\pict{blip_ctrl}"
        f"\\picw{picw}\\pich{pich}"
        f"\\picwgoal{w_goal}\\pichgoal{h_goal}\n"
        f"{hex_body}\n"
        f"}}"
    )


def render_rtf_image(
    img: ImageBlock,
    codepage: int = 1252,
    max_width_twips: int = DEFAULT_MAX_IMAGE_WIDTH_TWIPS,
    in_table: bool = False,
) -> str:
    """Render an ImageBlock as an embedded RTF \\pict paragraph, or fallback placeholder."""
    pict_group = build_rtf_pict_group(img, max_width_twips=max_width_twips)
    if pict_group is not None:
        if in_table:
            return f"\\pard\\intbl\\qc {pict_group}"
        return f"\\pard\\s0\\qc\\sa120 {pict_group}\\par"

    alt = img.alt_text.strip() if img.alt_text else "Image"
    escaped = encode_rtf_unicode(alt, codepage=codepage)
    if in_table:
        return f"\\pard\\intbl\\qc [{escaped}]"
    return f"\\pard\\s0\\qc\\sa120 [{escaped}]\\par"


__all__ = [
    "DEFAULT_MAX_IMAGE_WIDTH_TWIPS",
    "HEX_LINE_WIDTH",
    "detect_rtf_blip_type",
    "parse_image_pixel_dimensions",
    "encode_hex_lines",
    "build_rtf_pict_group",
    "render_rtf_image",
]
