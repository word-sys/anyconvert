"""PDF raster image extraction, color space decoding, and mask blending.

Implements pure-Python unpacking of PDF Image XObjects across DeviceGray,
DeviceRGB, DeviceCMYK, and Indexed color spaces, with support for 1/2/4/8/16
bits per component, soft alpha masks (/SMask), explicit masks (/Mask),
and color key masking.
"""

from __future__ import annotations

import math
from typing import Any, List, Optional, Sequence, Tuple, Union

from anyconvert.exceptions import PDFSyntaxError, SerializationError
from anyconvert.pdf.filters import decode_stream
from anyconvert.pdf.parser import (
    PDFArray,
    PDFDict,
    PDFHexString,
    PDFIndirectRef,
    PDFName,
    PDFStream,
    PDFString,
)
from anyconvert.pdf.xref import XRefResolver
from anyconvert.utils.png import encode_gray_png, encode_rgb_png, encode_rgba_png


class PDFImage:
    """Represents a raster image extracted from a PDF Image XObject stream."""

    __slots__ = (
        "width",
        "height",
        "color_space_name",
        "bits_per_component",
        "has_alpha",
        "rgba_pixels",
        "format",
        "raw_data",
        "stream",
    )

    def __init__(
        self,
        width: int,
        height: int,
        color_space_name: str,
        bits_per_component: int,
        rgba_pixels: bytes,
        has_alpha: bool = False,
        format: str = "png",
        raw_data: bytes = b"",
        stream: Optional[PDFStream] = None,
    ) -> None:
        self.width = width
        self.height = height
        self.color_space_name = color_space_name
        self.bits_per_component = bits_per_component
        self.has_alpha = has_alpha
        self.rgba_pixels = rgba_pixels
        self.format = format
        self.raw_data = raw_data
        self.stream = stream

    def to_rgba(self) -> bytes:
        """Return raw 8-bit RGBA pixel buffer (width * height * 4 bytes)."""
        return self.rgba_pixels

    def to_rgb(self) -> bytes:
        """Return raw 8-bit RGB pixel buffer (width * height * 3 bytes)."""
        num_pixels = self.width * self.height
        rgb = bytearray(num_pixels * 3)
        src = self.rgba_pixels
        in_pos = 0
        out_pos = 0
        for _ in range(num_pixels):
            rgb[out_pos : out_pos + 3] = src[in_pos : in_pos + 3]
            in_pos += 4
            out_pos += 3
        return bytes(rgb)

    def to_gray(self) -> bytes:
        """Return raw 8-bit grayscale pixel buffer (width * height bytes)."""
        num_pixels = self.width * self.height
        gray = bytearray(num_pixels)
        src = self.rgba_pixels
        in_pos = 0
        for i in range(num_pixels):
            r = src[in_pos]
            g = src[in_pos + 1]
            b = src[in_pos + 2]
            # Standard Rec. 601 luma formula
            gray[i] = min(255, max(0, round(0.299 * r + 0.587 * g + 0.114 * b)))
            in_pos += 4
        return bytes(gray)

    def to_png(self) -> bytes:
        """Serialize image to a standard PNG byte sequence in memory."""
        if self.has_alpha:
            return encode_rgba_png(self.width, self.height, self.rgba_pixels)
        if self.color_space_name in ("DeviceGray", "CalGray"):
            return encode_gray_png(self.width, self.height, self.to_gray(), bit_depth=8)
        return encode_rgb_png(self.width, self.height, self.to_rgb())

    @classmethod
    def from_stream(
        cls,
        stream: PDFStream,
        resolver: Optional[XRefResolver] = None,
    ) -> PDFImage:
        """Decode and construct a PDFImage from a PDF stream object.

        Args:
            stream: PDFStream representing an Image XObject.
            resolver: Optional XRefResolver for resolving indirect references.

        Returns:
            Fully decoded PDFImage instance.

        Raises:
            PDFSyntaxError: If the stream dictionary is missing required attributes.
            SerializationError: If decoding fails due to corrupt image data.
        """
        sdict = stream.dict

        def deref(obj: Any) -> Any:
            if resolver is not None:
                return resolver.dereference(obj)
            return obj

        # Verify XObject subtype
        subtype = deref(sdict.get("Subtype"))
        st_name = subtype.name if isinstance(subtype, PDFName) else str(subtype)
        if st_name != "Image":
            raise PDFSyntaxError(f"Expected XObject /Subtype /Image, got {st_name!r}")

        # Dimensions
        w_val = deref(sdict.get("Width"))
        h_val = deref(sdict.get("Height"))
        if not isinstance(w_val, int) or not isinstance(h_val, int) or w_val <= 0 or h_val <= 0:
            raise PDFSyntaxError(f"Invalid image dimensions: {w_val}x{h_val}")
        width = w_val
        height = h_val

        # ImageMask
        is_mask = bool(deref(sdict.get("ImageMask", False)))

        # BitsPerComponent
        if is_mask:
            bpc = 1
        else:
            bpc_val = deref(sdict.get("BitsPerComponent", 8))
            bpc = int(bpc_val) if isinstance(bpc_val, (int, float)) else 8

        if bpc not in (1, 2, 4, 8, 16):
            raise PDFSyntaxError(f"Unsupported BitsPerComponent: {bpc}")

        # Decode array
        decode_raw = deref(sdict.get("Decode"))
        decode_list: Optional[list[float]] = None
        if isinstance(decode_raw, (list, PDFArray)):
            decode_list = [float(deref(x)) for x in decode_raw]

        # Decompress stream data
        filter_spec = sdict.get("Filter")
        params_spec = sdict.get("DecodeParms")
        raw_payload = stream.get_raw_bytes()
        decoded_bytes = decode_stream(raw_payload, filter_spec, params_spec)

        # Detect DCTDecode (JPEG)
        # If stream is JPEG, verify JPEG header
        is_dct = False
        if filter_spec:
            f_norm = filter_spec.name if isinstance(filter_spec, PDFName) else str(filter_spec)
            if "DCT" in f_norm:
                is_dct = True
        if decoded_bytes.startswith(b"\xFF\xD8\xFF"):
            is_dct = True

        # Resolve ColorSpace
        cs_obj = deref(sdict.get("ColorSpace")) if not is_mask else None
        color_space_name, num_components, cs_extra = _resolve_color_space(
            cs_obj, is_mask, len(decoded_bytes), width, height, bpc, resolver
        )

        # Unpack raw samples into rows: list of rows, each having (width * num_components) raw int samples
        raw_rows = _unpack_samples(
            data=decoded_bytes,
            width=width,
            height=height,
            num_components=num_components,
            bpc=bpc,
        )

        # Convert unpacked samples to RGBA pixel buffer
        rgba_buffer, has_alpha = _samples_to_rgba(
            raw_rows=raw_rows,
            width=width,
            height=height,
            color_space_name=color_space_name,
            num_components=num_components,
            bpc=bpc,
            decode_list=decode_list,
            cs_extra=cs_extra,
            is_mask=is_mask,
        )

        # Blend Transparency: Soft Mask (/SMask)
        smask_ref = sdict.get("SMask")
        if smask_ref is not None:
            smask_obj = deref(smask_ref)
            if isinstance(smask_obj, PDFStream):
                smask_img = cls.from_stream(smask_obj, resolver=resolver)
                _blend_smask(rgba_buffer, width, height, smask_img)
                has_alpha = True

        # Blend Transparency: Explicit 1-bit /Mask stream or Color Key /Mask array
        mask_ref = sdict.get("Mask")
        if mask_ref is not None:
            mask_obj = deref(mask_ref)
            if isinstance(mask_obj, PDFStream):
                mask_img = cls.from_stream(mask_obj, resolver=resolver)
                _blend_explicit_mask(rgba_buffer, width, height, mask_img)
                has_alpha = True
            elif isinstance(mask_obj, (list, PDFArray)):
                mask_ranges = [int(deref(x)) for x in mask_obj]
                _blend_color_key_mask(rgba_buffer, raw_rows, width, height, num_components, mask_ranges)
                has_alpha = True

        return cls(
            width=width,
            height=height,
            color_space_name=color_space_name,
            bits_per_component=bpc,
            rgba_pixels=bytes(rgba_buffer),
            has_alpha=has_alpha,
            format="jpeg" if is_dct else "png",
            raw_data=decoded_bytes,
            stream=stream,
        )


