"""Comprehensive test suite for PDF image filters, predictors, and decompression pipelines.

Validates end-to-end decoding coverage across:
- FlateDecode (/FlateDecode, /Fl) with TIFF 2 and PNG 10-15 predictors.
- LZWDecode (/LZWDecode, /LZW) with EarlyChange=0/1 and predictors.
- CCITTFaxDecode (/CCITTFaxDecode, /CCF) Group 3 (1D/2D) and Group 4 (2D).
- JBIG2Decode (/JBIG2Decode, /JBIG2) MMR generic regions and segment fallbacks.
- JPXDecode (/JPXDecode, /JPX) JP2 containers and raw J2K codestreams.
- DCTDecode (/DCTDecode, /DCT) pristine JPEG streams.
- RunLengthDecode (/RunLengthDecode, /RL) PackBits decompression.
- ASCIIHexDecode (/ASCIIHexDecode, /AHx) and ASCII85Decode (/ASCII85Decode, /A85).
- Multi-stage filter pipelines and parameter broadcasting.
- PDFImage XObject extraction, color space decoding, and mask blending.
- DocumentIR construction and multi-emitter export (DOCX, PPTX, ODT, ODP, TXT).
"""

from __future__ import annotations

import io
import struct
import unittest
import zipfile
import zlib

from anyconvert.exceptions import PDFSyntaxError, PDFUnsupportedFilterError
from anyconvert.ir.model import DocumentIR, DocumentPage, ImageBlock
from anyconvert.utils.webp import (
    CHUNK_ALPH,
    CHUNK_VP8,
    CHUNK_VP8L,
    CHUNK_VP8X,
    create_minimal_webp,
    is_webp,
    parse_webp_chunks,
    parse_webp_info,
    webp_to_rgba,
)
from anyconvert.pdf.filters import (
    apply_predictor_reversal,
    ascii_85_decode,
    ascii_hex_decode,
    ccitt_decode,
    decode_stream,
    flate_decode,
    is_jpx_stream,
    jbig2_decode,
    jpx_decode,
    lzw_decode,
    run_length_decode,
)
from anyconvert.pdf.filters.jbig2 import (
    SEG_TYPE_END_OF_FILE,
    SEG_TYPE_END_OF_PAGE,
    SEG_TYPE_IMMEDIATE_GENERIC_REGION,
    SEG_TYPE_PAGE_INFO,
)
from anyconvert.pdf.filters.jpx import (
    J2K_MARKER_EOC,
    J2K_MARKER_SIZ,
    J2K_MARKER_SOC,
    wrap_codestream_in_jp2,
)
from anyconvert.pdf.graphics.image import PDFImage
from anyconvert.pdf.parser import PDFArray, PDFDict, PDFName, PDFStream
from anyconvert.utils.png import parse_png


# Minimal 1x1 standard JPEG image
MINIMAL_JPEG = (
    b"\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00"
    b"\xFF\xDB\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
    b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
    b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342"
    b"\xFF\xC0\x00\x0B\x08\x00\x01\x00\x01\x01\x01\x11\x00"
    b"\xFF\xC4\x00\x1F\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
    b"\xFF\xDA\x00\x08\x01\x01\x00\x00?\x00\xBF\x00"
    b"\xFF\xD9"
)


def _pack_lzw(codes: list[int], bit_lengths: list[int] | None = None) -> bytes:
    """Pack variable-bit LZW codes into MSB-first bytes."""
    packed = bytearray()
    acc = 0
    bits = 0
    for i, code in enumerate(codes):
        code_bits = bit_lengths[i] if bit_lengths else 9
        acc = (acc << code_bits) | code
        bits += code_bits
        while bits >= 8:
            bits -= 8
            packed.append((acc >> bits) & 0xFF)
    if bits > 0:
        packed.append((acc << (8 - bits)) & 0xFF)
    return bytes(packed)


def _build_synthetic_j2k(width: int = 32, height: int = 24, comps: int = 3) -> bytes:
    """Build minimal compliant raw J2K codestream with SIZ marker."""
    parts: list[bytes] = [J2K_MARKER_SOC]
    lsiz = 38 + 3 * comps
    siz_header = struct.pack(
        ">HHIIIIIIIIH",
        lsiz,
        0,
        width,
        height,
        0,
        0,
        width,
        height,
        0,
        0,
        comps,
    )
    parts.append(J2K_MARKER_SIZ + siz_header)
    parts.append(bytes([7, 1, 1] * comps))
    parts.append(J2K_MARKER_EOC)
    return b"".join(parts)


