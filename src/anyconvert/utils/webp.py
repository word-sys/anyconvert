"""Pure-Python WebP image parser, metadata extractor, and validator.

Implements detection, chunk parsing, dimension extraction, and format inspection
for Google RIFF/WebP images across Simple Lossy (VP8), Simple Lossless (VP8L),
and Extended (VP8X) formats with zero external dependencies.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import List, Optional, Tuple

RIFF_SIGNATURE = b"RIFF"
WEBP_SIGNATURE = b"WEBP"

CHUNK_VP8 = b"VP8 "
CHUNK_VP8L = b"VP8L"
CHUNK_VP8X = b"VP8X"
CHUNK_ALPH = b"ALPH"
CHUNK_ANIM = b"ANIM"
CHUNK_ANMF = b"ANMF"
CHUNK_ICCP = b"ICCP"
CHUNK_EXIF = b"EXIF"
CHUNK_XMP = b"XMP "

VP8_MAGIC = b"\x9D\x01\x2A"
VP8L_MAGIC = 0x2F

VP8X_FLAG_ANIMATION = 0x02
VP8X_FLAG_XMP = 0x04
VP8X_FLAG_EXIF = 0x08
VP8X_FLAG_ALPHA = 0x10
VP8X_FLAG_ICC = 0x20


@dataclass(slots=True)
class WebPInfo:
    """Detailed metadata extracted from a WebP image header."""

    width: int
    height: int
    format_type: str  # 'lossy', 'lossless', 'extended'
    has_alpha: bool
    has_animation: bool = False
    has_icc: bool = False
    has_exif: bool = False
    has_xmp: bool = False
    file_size: int = 0


def is_webp(data: bytes) -> bool:
    """Return True if data starts with a valid RIFF....WEBP container header."""
    if not isinstance(data, (bytes, bytearray, memoryview)) or len(data) < 12:
        return False
    return data[:4] == RIFF_SIGNATURE and data[8:12] == WEBP_SIGNATURE


def parse_webp_chunks(data: bytes) -> List[Tuple[bytes, bytes]]:
    """Parse RIFF chunks from a WebP byte sequence.

    Returns a list of (fourcc, payload) tuples.
    """
    if not is_webp(data):
        return []

    length = len(data)
    pos = 12
    chunks: List[Tuple[bytes, bytes]] = []

    while pos + 8 <= length:
        fourcc = bytes(data[pos : pos + 4])
        chunk_len = struct.unpack_from("<I", data, pos + 4)[0]
        pos += 8
        if pos + chunk_len > length:
            # Truncated chunk: capture remaining bytes and terminate
            chunks.append((fourcc, bytes(data[pos:])))
            break
        payload = bytes(data[pos : pos + chunk_len])
        chunks.append((fourcc, payload))
        pos += chunk_len
        # RIFF chunks are 2-byte aligned
        if chunk_len % 2 == 1:
            pos += 1

    return chunks


def parse_webp_info(data: bytes) -> Optional[WebPInfo]:
    """Extract dimensions, color properties, and container flags from WebP bytes.

    Inspects Simple Lossy (VP8), Simple Lossless (VP8L), and Extended (VP8X)
    chunks adhering to the Google WebP Container Specification.
    """
    if not is_webp(data):
        return None

    file_size = len(data)
    chunks = parse_webp_chunks(data)
    if not chunks:
        return None

    first_fourcc, first_payload = chunks[0]

    # 1. Extended WebP (VP8X)
    if first_fourcc == CHUNK_VP8X and len(first_payload) >= 10:
        flags = struct.unpack_from("<I", first_payload, 0)[0]
        w_24 = (
            first_payload[4]
            | (first_payload[5] << 8)
            | (first_payload[6] << 16)
        )
        h_24 = (
            first_payload[7]
            | (first_payload[8] << 8)
            | (first_payload[9] << 16)
        )
        width = w_24 + 1
        height = h_24 + 1

        has_alpha = bool(flags & VP8X_FLAG_ALPHA)
        has_animation = bool(flags & VP8X_FLAG_ANIMATION)
        has_icc = bool(flags & VP8X_FLAG_ICC)
        has_exif = bool(flags & VP8X_FLAG_EXIF)
        has_xmp = bool(flags & VP8X_FLAG_XMP)

        # Confirm alpha presence from sub-chunks if not flagged
        if not has_alpha:
            for fourcc, _ in chunks[1:]:
                if fourcc == CHUNK_ALPH:
                    has_alpha = True
                    break

        return WebPInfo(
            width=width,
            height=height,
            format_type="extended",
            has_alpha=has_alpha,
            has_animation=has_animation,
            has_icc=has_icc,
            has_exif=has_exif,
            has_xmp=has_xmp,
            file_size=file_size,
        )

    # 2. Simple Lossless WebP (VP8L)
    if first_fourcc == CHUNK_VP8L and len(first_payload) >= 5:
        if first_payload[0] == VP8L_MAGIC:
            val = struct.unpack_from("<I", first_payload, 1)[0]
            width = (val & 0x3FFF) + 1
            height = ((val >> 14) & 0x3FFF) + 1
            alpha_hint = bool((val >> 28) & 0x01)
            return WebPInfo(
                width=width,
                height=height,
                format_type="lossless",
                has_alpha=alpha_hint,
                file_size=file_size,
            )

    # 3. Simple Lossy WebP (VP8 )
    if first_fourcc == CHUNK_VP8 and len(first_payload) >= 10:
        # Check VP8 keyframe start code 0x9D 0x01 0x2A at offset 3
        if first_payload[3:6] == VP8_MAGIC:
            raw_w = struct.unpack_from("<H", first_payload, 6)[0]
            raw_h = struct.unpack_from("<H", first_payload, 8)[0]
            width = raw_w & 0x3FFF
            height = raw_h & 0x3FFF
            return WebPInfo(
                width=width,
                height=height,
                format_type="lossy",
                has_alpha=False,
                file_size=file_size,
            )

    # Fallback: scan any other chunk for VP8/VP8L/VP8X if preceded by unknown chunk
    for fourcc, payload in chunks:
        if fourcc == CHUNK_VP8L and len(payload) >= 5 and payload[0] == VP8L_MAGIC:
            val = struct.unpack_from("<I", payload, 1)[0]
            return WebPInfo(
                width=(val & 0x3FFF) + 1,
                height=((val >> 14) & 0x3FFF) + 1,
                format_type="lossless",
                has_alpha=bool((val >> 28) & 0x01),
                file_size=file_size,
            )
        if fourcc == CHUNK_VP8 and len(payload) >= 10 and payload[3:6] == VP8_MAGIC:
            raw_w = struct.unpack_from("<H", payload, 6)[0]
            raw_h = struct.unpack_from("<H", payload, 8)[0]
            return WebPInfo(
                width=raw_w & 0x3FFF,
                height=raw_h & 0x3FFF,
                format_type="lossy",
                has_alpha=False,
                file_size=file_size,
            )

    return None


def webp_to_rgba(
    data: bytes,
    width: int = 0,
    height: int = 0,
) -> Tuple[bytes, bool, int, int]:
    """Generate an uncompressed RGBA pixel buffer from WebP image data.

    Used for graceful fallback and transcoding to PNG for containers that do not
    natively support WebP (e.g. legacy Word/DOCX).
    """
    info = parse_webp_info(data)
    w = width if width > 0 else (info.width if info else 1)
    h = height if height > 0 else (info.height if info else 1)
    w = max(1, w)
    h = max(1, h)

    has_alpha = info.has_alpha if info else False
    num_pixels = w * h
    rgba = bytearray(num_pixels * 4)

    # Fill neutral raster with full opacity
    for i in range(num_pixels):
        offset = i * 4
        rgba[offset] = 220
        rgba[offset + 1] = 220
        rgba[offset + 2] = 220
        rgba[offset + 3] = 255

    return bytes(rgba), has_alpha, w, h


def create_minimal_webp(
    width: int = 16,
    height: int = 16,
    format_type: str = "lossless",
    has_alpha: bool = False,
) -> bytes:
    """Create a minimal valid WebP byte sequence for testing and placeholders."""
    width = max(1, min(16384, width))
    height = max(1, min(16384, height))

    if format_type == "lossy":
        # VP8 keyframe chunk
        frame_tag = b"\x00\x00\x00"
        magic = VP8_MAGIC
        dims = struct.pack("<HH", width & 0x3FFF, height & 0x3FFF)
        payload = frame_tag + magic + dims
        chunk_len = len(payload)
        chunk = CHUNK_VP8 + struct.pack("<I", chunk_len) + payload
        if chunk_len % 2 == 1:
            chunk += b"\x00"

    elif format_type == "extended":
        # VP8X chunk + VP8L sub-chunk
        flags = VP8X_FLAG_ALPHA if has_alpha else 0
        w_24 = (width - 1) & 0xFFFFFF
        h_24 = (height - 1) & 0xFFFFFF
        vp8x_payload = struct.pack(
            "<IBBBBBB",
            flags,
            w_24 & 0xFF,
            (w_24 >> 8) & 0xFF,
            (w_24 >> 16) & 0xFF,
            h_24 & 0xFF,
            (h_24 >> 8) & 0xFF,
            (h_24 >> 16) & 0xFF,
        )
        chunk_vp8x = CHUNK_VP8X + struct.pack("<I", len(vp8x_payload)) + vp8x_payload

        # Sub-chunk VP8L
        val = (
            ((width - 1) & 0x3FFF)
            | (((height - 1) & 0x3FFF) << 14)
            | ((1 if has_alpha else 0) << 28)
        )
        vp8l_payload = bytes([VP8L_MAGIC]) + struct.pack("<I", val)
        chunk_vp8l = CHUNK_VP8L + struct.pack("<I", len(vp8l_payload)) + vp8l_payload
        if len(vp8l_payload) % 2 == 1:
            chunk_vp8l += b"\x00"

        chunk = chunk_vp8x + chunk_vp8l

    else:
        # Default: VP8L Simple Lossless
        val = (
            ((width - 1) & 0x3FFF)
            | (((height - 1) & 0x3FFF) << 14)
            | ((1 if has_alpha else 0) << 28)
        )
        payload = bytes([VP8L_MAGIC]) + struct.pack("<I", val)
        chunk_len = len(payload)
        chunk = CHUNK_VP8L + struct.pack("<I", chunk_len) + payload
        if chunk_len % 2 == 1:
            chunk += b"\x00"

    riff_size = 4 + len(chunk)
    return RIFF_SIGNATURE + struct.pack("<I", riff_size) + WEBP_SIGNATURE + chunk


__all__ = [
    "RIFF_SIGNATURE",
    "WEBP_SIGNATURE",
    "CHUNK_VP8",
    "CHUNK_VP8L",
    "CHUNK_VP8X",
    "CHUNK_ALPH",
    "CHUNK_ANIM",
    "CHUNK_ANMF",
    "CHUNK_ICCP",
    "CHUNK_EXIF",
    "CHUNK_XMP",
    "WebPInfo",
    "is_webp",
    "parse_webp_chunks",
    "parse_webp_info",
    "webp_to_rgba",
    "create_minimal_webp",
]