def _resolve_color_space(
    cs_obj: Any,
    is_mask: bool,
    data_len: int,
    width: int,
    height: int,
    bpc: int,
    resolver: Optional[XRefResolver],
) -> Tuple[str, int, dict[str, Any]]:
    """Determine color space name, number of components, and auxiliary metadata."""
    if is_mask:
        return "ImageMask", 1, {}

    def deref(o: Any) -> Any:
        return resolver.dereference(o) if resolver is not None else o

    extra: dict[str, Any] = {}

    if cs_obj is None:
        # Infer from data length
        row_bytes_3 = (width * 3 * bpc + 7) // 8
        if data_len >= height * row_bytes_3:
            return "DeviceRGB", 3, {}
        return "DeviceGray", 1, {}

    if isinstance(cs_obj, (PDFName, str)):
        name = cs_obj.name if isinstance(cs_obj, PDFName) else str(cs_obj)
        clean = name[1:] if name.startswith("/") else name
        if clean in ("DeviceRGB", "RGB"):
            return "DeviceRGB", 3, {}
        if clean in ("DeviceGray", "G"):
            return "DeviceGray", 1, {}
        if clean in ("DeviceCMYK", "CMYK"):
            return "DeviceCMYK", 4, {}
        # Default fallback
        return clean, 3, {}

    if isinstance(cs_obj, (list, PDFArray)) and len(cs_obj) > 0:
        cs_type = deref(cs_obj[0])
        type_name = cs_type.name if isinstance(cs_type, PDFName) else str(cs_type)
        type_clean = type_name[1:] if type_name.startswith("/") else type_name

        if type_clean in ("Indexed", "I"):
            base_cs = deref(cs_obj[1])
            base_name, base_comps, _ = _resolve_color_space(
                base_cs, False, data_len, width, height, bpc, resolver
            )
            hival = int(deref(cs_obj[2]))
            lookup_obj = deref(cs_obj[3])
            lookup_bytes: bytes = b""
            if isinstance(lookup_obj, PDFStream):
                lookup_bytes = decode_stream(lookup_obj.get_raw_bytes(), lookup_obj.dict.get("Filter"))
            elif isinstance(lookup_obj, (PDFString, PDFHexString)):
                lookup_bytes = lookup_obj.as_bytes()
            elif isinstance(lookup_obj, str):
                lookup_bytes = lookup_obj.encode("latin-1")
            elif isinstance(lookup_obj, bytes):
                lookup_bytes = lookup_obj
            elif isinstance(lookup_obj, memoryview):
                lookup_bytes = bytes(lookup_obj)

            extra["base_name"] = base_name
            extra["base_comps"] = base_comps
            extra["hival"] = hival
            extra["lookup"] = lookup_bytes
            return "Indexed", 1, extra

        if type_clean == "Separation":
            alt_cs = deref(cs_obj[2])
            alt_name, alt_comps, _ = _resolve_color_space(
                alt_cs, False, data_len, width, height, bpc, resolver
            )
            extra["sep_name"] = str(deref(cs_obj[1]))
            extra["alt_name"] = alt_name
            extra["alt_comps"] = alt_comps
            return "Separation", 1, extra

        if type_clean == "DeviceN":
            names = deref(cs_obj[1])
            num_comps = len(names) if isinstance(names, (list, PDFArray)) else 4
            return "DeviceN", num_comps, {}

        if type_clean in ("CalRGB", "Lab"):
            return type_clean, 3, {}

        if type_clean == "CalGray":
            return "CalGray", 1, {}

        if type_clean == "ICCBased":
            icc_stream = deref(cs_obj[1])
            n_comps = 3
            if isinstance(icc_stream, PDFStream):
                n_comps = int(deref(icc_stream.dict.get("N", 3)))
            return "ICCBased", n_comps, {}

    return "DeviceRGB", 3, {}