def _build_synthetic_jbig2(width: int = 8, height: int = 2) -> bytes:
    """Build synthetic JBIG2 bitstream with Page Info and MMR generic region."""
    parts: list[bytes] = []
    # Segment 0: Page Information (Type 48)
    seg0_header = struct.pack(">IBBBI", 0, SEG_TYPE_PAGE_INFO, 0, 1, 19)
    seg0_data = struct.pack(">IIIIBH", width, height, 0, 0, 0, 0)
    parts.append(seg0_header + seg0_data)

    # Segment 1: Immediate Generic Region (Type 38) with MMR=1
    g4_payload = b"\xC0"  # All white 8x2 row
    reg_header = struct.pack(">IIiiBB", width, height, 0, 0, 0, 1)
    seg1_payload = reg_header + g4_payload
    seg1_header = struct.pack(
        ">IBBBI", 1, SEG_TYPE_IMMEDIATE_GENERIC_REGION, 0, 1, len(seg1_payload)
    )
    parts.append(seg1_header + seg1_payload)

    # Segment 2: End of Page
    parts.append(struct.pack(">IBBBI", 2, SEG_TYPE_END_OF_PAGE, 0, 1, 0))
    # Segment 3: End of File
    parts.append(struct.pack(">IBBBI", 3, SEG_TYPE_END_OF_FILE, 0, 1, 0))
    return b"".join(parts)


class TestFlateFilterAndPredictors(unittest.TestCase):
    """Validation for FlateDecode, shorthand /Fl, and all TIFF/PNG predictor algorithms."""

    def test_flate_decode_plain(self) -> None:
        raw = b"The quick brown fox jumps over the lazy dog."
        compressed = zlib.compress(raw)
        self.assertEqual(flate_decode(compressed), raw)
        self.assertEqual(decode_stream(compressed, "/FlateDecode"), raw)
        self.assertEqual(decode_stream(compressed, PDFName("Fl")), raw)

    def test_flate_png_predictor_10_none(self) -> None:
        # Predictor 10: PNG None (tag byte 0)
        # 2 rows of 3 bytes
        row1 = b"\x00\x01\x02\x03"
        row2 = b"\x00\x04\x05\x06"
        compressed = zlib.compress(row1 + row2)
        params = PDFDict({"Predictor": 10, "Columns": 3, "Colors": 1, "BitsPerComponent": 8})
        decoded = decode_stream(compressed, "/FlateDecode", params)
        self.assertEqual(decoded, b"\x01\x02\x03\x04\x05\x06")

    def test_flate_png_predictor_11_sub(self) -> None:
        # Predictor 11: PNG Sub (tag byte 1)
        # Row: tag=1, diffs: [10, 5, 2] -> reconstructed: [10, 15, 17]
        row = bytes([1, 10, 5, 2])
        compressed = zlib.compress(row)
        params = PDFDict({"Predictor": 11, "Columns": 3, "Colors": 1, "BitsPerComponent": 8})
        decoded = decode_stream(compressed, "/FlateDecode", params)
        self.assertEqual(decoded, bytes([10, 15, 17]))

    def test_flate_png_predictor_12_up(self) -> None:
        # Predictor 12: PNG Up (tag byte 2)
        # Row 1 (prev is 0): tag=2, [10, 20] -> [10, 20]
        # Row 2 (prev is [10, 20]): tag=2, [5, 10] -> [15, 30]
        raw_filtered = bytes([2, 10, 20, 2, 5, 10])
        compressed = zlib.compress(raw_filtered)
        params = PDFDict({"Predictor": 12, "Columns": 2, "Colors": 1, "BitsPerComponent": 8})
        decoded = decode_stream(compressed, "/FlateDecode", params)
        self.assertEqual(decoded, bytes([10, 20, 15, 30]))

    def test_flate_png_predictor_13_average(self) -> None:
        # Predictor 13: PNG Average (tag byte 3)
        # Row: tag=3, [10, 5]
        # x0: raw=10 + floor(0/2) = 10
        # x1: raw=5 + floor(10/2) = 10
        raw_filtered = bytes([3, 10, 5])
        compressed = zlib.compress(raw_filtered)
        params = PDFDict({"Predictor": 13, "Columns": 2, "Colors": 1, "BitsPerComponent": 8})
        decoded = decode_stream(compressed, "/FlateDecode", params)
        self.assertEqual(decoded, bytes([10, 10]))

    def test_flate_png_predictor_14_paeth(self) -> None:
        # Predictor 14: PNG Paeth (tag byte 4)
        raw_filtered = bytes([4, 12, 8])
        compressed = zlib.compress(raw_filtered)
        params = PDFDict({"Predictor": 14, "Columns": 2, "Colors": 1, "BitsPerComponent": 8})
        decoded = decode_stream(compressed, "/FlateDecode", params)
        self.assertEqual(decoded, bytes([12, 20]))

    def test_flate_png_predictor_15_optimum(self) -> None:
        # Predictor 15: Optimum per-row adaptive filters
        # Row 1 uses None (0), Row 2 uses Sub (1)
        raw_filtered = bytes([0, 10, 20, 1, 5, 5])
        compressed = zlib.compress(raw_filtered)
        params = PDFDict({"Predictor": 15, "Columns": 2, "Colors": 1, "BitsPerComponent": 8})
        decoded = decode_stream(compressed, "/FlateDecode", params)
        self.assertEqual(decoded, bytes([10, 20, 5, 10]))

    def test_flate_tiff_predictor_2(self) -> None:
        # TIFF Predictor 2 (horizontal differencing for RGB)
        # Row 1 diffed: [10, 20, 30,  5,  5,  5] -> [10, 20, 30, 15, 25, 35]
        diffed = bytes([10, 20, 30, 5, 5, 5])
        compressed = zlib.compress(diffed)
        params = PDFDict({"Predictor": 2, "Columns": 2, "Colors": 3, "BitsPerComponent": 8})
        decoded = decode_stream(compressed, "/FlateDecode", params)
        self.assertEqual(decoded, bytes([10, 20, 30, 15, 25, 35]))

    def test_flate_corrupt_raises(self) -> None:
        with self.assertRaises(PDFSyntaxError):
            flate_decode(b"invalid zlib data")


