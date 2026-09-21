"""Pure-Python in-memory PNG serializer and parser.

Implements zero-dependency PNG synthesis (ISO/IEC 15948:2004 / W3C Recommendation)
for embedding raster graphics in documents without external imaging libraries.
"""

from __future__ import annotations

import struct
import zlib
from typing import Optional, Tuple

from anyconvert.exceptions import SerializationError

# Standard 8-byte PNG file signature
PNG_SIGNATURE: bytes = b"\x89PNG\r\n\x1a\n"

# Standard PNG Color Types
COLOR_TYPE_GRAY: int = 0
COLOR_TYPE_RGB: int = 2
COLOR_TYPE_INDEXED: int = 3
COLOR_TYPE_GRAY_ALPHA: int = 4
COLOR_TYPE_RGBA: int = 6


def create_chunk(chunk_type: bytes, data: bytes) -> bytes:
    """Construct a standard PNG chunk with 4-byte length, type, data, and CRC-32.

    Args:
        chunk_type: 4-byte ASCII chunk identifier (e.g. b"IHDR", b"IDAT", b"IEND").
        data: Raw payload of the chunk.

    Returns:
        Complete serialized chunk bytes.
    """
    if len(chunk_type) != 4:
        raise SerializationError(f"PNG chunk type must be 4 bytes, got {len(chunk_type)}")
    length_bytes = struct.pack(">I", len(data))
    crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    crc_bytes = struct.pack(">I", crc)
    return length_bytes + chunk_type + data + crc_bytes


def _bytes_per_row(width: int, color_type: int, bit_depth: int) -> int:
    """Calculate the number of raw uncompressed bytes in a single image row."""
    if color_type == COLOR_TYPE_GRAY:
        bits_per_pixel = bit_depth
    elif color_type == COLOR_TYPE_RGB:
        bits_per_pixel = 3 * bit_depth
    elif color_type == COLOR_TYPE_INDEXED:
        bits_per_pixel = bit_depth
    elif color_type == COLOR_TYPE_GRAY_ALPHA:
        bits_per_pixel = 2 * bit_depth
    elif color_type == COLOR_TYPE_RGBA:
        bits_per_pixel = 4 * bit_depth
    else:
        raise SerializationError(f"Unsupported PNG color type: {color_type}")

    total_bits = width * bits_per_pixel
    return (total_bits + 7) // 8