def _unpack_samples(
    data: bytes,
    width: int,
    height: int,
    num_components: int,
    bpc: int,
) -> list[list[int]]:
    """Unpack raw byte payload into scanline rows of raw integer samples.

    Correctly enforces row-stride byte alignment (ISO 32000-1 Section 8.9.5.1).
    """
    bits_per_pixel = num_components * bpc
    bits_per_row = width * bits_per_pixel
    bytes_per_row = (bits_per_row + 7) // 8
    total_samples_per_row = width * num_components

    # Defensive zero-padding if data was truncated
    expected_len = height * bytes_per_row
    if len(data) < expected_len:
        data = data + b"\x00" * (expected_len - len(data))

    rows: list[list[int]] = []

    if bpc == 8:
        for y in range(height):
            row_start = y * bytes_per_row
            row_bytes = data[row_start : row_start + total_samples_per_row]
            rows.append(list(row_bytes))
    elif bpc == 1:
        for y in range(height):
            row_start = y * bytes_per_row
            row_data = data[row_start : row_start + bytes_per_row]
            row_samples: list[int] = [0] * total_samples_per_row
            for k in range(total_samples_per_row):
                byte_val = row_data[k >> 3]
                bit_shift = 7 - (k & 7)
                row_samples[k] = (byte_val >> bit_shift) & 1
            rows.append(row_samples)
    elif bpc == 2:
        for y in range(height):
            row_start = y * bytes_per_row
            row_data = data[row_start : row_start + bytes_per_row]
            row_samples = [0] * total_samples_per_row
            for k in range(total_samples_per_row):
                byte_val = row_data[k >> 2]
                bit_shift = (3 - (k & 3)) * 2
                row_samples[k] = (byte_val >> bit_shift) & 3
            rows.append(row_samples)
    elif bpc == 4:
        for y in range(height):
            row_start = y * bytes_per_row
            row_data = data[row_start : row_start + bytes_per_row]
            row_samples = [0] * total_samples_per_row
            for k in range(total_samples_per_row):
                byte_val = row_data[k >> 1]
                bit_shift = 4 if (k & 1) == 0 else 0
                row_samples[k] = (byte_val >> bit_shift) & 0x0F
            rows.append(row_samples)
    elif bpc == 16:
        for y in range(height):
            row_start = y * bytes_per_row
            row_data = data[row_start : row_start + total_samples_per_row * 2]
            row_samples = [0] * total_samples_per_row
            for k in range(total_samples_per_row):
                row_samples[k] = (row_data[2 * k] << 8) | row_data[2 * k + 1]
            rows.append(row_samples)

    return rows