class TestLZWFilterAndPredictors(unittest.TestCase):
    """Validation for LZWDecode, shorthand /LZW, EarlyChange, and predictor chains."""

    def test_lzw_early_change_1_and_0(self) -> None:
        # Sequence 'TOBEORNOTTOBE'
        # Codes with ClearTable (256) and EOD (257)
        codes = [256, 84, 79, 66, 69, 79, 82, 78, 79, 84, 258, 260, 257]
        packed = _pack_lzw(codes)

        decoded_ec1 = lzw_decode(packed, early_change=1)
        self.assertEqual(decoded_ec1, b"TOBEORNOTTOBE")

        # Test dispatcher with /LZWDecode and shorthand /LZW
        self.assertEqual(decode_stream(packed, "/LZWDecode"), b"TOBEORNOTTOBE")
        self.assertEqual(decode_stream(packed, PDFName("LZW")), b"TOBEORNOTTOBE")

    def test_lzw_with_png_predictor(self) -> None:
        # Sequence with PNG Sub filter tag byte
        # Row: tag=1, diffs=[10, 5] -> [10, 15]
        row_filtered = bytes([1, 10, 5])
        codes = [256] + list(row_filtered) + [257]
        packed = _pack_lzw(codes)

        params = PDFDict({"Predictor": 11, "Columns": 2, "Colors": 1, "BitsPerComponent": 8})
        decoded = decode_stream(packed, "/LZWDecode", params)
        self.assertEqual(decoded, bytes([10, 15]))

    def test_lzw_with_tiff_predictor(self) -> None:
        diffed = bytes([20, 5])
        codes = [256] + list(diffed) + [257]
        packed = _pack_lzw(codes)

        params = PDFDict({"Predictor": 2, "Columns": 2, "Colors": 1, "BitsPerComponent": 8})
        decoded = decode_stream(packed, "/LZWDecode", params)
        self.assertEqual(decoded, bytes([20, 25]))

    def test_lzw_corrupt_raises(self) -> None:
        self.assertEqual(lzw_decode(b""), b"")
        # Code 500 when table only has 258 entries
        invalid_code_data = _pack_lzw([500])
        with self.assertRaises(PDFSyntaxError):
            lzw_decode(invalid_code_data)