def encode_png(
    width: int,
    height: int,
    data: bytes,
    color_type: int = COLOR_TYPE_RGBA,
    bit_depth: int = 8,
    palette: Optional[bytes] = None,
    compression_level: int = 6,
) -> bytes:
    """Serialize raw raster pixel data into a standard PNG byte sequence.

    Args:
        width: Image width in pixels (> 0).
        height: Image height in pixels (> 0).
        data: Pixel data. Can either be raw scanline payload (width * height * bpp)
              or pre-filtered scanlines (with 1-byte filter prefix per row).
        color_type: PNG color type (0=Gray, 2=RGB, 3=Indexed, 4=Gray+Alpha, 6=RGBA).
        bit_depth: Bits per component sample (1, 2, 4, 8, 16).
        palette: Optional RGB palette bytes for indexed color type 3.
        compression_level: zlib compression level (0-9).

    Returns:
        Complete in-memory PNG file byte sequence.

    Raises:
        SerializationError: If dimensions or data lengths are invalid.
    """
    if width <= 0 or height <= 0:
        raise SerializationError(f"Invalid image dimensions: {width}x{height}")

    # Validate bit depth for color type
    valid_depths = {
        COLOR_TYPE_GRAY: (1, 2, 4, 8, 16),
        COLOR_TYPE_RGB: (8, 16),
        COLOR_TYPE_INDEXED: (1, 2, 4, 8),
        COLOR_TYPE_GRAY_ALPHA: (8, 16),
        COLOR_TYPE_RGBA: (8, 16),
    }
    if color_type not in valid_depths:
        raise SerializationError(f"Unsupported PNG color type: {color_type}")
    if bit_depth not in valid_depths[color_type]:
        raise SerializationError(
            f"Invalid bit depth {bit_depth} for color type {color_type}"
        )

    row_bytes = _bytes_per_row(width, color_type, bit_depth)
    unfiltered_size = row_bytes * height
    filtered_size = (row_bytes + 1) * height

    # Prepare scanlines with filter type 0 (None) prefix per row if not already present
    if len(data) == unfiltered_size:
        scanlines = bytearray(filtered_size)
        in_offset = 0
        out_offset = 0
        for _ in range(height):
            scanlines[out_offset] = 0  # Filter type 0: None
            out_offset += 1
            scanlines[out_offset : out_offset + row_bytes] = data[in_offset : in_offset + row_bytes]
            in_offset += row_bytes
            out_offset += row_bytes
        filtered_data = bytes(scanlines)
    elif len(data) == filtered_size:
        filtered_data = data
    else:
        raise SerializationError(
            f"Invalid pixel buffer size: expected {unfiltered_size} (raw) "
            f"or {filtered_size} (filtered) bytes, got {len(data)}"
        )

    # 1. Signature
    chunks: list[bytes] = [PNG_SIGNATURE]

    # 2. IHDR Chunk (13 bytes)
    # Width (4), Height (4), Bit Depth (1), Color Type (1), Compression (1=0), Filter (1=0), Interlace (1=0)
    ihdr_payload = struct.pack(
        ">IIBBBBB",
        width,
        height,
        bit_depth,
        color_type,
        0,  # Deflate compression
        0,  # Adaptive filtering
        0,  # No interlace
    )
    chunks.append(create_chunk(b"IHDR", ihdr_payload))

    # 3. PLTE Chunk (if Indexed color)
    if color_type == COLOR_TYPE_INDEXED:
        if palette is None or len(palette) == 0:
            raise SerializationError("Indexed PNG requires a non-empty palette")
        if len(palette) % 3 != 0:
            raise SerializationError("PLTE palette length must be a multiple of 3 (RGB)")
        chunks.append(create_chunk(b"PLTE", palette))

    # 4. IDAT Chunk (zlib compressed scanlines)
    compressed_idat = zlib.compress(filtered_data, level=compression_level)
    chunks.append(create_chunk(b"IDAT", compressed_idat))

    # 5. IEND Chunk
    chunks.append(create_chunk(b"IEND", b""))

    return b"".join(chunks)


def encode_rgba_png(width: int, height: int, rgba_bytes: bytes) -> bytes:
    """Encode an 8-bit RGBA raw byte buffer into a PNG.

    Args:
        width: Image width in pixels.
        height: Image height in pixels.
        rgba_bytes: Interleaved RGBA bytes (len = width * height * 4).

    Returns:
        Valid PNG bytes.
    """
    return encode_png(
        width=width,
        height=height,
        data=rgba_bytes,
        color_type=COLOR_TYPE_RGBA,
        bit_depth=8,
    )


def encode_rgb_png(width: int, height: int, rgb_bytes: bytes) -> bytes:
    """Encode an 8-bit RGB raw byte buffer into a PNG.

    Args:
        width: Image width in pixels.
        height: Image height in pixels.
        rgb_bytes: Interleaved RGB bytes (len = width * height * 3).

    Returns:
        Valid PNG bytes.
    """
    return encode_png(
        width=width,
        height=height,
        data=rgb_bytes,
        color_type=COLOR_TYPE_RGB,
        bit_depth=8,
    )


def encode_gray_png(width: int, height: int, gray_bytes: bytes, bit_depth: int = 8) -> bytes:
    """Encode an 8-bit or 1-bit grayscale raw byte buffer into a PNG.

    Args:
        width: Image width in pixels.
        height: Image height in pixels.
        gray_bytes: Grayscale bytes.
        bit_depth: 1, 2, 4, 8, or 16.

    Returns:
        Valid PNG bytes.
    """
    return encode_png(
        width=width,
        height=height,
        data=gray_bytes,
        color_type=COLOR_TYPE_GRAY,
        bit_depth=bit_depth,
    )