def _samples_to_rgba(
    raw_rows: list[list[int]],
    width: int,
    height: int,
    color_space_name: str,
    num_components: int,
    bpc: int,
    decode_list: Optional[list[float]],
    cs_extra: dict[str, Any],
    is_mask: bool,
) -> Tuple[bytearray, bool]:
    """Convert unpacked raw sample values into 8-bit RGBA pixel buffer."""
    num_pixels = width * height
    rgba = bytearray(num_pixels * 4)
    max_val = (1 << bpc) - 1
    has_alpha = False

    # Precompute decode mapping ranges
    has_decode = decode_list is not None and len(decode_list) >= 2 * num_components
    decode_ranges: list[Tuple[float, float]] = []
    if has_decode and decode_list is not None:
        for c in range(num_components):
            decode_ranges.append((decode_list[2 * c], decode_list[2 * c + 1]))

    out_idx = 0

    if is_mask:
        # 1-bit stencil mask
        # Default Decode: [0, 1] -> 0 is transparent (not painted), 1 is painted (black)
        # If Decode: [1, 0] -> 1 is transparent, 0 is painted
        inv = has_decode and decode_ranges[0][0] > decode_ranges[0][1]
        for row in raw_rows:
            for sample in row:
                painted = (sample == 0) if inv else (sample == 1)
                if painted:
                    rgba[out_idx : out_idx + 4] = b"\x00\x00\x00\xFF"
                else:
                    rgba[out_idx : out_idx + 4] = b"\x00\x00\x00\x00"
                    has_alpha = True
                out_idx += 4
        return rgba, has_alpha

    if color_space_name in ("DeviceGray", "CalGray"):
        for row in raw_rows:
            for raw_val in row:
                if has_decode:
                    dmin, dmax = decode_ranges[0]
                    v = dmin + (raw_val / max_val) * (dmax - dmin)
                    g = min(255, max(0, round(v * 255.0)))
                elif bpc == 8:
                    g = raw_val
                elif bpc == 1:
                    g = 255 if raw_val == 1 else 0
                elif bpc == 2:
                    g = raw_val * 85
                elif bpc == 4:
                    g = raw_val * 17
                elif bpc == 16:
                    g = raw_val >> 8
                else:
                    g = min(255, max(0, round((raw_val / max_val) * 255.0)))

                rgba[out_idx] = g
                rgba[out_idx + 1] = g
                rgba[out_idx + 2] = g
                rgba[out_idx + 3] = 255
                out_idx += 4

    elif color_space_name in ("DeviceRGB", "CalRGB", "ICCBased") and num_components == 3:
        for row in raw_rows:
            row_len = len(row)
            for i in range(0, row_len, 3):
                r_raw = row[i]
                g_raw = row[i + 1]
                b_raw = row[i + 2]

                if has_decode:
                    r = min(255, max(0, round((decode_ranges[0][0] + (r_raw / max_val) * (decode_ranges[0][1] - decode_ranges[0][0])) * 255.0)))
                    g = min(255, max(0, round((decode_ranges[1][0] + (g_raw / max_val) * (decode_ranges[1][1] - decode_ranges[1][0])) * 255.0)))
                    b = min(255, max(0, round((decode_ranges[2][0] + (b_raw / max_val) * (decode_ranges[2][1] - decode_ranges[2][0])) * 255.0)))
                elif bpc == 8:
                    r = r_raw
                    g = g_raw
                    b = b_raw
                elif bpc == 16:
                    r = r_raw >> 8
                    g = g_raw >> 8
                    b = b_raw >> 8
                else:
                    r = min(255, max(0, round((r_raw / max_val) * 255.0)))
                    g = min(255, max(0, round((g_raw / max_val) * 255.0)))
                    b = min(255, max(0, round((b_raw / max_val) * 255.0)))

                rgba[out_idx] = r
                rgba[out_idx + 1] = g
                rgba[out_idx + 2] = b
                rgba[out_idx + 3] = 255
                out_idx += 4

    elif color_space_name == "DeviceCMYK" or (color_space_name == "ICCBased" and num_components == 4):
        # CMYK to RGB subtractive equations:
        # R = 255 * (1 - C) * (1 - K)
        # G = 255 * (1 - M) * (1 - K)
        # B = 255 * (1 - Y) * (1 - K)
        for row in raw_rows:
            row_len = len(row)
            for i in range(0, row_len, 4):
                c_raw = row[i]
                m_raw = row[i + 1]
                y_raw = row[i + 2]
                k_raw = row[i + 3]

                if has_decode:
                    c_f = decode_ranges[0][0] + (c_raw / max_val) * (decode_ranges[0][1] - decode_ranges[0][0])
                    m_f = decode_ranges[1][0] + (m_raw / max_val) * (decode_ranges[1][1] - decode_ranges[1][0])
                    y_f = decode_ranges[2][0] + (y_raw / max_val) * (decode_ranges[2][1] - decode_ranges[2][0])
                    k_f = decode_ranges[3][0] + (k_raw / max_val) * (decode_ranges[3][1] - decode_ranges[3][0])
                else:
                    c_f = c_raw / max_val
                    m_f = m_raw / max_val
                    y_f = y_raw / max_val
                    k_f = k_raw / max_val

                c_clamped = min(1.0, max(0.0, c_f))
                m_clamped = min(1.0, max(0.0, m_f))
                y_clamped = min(1.0, max(0.0, y_f))
                k_clamped = min(1.0, max(0.0, k_f))

                r = min(255, max(0, round(255.0 * (1.0 - c_clamped) * (1.0 - k_clamped))))
                g = min(255, max(0, round(255.0 * (1.0 - m_clamped) * (1.0 - k_clamped))))
                b = min(255, max(0, round(255.0 * (1.0 - y_clamped) * (1.0 - k_clamped))))

                rgba[out_idx] = r
                rgba[out_idx + 1] = g
                rgba[out_idx + 2] = b
                rgba[out_idx + 3] = 255
                out_idx += 4

    elif color_space_name == "Indexed":
        base_name = cs_extra.get("base_name", "DeviceRGB")
        base_comps = cs_extra.get("base_comps", 3)
        hival = cs_extra.get("hival", 255)
        lookup = cs_extra.get("lookup", b"")
        max_index = min(hival, (len(lookup) // base_comps) - 1) if base_comps > 0 else 0

        for row in raw_rows:
            for raw_val in row:
                if has_decode:
                    dmin, dmax = decode_ranges[0]
                    v = dmin + (raw_val / max_val) * (dmax - dmin)
                    idx = min(max_index, max(0, round(v)))
                else:
                    idx = min(max_index, max(0, raw_val))

                entry_pos = idx * base_comps
                if base_comps == 3:  # RGB
                    rgba[out_idx] = lookup[entry_pos]
                    rgba[out_idx + 1] = lookup[entry_pos + 1]
                    rgba[out_idx + 2] = lookup[entry_pos + 2]
                elif base_comps == 1:  # Gray
                    g_val = lookup[entry_pos]
                    rgba[out_idx] = g_val
                    rgba[out_idx + 1] = g_val
                    rgba[out_idx + 2] = g_val
                elif base_comps == 4:  # CMYK
                    c_f = lookup[entry_pos] / 255.0
                    m_f = lookup[entry_pos + 1] / 255.0
                    y_f = lookup[entry_pos + 2] / 255.0
                    k_f = lookup[entry_pos + 3] / 255.0
                    rgba[out_idx] = min(255, max(0, round(255.0 * (1.0 - c_f) * (1.0 - k_f))))
                    rgba[out_idx + 1] = min(255, max(0, round(255.0 * (1.0 - m_f) * (1.0 - k_f))))
                    rgba[out_idx + 2] = min(255, max(0, round(255.0 * (1.0 - y_f) * (1.0 - k_f))))
                else:
                    rgba[out_idx] = 0
                    rgba[out_idx + 1] = 0
                    rgba[out_idx + 2] = 0

                rgba[out_idx + 3] = 255
                out_idx += 4

    elif color_space_name == "Separation":
        # Spot tint / alternate mapping
        sep_name = cs_extra.get("sep_name", "")
        if sep_name in ("None", "/None"):
            for _ in range(num_pixels):
                rgba[out_idx : out_idx + 4] = b"\xFF\xFF\xFF\x00"
                out_idx += 4
            has_alpha = True
        else:
            for row in raw_rows:
                for raw_val in row:
                    tint = raw_val / max_val
                    g = min(255, max(0, round(255.0 * (1.0 - tint))))
                    rgba[out_idx] = g
                    rgba[out_idx + 1] = g
                    rgba[out_idx + 2] = g
                    rgba[out_idx + 3] = 255
                    out_idx += 4
    else:
        # Fallback default: copy whatever components exist into RGB
        for row in raw_rows:
            row_len = len(row)
            step = max(1, num_components)
            for i in range(0, row_len, step):
                c0 = min(255, max(0, round((row[i] / max_val) * 255.0)))
                c1 = min(255, max(0, round((row[i + 1] / max_val) * 255.0))) if i + 1 < row_len else c0
                c2 = min(255, max(0, round((row[i + 2] / max_val) * 255.0))) if i + 2 < row_len else c0
                rgba[out_idx] = c0
                rgba[out_idx + 1] = c1
                rgba[out_idx + 2] = c2
                rgba[out_idx + 3] = 255
                out_idx += 4

    return rgba, has_alpha


def _blend_smask(
    rgba_buffer: bytearray,
    width: int,
    height: int,
    smask_img: PDFImage,
) -> None:
    """Blend Soft Mask (/SMask) 8-bit alpha channel into main image RGBA buffer."""
    mask_w = smask_img.width
    mask_h = smask_img.height
    mask_pixels = smask_img.rgba_pixels

    if mask_w == width and mask_h == height:
        for p in range(width * height):
            # Mask is grayscale, R channel contains the alpha sample
            alpha = mask_pixels[p * 4]
            rgba_buffer[p * 4 + 3] = alpha
    else:
        # Resample nearest-neighbor
        for y in range(height):
            sy = min(mask_h - 1, (y * mask_h) // height)
            for x in range(width):
                sx = min(mask_w - 1, (x * mask_w) // width)
                alpha = mask_pixels[(sy * mask_w + sx) * 4]
                rgba_buffer[(y * width + x) * 4 + 3] = alpha


def _blend_explicit_mask(
    rgba_buffer: bytearray,
    width: int,
    height: int,
    mask_img: PDFImage,
) -> None:
    """Blend explicit 1-bit /Mask stream transparency into main image RGBA buffer."""
    mask_w = mask_img.width
    mask_h = mask_img.height
    mask_pixels = mask_img.rgba_pixels

    for y in range(height):
        sy = min(mask_h - 1, (y * mask_h) // height)
        for x in range(width):
            sx = min(mask_w - 1, (x * mask_w) // width)
            # In PDF explicit mask (ISO 32000-1 §8.9.6.2):
            # A sample value of 1 indicates that the corresponding area of the image
            # shall be painted (opaque); a value of 0 indicates that the area shall
            # not be painted (transparent).
            offset = (sy * mask_w + sx) * 4
            if mask_img.color_space_name == "ImageMask":
                mask_val = mask_pixels[offset + 3]  # Alpha channel
            else:
                mask_val = mask_pixels[offset]      # Gray channel

            if mask_val < 128:
                rgba_buffer[(y * width + x) * 4 + 3] = 0


def _blend_color_key_mask(
    rgba_buffer: bytearray,
    raw_rows: list[list[int]],
    width: int,
    height: int,
    num_components: int,
    mask_ranges: list[int],
) -> None:
    """Apply color key masking based on raw component range bounds."""
    if len(mask_ranges) < 2 * num_components:
        return

    pix_idx = 0
    for row in raw_rows:
        row_len = len(row)
        for i in range(0, row_len, num_components):
            is_transparent = True
            for c in range(num_components):
                min_val = mask_ranges[2 * c]
                max_val = mask_ranges[2 * c + 1]
                val = row[i + c]
                if not (min_val <= val <= max_val):
                    is_transparent = False
                    break
            if is_transparent:
                rgba_buffer[pix_idx * 4 + 3] = 0
            pix_idx += 1


__all__ = [
    "PDFImage",
]