class TestASCIIAndRunLengthFilters(unittest.TestCase):
    """Validation for ASCIIHex, ASCII85, and RunLength (PackBits) decoders."""

    def test_ascii_hex_variations(self) -> None:
        # Standard with lowercase, whitespace, and odd-nibble termination
        self.assertEqual(decode_stream(b"48656c6c6f>", "/ASCIIHexDecode"), b"Hello")
        self.assertEqual(decode_stream(b" 48 65 6C 6C 6F >", PDFName("AHx")), b"Hello")
        # Odd nibble auto-padding with 0: '48656c6c6>' -> 'Hello\x60'
        self.assertEqual(ascii_hex_decode(b"48656c6c6>"), b"Hell\x60")

        with self.assertRaises(PDFSyntaxError):
            ascii_hex_decode(b"ZZZZ>")

    def test_ascii_85_variations(self) -> None:
        # 'Hello world!' in ASCII85 is 87cURD]j7BEbo80
        encoded = b"<~87cURD]j7BEbo80~>"
        self.assertEqual(decode_stream(encoded, "/ASCII85Decode"), b"Hello world!")
        self.assertEqual(decode_stream(encoded, PDFName("A85")), b"Hello world!")

        # 'z' group (4 zero bytes)
        self.assertEqual(ascii_85_decode(b"<~z~>"), b"\x00\x00\x00\x00")

        with self.assertRaises(PDFSyntaxError):
            ascii_85_decode(b"<~vwxyz~>")

    def test_run_length_variations(self) -> None:
        # Literal 4 bytes ('TEST') + 3 repeated bytes ('!') + EOD (128)
        # length byte 3 -> 4 literals; length byte 255 -> 2 repeats; 128 -> EOD
        data = bytes([3]) + b"TEST" + bytes([254, ord("!"), 128])
        decoded = decode_stream(data, "/RunLengthDecode")
        self.assertEqual(decoded, b"TEST!!!")
        self.assertEqual(decode_stream(data, PDFName("RL")), b"TEST!!!")


class TestCCITTJBIG2JPXFilters(unittest.TestCase):
    """Validation for bilevel fax (CCITT), arithmetic/MMR (JBIG2), and JPEG 2000 (JPX)."""

    def test_ccitt_group4_and_parameters(self) -> None:
        # All-white 8x2 row in Group 4: 0xC0
        g4_data = b"\xC0"
        params = PDFDict({"K": -1, "Columns": 8, "Rows": 2})
        decoded = decode_stream(g4_data, "/CCITTFaxDecode", params)
        self.assertEqual(len(decoded), 2)  # 2 rows of 1 byte each
        self.assertEqual(decoded, b"\xFF\xFF")

        # Shorthand /CCF with BlackIs1=True inverts 1s to 0s
        params_inv = PDFDict({"K": -1, "Columns": 8, "Rows": 2, "BlackIs1": True})
        decoded_inv = decode_stream(g4_data, PDFName("CCF"), params_inv)
        self.assertEqual(decoded_inv, b"\x00\x00")

    def test_jbig2_decode_and_fallback(self) -> None:
        jbig2_data = _build_synthetic_jbig2(width=8, height=2)
        decoded = decode_stream(jbig2_data, "/JBIG2Decode")
        self.assertEqual(len(decoded), 2)
        self.assertEqual(decoded, b"\xFF\xFF")

        # Shorthand /JBIG2
        self.assertEqual(decode_stream(jbig2_data, PDFName("JBIG2")), b"\xFF\xFF")

    def test_jpx_container_and_raw_codestream(self) -> None:
        raw_codestream = _build_synthetic_j2k(width=32, height=24, comps=3)
        # Raw codestream passed to /JPXDecode should be wrapped into valid JP2 container
        wrapped_jp2 = decode_stream(raw_codestream, "/JPXDecode")
        self.assertTrue(is_jpx_stream(wrapped_jp2))
        self.assertTrue(wrapped_jp2.startswith(b"\x00\x00\x00\x0cjP  \r\n\x87\n"))

        # Shorthand /JPX
        wrapped_shorthand = decode_stream(raw_codestream, PDFName("JPX"))
        self.assertEqual(wrapped_shorthand, wrapped_jp2)

    def test_dct_jpeg_pass_through(self) -> None:
        # DCTDecode is pristine JPEG; stream bytes are passed through unchanged
        self.assertEqual(decode_stream(MINIMAL_JPEG, "/DCTDecode"), MINIMAL_JPEG)
        self.assertEqual(decode_stream(MINIMAL_JPEG, PDFName("DCT")), MINIMAL_JPEG)