def parse_png(data: bytes) -> Tuple[int, int, int, int, bytes]:
    """Parse and validate a PNG byte sequence without external dependencies.

    Extracts dimensions, color characteristics, and unfiltered pixel data.

    Args:
        data: Complete PNG file byte sequence.

    Returns:
        Tuple of (width, height, color_type, bit_depth, raw_unfiltered_pixels).

    Raises:
        SerializationError: If signature or chunks are malformed.
    """
    if len(data) < 8 or data[:8] != PNG_SIGNATURE:
        raise SerializationError("Invalid PNG signature")

    offset = 8
    width = 0
    height = 0
    bit_depth = 8
    color_type = COLOR_TYPE_RGBA
    idat_chunks: list[bytes] = []

    while offset < len(data):
        if offset + 8 > len(data):
            raise SerializationError("Truncated PNG chunk header")

        chunk_len = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        offset += 8

        if offset + chunk_len + 4 > len(data):
            raise SerializationError(f"Truncated PNG chunk data for {chunk_type!r}")

        chunk_data = data[offset : offset + chunk_len]
        crc_actual = struct.unpack(">I", data[offset + chunk_len : offset + chunk_len + 4])[0]
        offset += chunk_len + 4

        # Verify CRC
        crc_expected = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
        if crc_actual != crc_expected:
            raise SerializationError(
                f"CRC-32 checksum mismatch for chunk {chunk_type!r}: "
                f"expected {crc_expected:#010x}, got {crc_actual:#010x}"
            )

        if chunk_type == b"IHDR":
            if chunk_len < 13:
                raise SerializationError("Invalid IHDR chunk length")
            w, h, bd, ct, comp, filt, inter = struct.unpack(">IIBBBBB", chunk_data[:13])
            width = w
            height = h
            bit_depth = bd
            color_type = ct
        elif chunk_type == b"IDAT":
            idat_chunks.append(chunk_data)
        elif chunk_type == b"IEND":
            break

    if width == 0 or height == 0:
        raise SerializationError("Missing or invalid IHDR chunk")

    compressed_idat = b"".join(idat_chunks)
    decompressed = zlib.decompress(compressed_idat)

    row_bytes = _bytes_per_row(width, color_type, bit_depth)
    expected_decompressed = height * (row_bytes + 1)
    if len(decompressed) != expected_decompressed:
        raise SerializationError(
            f"Decompressed IDAT length mismatch: expected {expected_decompressed}, got {len(decompressed)}"
        )

    # Reconstruct unfiltered rows
    bpp = max(1, row_bytes // width)
    unfiltered = bytearray(height * row_bytes)
    prev_row = bytearray(row_bytes)
    in_pos = 0
    out_pos = 0

    for _ in range(height):
        filter_type = decompressed[in_pos]
        in_pos += 1
        curr_raw = decompressed[in_pos : in_pos + row_bytes]
        in_pos += row_bytes

        recon_row = bytearray(row_bytes)
        if filter_type == 0:  # None
            recon_row[:] = curr_raw
        elif filter_type == 1:  # Sub
            for i in range(row_bytes):
                left = recon_row[i - bpp] if i >= bpp else 0
                recon_row[i] = (curr_raw[i] + left) & 0xFF
        elif filter_type == 2:  # Up
            for i in range(row_bytes):
                up = prev_row[i]
                recon_row[i] = (curr_raw[i] + up) & 0xFF
        elif filter_type == 3:  # Average
            for i in range(row_bytes):
                left = recon_row[i - bpp] if i >= bpp else 0
                up = prev_row[i]
                recon_row[i] = (curr_raw[i] + ((left + up) >> 1)) & 0xFF
        elif filter_type == 4:  # Paeth
            for i in range(row_bytes):
                a = recon_row[i - bpp] if i >= bpp else 0
                b = prev_row[i]
                c = prev_row[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa = abs(p - a)
                pb = abs(p - b)
                pc = abs(p - c)
                if pa <= pb and pa <= pc:
                    pr = a
                elif pb <= pc:
                    pr = b
                else:
                    pr = c
                recon_row[i] = (curr_raw[i] + pr) & 0xFF
        else:
            raise SerializationError(f"Unsupported PNG filter type: {filter_type}")

        unfiltered[out_pos : out_pos + row_bytes] = recon_row
        out_pos += row_bytes
        prev_row = recon_row

    return (width, height, color_type, bit_depth, bytes(unfiltered))


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
