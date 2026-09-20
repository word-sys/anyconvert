"""FlateDecode (Deflate/Zlib) stream decompression and row predictor reversal.

Adheres to PDF 32000-1 §7.4.4.4, RFC 1950/1951, and TIFF/PNG predictor standards:
- Predictor 1: None
- Predictor 2: TIFF Predictor 2 (horizontal differencing across 1, 2, 4, 8, 16 bits/component)
- Predictor 10-15: PNG Predictors (None, Sub, Up, Average, Paeth)
"""

from __future__ import annotations

import math
import zlib
from typing import Optional

from anyconvert.exceptions import PDFSyntaxError, PDFUnsupportedFilterError
from anyconvert.pdf.parser import PDFDict


def flate_decode(data: bytes, params: Optional[PDFDict] = None) -> bytes:
    """Decompress Flate (Zlib/Deflate) stream with row predictor reversal.

    Args:
        data: Compressed Deflate/Zlib byte stream.
        params: Optional /DecodeParms dictionary.

    Returns:
        bytes: Decompressed binary data with predictors reversed.

    Raises:
        PDFSyntaxError: If zlib decompression or predictor reversal fails.
    """
    if not data:
        return b""

    try:
        # Standard zlib stream decompression
        decompressed = zlib.decompress(data)
    except zlib.error:
        try:
            # Fallback to raw Deflate without zlib wrapper header
            decompressed = zlib.decompress(data, -zlib.MAX_WBITS)
        except zlib.error as err:
            raise PDFSyntaxError(f"Flate decompression error: {err}") from err

    if params is None:
        return decompressed

    predictor = params.get("Predictor", 1)
    if not isinstance(predictor, int) or predictor <= 1:
        return decompressed

    columns = int(params.get("Columns", 1))
    colors = int(params.get("Colors", 1))
    bits_per_component = int(params.get("BitsPerComponent", 8))

    # Apply row predictor reversal
    return apply_predictor_reversal(
        data=decompressed,
        predictor=predictor,
        columns=columns,
        colors=colors,
        bpc=bits_per_component,
    )


def apply_predictor_reversal(
    data: bytes,
    predictor: int,
    columns: int,
    colors: int,
    bpc: int,
) -> bytes:
    """Reverse TIFF or PNG predictor math over decompressed stream data.

    Args:
        data: Decompressed raw byte data.
        predictor: Predictor algorithm code (2 = TIFF, 10-15 = PNG).
        columns: Samples per row.
        colors: Color channels per sample.
        bpc: Bits per component (1, 2, 4, 8, 16).

    Returns:
        bytes: Reconstructed byte stream.
    """
    row_bytes = (columns * colors * bpc + 7) // 8

    if predictor == 2:
        # TIFF Predictor 2: Horizontal differencing
        return _reverse_tiff_predictor(data, columns, colors, bpc, row_bytes)
    elif 10 <= predictor <= 15:
        # PNG Predictors: 1-byte filter tag + row_bytes per scanline
        return _reverse_png_predictor_multi_bpc(data, columns, colors, bpc, row_bytes)
    else:
        raise PDFUnsupportedFilterError(f"Unsupported predictor code: {predictor}")