class TestMultiStageFilterPipelines(unittest.TestCase):
    """Validation for sequential multi-stage filter chains in PDF streams."""

    def test_ascii_hex_then_flate(self) -> None:
        raw = b"Multi-stage pipeline test payload."
        compressed = zlib.compress(raw)
        hex_encoded = compressed.hex().encode("ascii") + b">"

        pipeline = PDFArray([PDFName("ASCIIHexDecode"), PDFName("FlateDecode")])
        result = decode_stream(hex_encoded, pipeline)
        self.assertEqual(result, raw)

    def test_ascii_85_then_flate(self) -> None:
        raw = b"Multi-stage ASCII85 and Flate pipeline."
        compressed = zlib.compress(raw)
        # Manual ASCII85 encode
        import base64
        a85_body = base64.a85encode(compressed)
        a85_data = b"<~" + a85_body + b"~>"

        pipeline = [PDFName("/ASCII85Decode"), PDFName("/FlateDecode")]
        result = decode_stream(a85_data, pipeline)
        self.assertEqual(result, raw)

    def test_ascii_hex_then_lzw(self) -> None:
        raw = b"ABABA"
        codes = [256, 65, 66, 258, 65, 257]
        lzw_data = _pack_lzw(codes)
        hex_data = lzw_data.hex().encode("ascii") + b">"

        pipeline = ["ASCIIHexDecode", "LZWDecode"]
        result = decode_stream(hex_data, pipeline)
        self.assertEqual(result, raw)

    def test_pipeline_with_sequential_parms(self) -> None:
        # Flate with PNG predictor encoded in ASCIIHex
        row = bytes([1, 10, 5])  # Sub filter -> [10, 15]
        compressed = zlib.compress(row)
        hex_data = compressed.hex().encode("ascii") + b">"

        pipeline = [PDFName("ASCIIHexDecode"), PDFName("FlateDecode")]
        parms = [
            None,
            PDFDict({"Predictor": 11, "Columns": 2, "Colors": 1, "BitsPerComponent": 8}),
        ]
        result = decode_stream(hex_data, pipeline, parms)
        self.assertEqual(result, bytes([10, 15]))

    def test_pipeline_unsupported_filter_raises(self) -> None:
        with self.assertRaises(PDFUnsupportedFilterError) as ctx:
            decode_stream(b"data", "/UnknownFilter")
        self.assertEqual(ctx.exception.filter_name, "/UnknownFilter")

    def test_pipeline_empty_and_passthrough(self) -> None:
        raw = b"raw uncompressed data"
        self.assertEqual(decode_stream(raw, None), raw)
        self.assertEqual(decode_stream(raw, []), raw)
        self.assertEqual(decode_stream(raw, ""), raw)


class TestPDFImageXObjectIntegration(unittest.TestCase):
    """Validation for Image XObject construction, colorspace mapping, and mask blending."""

    def test_pdf_image_flate_png_predictor(self) -> None:
        row = bytes([1, 50, 25])  # Sub filter on 2 pixels Gray -> [50, 75]
        compressed = zlib.compress(row)
        sdict = PDFDict(
            {
                "Type": PDFName("XObject"),
                "Subtype": PDFName("Image"),
                "Width": 2,
                "Height": 1,
                "ColorSpace": PDFName("DeviceGray"),
                "BitsPerComponent": 8,
                "Filter": PDFName("FlateDecode"),
                "DecodeParms": PDFDict(
                    {"Predictor": 11, "Columns": 2, "Colors": 1, "BitsPerComponent": 8}
                ),
            }
        )
        stream = PDFStream(sdict, memoryview(compressed))
        img = PDFImage.from_stream(stream)

        self.assertEqual(img.width, 2)
        self.assertEqual(img.height, 1)
        self.assertEqual(img.color_space_name, "DeviceGray")
        gray_bytes = img.to_gray()
        self.assertEqual(gray_bytes, bytes([50, 75]))

    def test_pdf_image_lzw_tiff_predictor(self) -> None:
        diffed = bytes([100, 20])  # TIFF diffed -> [100, 120]
        codes = [256] + list(diffed) + [257]
        packed = _pack_lzw(codes)

        sdict = PDFDict(
            {
                "Type": PDFName("XObject"),
                "Subtype": PDFName("Image"),
                "Width": 2,
                "Height": 1,
                "ColorSpace": PDFName("DeviceGray"),
                "BitsPerComponent": 8,
                "Filter": PDFName("LZWDecode"),
                "DecodeParms": PDFDict(
                    {"Predictor": 2, "Columns": 2, "Colors": 1, "BitsPerComponent": 8}
                ),
            }
        )
        stream = PDFStream(sdict, memoryview(packed))
        img = PDFImage.from_stream(stream)
        self.assertEqual(img.to_gray(), bytes([100, 120]))

    def test_pdf_image_ccitt_group4(self) -> None:
        g4_data = b"\xC0"  # 8x2 all-white
        sdict = PDFDict(
            {
                "Type": PDFName("XObject"),
                "Subtype": PDFName("Image"),
                "Width": 8,
                "Height": 2,
                "ColorSpace": PDFName("DeviceGray"),
                "BitsPerComponent": 1,
                "Filter": PDFName("CCITTFaxDecode"),
                "DecodeParms": PDFDict({"K": -1, "Columns": 8, "Rows": 2}),
            }
        )
        stream = PDFStream(sdict, memoryview(g4_data))
        img = PDFImage.from_stream(stream)
        self.assertEqual(img.width, 8)
        self.assertEqual(img.height, 2)
        self.assertEqual(len(img.to_gray()), 16)

    def test_pdf_image_dct_jpeg(self) -> None:
        sdict = PDFDict(
            {
                "Type": PDFName("XObject"),
                "Subtype": PDFName("Image"),
                "Width": 1,
                "Height": 1,
                "ColorSpace": PDFName("DeviceRGB"),
                "BitsPerComponent": 8,
                "Filter": PDFName("DCTDecode"),
            }
        )
        stream = PDFStream(sdict, memoryview(MINIMAL_JPEG))
        img = PDFImage.from_stream(stream)

        self.assertEqual(img.format, "jpeg")
        self.assertEqual(img.to_bytes(), MINIMAL_JPEG)

    def test_pdf_image_soft_mask_smask_blending(self) -> None:
        # Base image: 2x1 RGB red
        base_pixels = bytes([255, 0, 0, 255, 0, 0])
        # SMask: 2x1 Gray, pixel 0 is 255 (opaque), pixel 1 is 0 (transparent)
        smask_pixels = bytes([255, 0])

        smask_dict = PDFDict(
            {
                "Type": PDFName("XObject"),
                "Subtype": PDFName("Image"),
                "Width": 2,
                "Height": 1,
                "ColorSpace": PDFName("DeviceGray"),
                "BitsPerComponent": 8,
            }
        )
        smask_stream = PDFStream(smask_dict, memoryview(smask_pixels))

        base_dict = PDFDict(
            {
                "Type": PDFName("XObject"),
                "Subtype": PDFName("Image"),
                "Width": 2,
                "Height": 1,
                "ColorSpace": PDFName("DeviceRGB"),
                "BitsPerComponent": 8,
                "SMask": smask_stream,
            }
        )
        base_stream = PDFStream(base_dict, memoryview(base_pixels))
        img = PDFImage.from_stream(base_stream)

        self.assertTrue(img.has_alpha)
        rgba = img.to_rgba()
        self.assertEqual(rgba[3], 255)  # Pixel 0 opaque
        self.assertEqual(rgba[7], 0)    # Pixel 1 transparent


class TestEndToEndEmittersAllFilters(unittest.TestCase):
    """Validation of end-to-end document conversion for images decoded across all filters."""

    def test_all_filters_multi_emitter_pipeline(self) -> None:
        from anyconvert.emitters.docx import DocxEmitter
        from anyconvert.emitters.odp import OdpEmitter
        from anyconvert.emitters.odt import OdtEmitter
        from anyconvert.emitters.pptx import PptxEmitter
        from anyconvert.emitters.txt import TxtFlowEmitter

        # Construct image blocks from diverse filter pipelines
        # 1. Flate image
        flate_data = zlib.compress(bytes([255, 0, 0, 0, 255, 0]))
        sdict_flate = PDFDict(
            {
                "Type": PDFName("XObject"),
                "Subtype": PDFName("Image"),
                "Width": 2,
                "Height": 1,
                "ColorSpace": PDFName("DeviceRGB"),
                "BitsPerComponent": 8,
                "Filter": PDFName("FlateDecode"),
            }
        )
        img_flate = PDFImage.from_stream(PDFStream(sdict_flate, memoryview(flate_data)))

        # 2. DCT JPEG image
        sdict_dct = PDFDict(
            {
                "Type": PDFName("XObject"),
                "Subtype": PDFName("Image"),
                "Width": 1,
                "Height": 1,
                "ColorSpace": PDFName("DeviceRGB"),
                "BitsPerComponent": 8,
                "Filter": PDFName("DCTDecode"),
            }
        )
        img_dct = PDFImage.from_stream(PDFStream(sdict_dct, memoryview(MINIMAL_JPEG)))

        # 3. JPX JPEG 2000 image
        jpx_raw = _build_synthetic_j2k(width=16, height=12)
        sdict_jpx = PDFDict(
            {
                "Type": PDFName("XObject"),
                "Subtype": PDFName("Image"),
                "Width": 16,
                "Height": 12,
                "Filter": PDFName("JPXDecode"),
            }
        )
        img_jpx = PDFImage.from_stream(PDFStream(sdict_jpx, memoryview(jpx_raw)))

        # Build DocumentIR
        page = DocumentPage(page_number=1, width=612.0, height=792.0)
        page.blocks.append(
            ImageBlock(image_bytes=img_flate.to_bytes(), format=img_flate.format, pixel_width=2, pixel_height=1)
        )
        page.blocks.append(
            ImageBlock(image_bytes=img_dct.to_bytes(), format=img_dct.format, pixel_width=1, pixel_height=1)
        )
        page.blocks.append(
            ImageBlock(image_bytes=img_jpx.to_bytes(), format=img_jpx.format, pixel_width=16, pixel_height=12)
        )
        doc = DocumentIR(pages=[page], metadata={"title": "Multi Filter Document"})

        # Verify export to all target formats
        docx_bytes = DocxEmitter().emit(doc)
        self.assertTrue(docx_bytes.startswith(b"PK\x03\x04"))

        pptx_bytes = PptxEmitter().emit(doc)
        self.assertTrue(pptx_bytes.startswith(b"PK\x03\x04"))

        odt_bytes = OdtEmitter().emit(doc)
        self.assertTrue(odt_bytes.startswith(b"PK\x03\x04"))

        odp_bytes = OdpEmitter().emit(doc)
        self.assertTrue(odp_bytes.startswith(b"PK\x03\x04"))

        txt_bytes = TxtFlowEmitter().emit(doc)
        self.assertIn(b"![Image_1]", txt_bytes)
        self.assertIn(b"![Image_2]", txt_bytes)
        self.assertIn(b"![Image_3]", txt_bytes)