def _reverse_tiff_predictor(
    data: bytes, columns: int, colors: int, bpc: int, row_bytes: int
) -> bytes:
    """Reverse TIFF Predictor 2 (horizontal differencing)."""
    if row_bytes == 0:
        return data

    out = bytearray(data)
    num_rows = len(out) // row_bytes

    if bpc == 8:
        bpp = colors
        for r in range(num_rows):
            row_start = r * row_bytes
            for c in range(bpp, row_bytes):
                out[row_start + c] = (out[row_start + c] + out[row_start + c - bpp]) & 0xFF
    elif bpc == 16:
        samples_per_row = columns * colors
        # 16-bit big-endian samples
        for r in range(num_rows):
            row_start = r * row_bytes
            for c in range(colors, samples_per_row):
                idx = row_start + c * 2
                prev_idx = row_start + (c - colors) * 2
                val = (out[idx] << 8) | out[idx + 1]
                prev_val = (out[prev_idx] << 8) | out[prev_idx + 1]
                res = (val + prev_val) & 0xFFFF
                out[idx] = (res >> 8) & 0xFF
                out[idx + 1] = res & 0xFF
    else:
        # Sub-byte (1, 2, 4 bit) components
        # Bit-level unpacking, addition, and repacking
        bpp = colors
        for r in range(num_rows):
            row_start = r * row_bytes
            row_slice = out[row_start : row_start + row_bytes]
            # Unpack samples
            samples: list[int] = []
            mask = (1 << bpc) - 1
            bit_acc = 0
            bits_in_acc = 0

            for byte in row_slice:
                bit_acc = (bit_acc << 8) | byte
                bits_in_acc += 8
                while bits_in_acc >= bpc and len(samples) < columns * colors:
                    bits_in_acc -= bpc
                    sample = (bit_acc >> bits_in_acc) & mask
                    samples.append(sample)

            # Reverse differencing
            for c in range(bpp, len(samples)):
                samples[c] = (samples[c] + samples[c - bpp]) & mask

            # Repack samples
            repacked = bytearray(row_bytes)
            pack_acc = 0
            pack_bits = 0
            byte_idx = 0

            for sample in samples:
                pack_acc = (pack_acc << bpc) | sample
                pack_bits += bpc
                if pack_bits >= 8:
                    pack_bits -= 8
                    repacked[byte_idx] = (pack_acc >> pack_bits) & 0xFF
                    byte_idx += 1

            if pack_bits > 0 and byte_idx < row_bytes:
                repacked[byte_idx] = (pack_acc << (8 - pack_bits)) & 0xFF

            out[row_start : row_start + row_bytes] = repacked

    return bytes(out)


def _reverse_png_predictor_multi_bpc(
    data: bytes, columns: int, colors: int, bpc: int, row_bytes: int
) -> bytes:
    """Reverse PNG row predictors (10-15) supporting arbitrary bits per component."""
    line_bytes = 1 + row_bytes
    if line_bytes <= 1:
        return data

    num_rows = len(data) // line_bytes
    out = bytearray(num_rows * row_bytes)
    prev_row = bytearray(row_bytes)
    bpp = max(1, (colors * bpc + 7) // 8)

    for r in range(num_rows):
        row_offset = r * line_bytes
        filter_type = data[row_offset]
        row_raw = data[row_offset + 1 : row_offset + line_bytes]
        curr_row = bytearray(row_bytes)

        if filter_type == 0:  # None
            curr_row[:] = row_raw
        elif filter_type == 1:  # Sub
            for i in range(row_bytes):
                left = curr_row[i - bpp] if i >= bpp else 0
                curr_row[i] = (row_raw[i] + left) & 0xFF
        elif filter_type == 2:  # Up
            for i in range(row_bytes):
                up = prev_row[i]
                curr_row[i] = (row_raw[i] + up) & 0xFF
        elif filter_type == 3:  # Average
            for i in range(row_bytes):
                left = curr_row[i - bpp] if i >= bpp else 0
                up = prev_row[i]
                curr_row[i] = (row_raw[i] + ((left + up) >> 1)) & 0xFF
        elif filter_type == 4:  # Paeth
            for i in range(row_bytes):
                left = curr_row[i - bpp] if i >= bpp else 0
                up = prev_row[i]
                upper_left = prev_row[i - bpp] if i >= bpp else 0

                p = left + up - upper_left
                pa = abs(p - left)
                pb = abs(p - up)
                pc = abs(p - upper_left)

                if pa <= pb and pa <= pc:
                    pr = left
                elif pb <= pc:
                    pr = up
                else:
                    pr = upper_left

                curr_row[i] = (row_raw[i] + pr) & 0xFF
        else:
            curr_row[:] = row_raw

        out[r * row_bytes : (r + 1) * row_bytes] = curr_row
        prev_row = curr_row

    return bytes(out)