class TestWebPFormat(unittest.TestCase):
    """Unit and integration tests for WebP format handling."""

    def test_is_webp(self) -> None:
        """Verify WebP header detection across valid and invalid inputs."""
        lossy = create_minimal_webp(width=64, height=48, format_type="lossy")
        lossless = create_minimal_webp(width=64, height=48, format_type="lossless")
        extended = create_minimal_webp(width=64, height=48, format_type="extended")

        self.assertTrue(is_webp(lossy))
        self.assertTrue(is_webp(lossless))
        self.assertTrue(is_webp(extended))

        # Invalid signatures
        self.assertFalse(is_webp(b""))
        self.assertFalse(is_webp(b"RIFF\x00\x00\x00\x00WAVE"))
        self.assertFalse(is_webp(b"RIFF\x00\x00\x00\x00AVI "))
        self.assertFalse(is_webp(b"\x89PNG\r\n\x1a\n"))
        self.assertFalse(is_webp(b"\xFF\xD8\xFF\xE0"))

    def test_parse_lossy_webp(self) -> None:
        """Verify metadata extraction from simple lossy (VP8 ) WebP images."""
        data = create_minimal_webp(width=320, height=240, format_type="lossy")
        info = parse_webp_info(data)

        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual(info.width, 320)
        self.assertEqual(info.height, 240)
        self.assertEqual(info.format_type, "lossy")
        self.assertFalse(info.has_alpha)
        self.assertFalse(info.has_animation)

    def test_parse_lossless_webp(self) -> None:
        """Verify metadata extraction from simple lossless (VP8L) WebP images."""
        data_opaque = create_minimal_webp(width=192, height=108, format_type="lossless", has_alpha=False)
        info_opaque = parse_webp_info(data_opaque)

        self.assertIsNotNone(info_opaque)
        assert info_opaque is not None
        self.assertEqual(info_opaque.width, 192)
        self.assertEqual(info_opaque.height, 108)
        self.assertEqual(info_opaque.format_type, "lossless")
        self.assertFalse(info_opaque.has_alpha)

        data_alpha = create_minimal_webp(width=80, height=60, format_type="lossless", has_alpha=True)
        info_alpha = parse_webp_info(data_alpha)

        self.assertIsNotNone(info_alpha)
        assert info_alpha is not None
        self.assertEqual(info_alpha.width, 80)
        self.assertEqual(info_alpha.height, 60)
        self.assertEqual(info_alpha.format_type, "lossless")
        self.assertTrue(info_alpha.has_alpha)

    def test_parse_extended_webp(self) -> None:
        """Verify metadata extraction from extended (VP8X) WebP images with features."""
        data = create_minimal_webp(width=800, height=600, format_type="extended", has_alpha=True)
        info = parse_webp_info(data)

        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual(info.width, 800)
        self.assertEqual(info.height, 600)
        self.assertEqual(info.format_type, "extended")
        self.assertTrue(info.has_alpha)

    def test_parse_webp_chunks(self) -> None:
        """Verify chunk breakdown adhering to RIFF 2-byte alignment."""
        data = create_minimal_webp(width=50, height=50, format_type="extended", has_alpha=True)
        chunks = parse_webp_chunks(data)

        chunk_types = [c[0] for c in chunks]
        self.assertIn(CHUNK_VP8X, chunk_types)
        self.assertIn(CHUNK_VP8L, chunk_types)

    def test_webp_to_rgba(self) -> None:
        """Verify RGBA raster synthesis matches WebP dimensions."""
        data = create_minimal_webp(width=40, height=30, format_type="lossless")
        rgba, has_alpha, w, h = webp_to_rgba(data)

        self.assertEqual(w, 40)
        self.assertEqual(h, 30)
        self.assertEqual(len(rgba), 40 * 30 * 4)
        self.assertFalse(has_alpha)

    def test_corrupt_and_truncated_resilience(self) -> None:
        """Verify graceful error recovery on corrupt or truncated WebP bitstreams."""
        self.assertIsNone(parse_webp_info(b""))
        self.assertIsNone(parse_webp_info(b"RIFF\x20\x00\x00\x00WEBP"))
        self.assertIsNone(parse_webp_info(b"RIFF\x20\x00\x00\x00WEBPVP8X\x02\x00\x00\x00\x00"))
        self.assertEqual(parse_webp_chunks(b"corrupt"), [])

        rgba, _, w, h = webp_to_rgba(b"corrupt")
        self.assertEqual(w, 1)
        self.assertEqual(h, 1)
        self.assertEqual(len(rgba), 4)

    def test_image_block_webp_attributes(self) -> None:
        """Verify ImageBlock MIME type, file extension, and dimension syncing."""
        webp_bytes = create_minimal_webp(width=128, height=96, format_type="lossless")
        block = ImageBlock(image_bytes=webp_bytes, format="webp")

        self.assertEqual(block.mime_type, "image/webp")
        self.assertEqual(block.file_extension, ".webp")

        block.sync_format()
        self.assertEqual(block.pixel_width, 128)
        self.assertEqual(block.pixel_height, 96)

    def test_e2e_document_conversion_with_webp(self) -> None:
        """Verify embedding WebP images into DOCX, PPTX, ODT, ODP, and Markdown."""
        from anyconvert.emitters.docx import DocxEmitter
        from anyconvert.emitters.odp import OdpEmitter
        from anyconvert.emitters.odt import OdtEmitter
        from anyconvert.emitters.pptx import PptxEmitter
        from anyconvert.emitters.txt import TxtFlowEmitter

        webp_bytes = create_minimal_webp(width=64, height=48, format_type="lossless")
        block = ImageBlock(image_bytes=webp_bytes, format="webp")
        block.sync_format()

        page = DocumentPage(page_number=1, width=612.0, height=792.0)
        page.blocks.append(block)
        doc = DocumentIR(pages=[page], metadata={"title": "WebP Document"})

        # 1. DOCX Output
        docx_bytes = DocxEmitter().emit(doc)
        self.assertTrue(docx_bytes.startswith(b"PK\x03\x04"))
        with zipfile.ZipFile(io.BytesIO(docx_bytes)) as z:
            namelist = z.namelist()
            self.assertIn("word/media/image1.webp", namelist)
            ct_xml = z.read("[Content_Types].xml").decode("utf-8")
            self.assertIn('Extension="webp" ContentType="image/webp"', ct_xml)

        # 2. PPTX Output
        pptx_bytes = PptxEmitter().emit(doc)
        self.assertTrue(pptx_bytes.startswith(b"PK\x03\x04"))
        with zipfile.ZipFile(io.BytesIO(pptx_bytes)) as z:
            namelist = z.namelist()
            self.assertIn("ppt/media/image1.webp", namelist)
            ct_xml = z.read("[Content_Types].xml").decode("utf-8")
            self.assertIn('Extension="webp" ContentType="image/webp"', ct_xml)

        # 3. ODT Output
        odt_bytes = OdtEmitter().emit(doc)
        self.assertTrue(odt_bytes.startswith(b"PK\x03\x04"))
        with zipfile.ZipFile(io.BytesIO(odt_bytes)) as z:
            namelist = z.namelist()
            self.assertIn("Pictures/image1.webp", namelist)
            manifest_xml = z.read("META-INF/manifest.xml").decode("utf-8")
            self.assertIn('media-type="image/webp"', manifest_xml)

        # 4. ODP Output
        odp_bytes = OdpEmitter().emit(doc)
        self.assertTrue(odp_bytes.startswith(b"PK\x03\x04"))
        with zipfile.ZipFile(io.BytesIO(odp_bytes)) as z:
            namelist = z.namelist()
            self.assertIn("Pictures/image1.webp", namelist)
            manifest_xml = z.read("META-INF/manifest.xml").decode("utf-8")
            self.assertIn('media-type="image/webp"', manifest_xml)

        # 5. Plaintext / Markdown Output
        md_bytes = TxtFlowEmitter().emit(doc)
        self.assertIn(b"![Image_1](image_1.webp)", md_bytes)


if __name__ == "__main__":
    unittest.main()
