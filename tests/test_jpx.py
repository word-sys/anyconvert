"""Tests for JPEG 2000 (JPX/JP2) header parser, stream wrapper, and image decoding."""

from __future__ import annotations

import struct
import unittest

from anyconvert.ir.model import DocumentIR, DocumentPage, ImageBlock
from anyconvert.pdf.filters import decode_stream, jpx_decode
from anyconvert.pdf.filters.jpx import (
    J2K_MARKER_EOC,
    J2K_MARKER_SIZ,
    J2K_MARKER_SOC,
    JP2_SIGNATURE_MAGIC,
    is_jpx_stream,
    jpx_to_rgba,
    parse_jpx_info,
    wrap_codestream_in_jp2,
)
from anyconvert.pdf.graphics.image import PDFImage
from anyconvert.pdf.parser import PDFDict, PDFName, PDFStream
from anyconvert.utils.png import parse_png


def _build_synthetic_j2k_codestream(
    width: int = 64,
    height: int = 48,
    num_components: int = 3,
    bpc: int = 8,
) -> bytes:
    """Helper to synthesize a minimal compliant J2K codestream with SIZ marker."""
    parts: list[bytes] = []

    # 1. SOC marker (FF4F)
    parts.append(J2K_MARKER_SOC)

    # 2. SIZ marker (FF51)
    # Lsiz = 38 + 3 * Csiz
    lsiz = 38 + 3 * num_components
    rsiz = 0
    xsiz = width
    ysiz = height
    xosiz = 0
    yosiz = 0
    xtsiz = width
    ytsiz = height
    xtosiz = 0
    ytosiz = 0
    csiz = num_components

    siz_header = struct.pack(
        ">HHIIIIIIIIH",
        lsiz,
        rsiz,
        xsiz,
        ysiz,
        xosiz,
        yosiz,
        xtsiz,
        ytsiz,
        xtosiz,
        ytosiz,
        csiz,
    )
    parts.append(J2K_MARKER_SIZ + siz_header)

    # Components: Ssiz, XRsiz, YRsiz
    ssiz = (bpc - 1) & 0x7F
    comp_bytes = bytearray()
    for _ in range(num_components):
        comp_bytes.extend([ssiz, 1, 1])
    parts.append(bytes(comp_bytes))

    # 3. EOC marker (FFD9)
    parts.append(J2K_MARKER_EOC)

    return b"".join(parts)


def _build_synthetic_jp2_file(
    width: int = 100,
    height: int = 80,
    num_components: int = 3,
    bpc: int = 8,
) -> bytes:
    """Helper to synthesize a minimal compliant JP2 container file."""
    codestream = _build_synthetic_j2k_codestream(
        width=width, height=height, num_components=num_components, bpc=bpc
    )
    return wrap_codestream_in_jp2(
        codestream=codestream,
        width=width,
        height=height,
        num_components=num_components,
        bpc=bpc,
    )


class TestJPXFilter(unittest.TestCase):
    """Unit and integration test cases for JPX / JPEG 2000 support."""

    def test_is_jpx_stream(self) -> None:
        """Verify stream header identification for JP2 files and J2K codestreams."""
        jp2_data = _build_synthetic_jp2_file(width=32, height=32)
        j2k_data = _build_synthetic_j2k_codestream(width=32, height=32)

        self.assertTrue(is_jpx_stream(jp2_data))
        self.assertTrue(is_jpx_stream(j2k_data))
        self.assertTrue(is_jpx_stream(b"\x00\x00\x00\x0cjP\x1a\x1a"))
        self.assertTrue(is_jpx_stream(b"\xFF\x4F\xFF\x51"))

        self.assertFalse(is_jpx_stream(b"\x89PNG\r\n\x1a\n"))
        self.assertFalse(is_jpx_stream(b"\xFF\xD8\xFF\xE0"))
        self.assertFalse(is_jpx_stream(b""))
        self.assertFalse(is_jpx_stream(b"x"))

    def test_parse_raw_codestream_siz(self) -> None:
        """Verify dimension and component parsing from raw J2K SIZ marker."""
        data = _build_synthetic_j2k_codestream(width=160, height=120, num_components=3, bpc=8)
        info = parse_jpx_info(data)

        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual(info.width, 160)
        self.assertEqual(info.height, 120)
        self.assertEqual(info.num_components, 3)
        self.assertEqual(info.bits_per_component, 8)
        self.assertEqual(info.color_space, "DeviceRGB")
        self.assertFalse(info.is_jp2_container)

    def test_parse_raw_codestream_grayscale(self) -> None:
        """Verify grayscale component handling from raw J2K SIZ marker."""
        data = _build_synthetic_j2k_codestream(width=50, height=40, num_components=1, bpc=8)
        info = parse_jpx_info(data)

        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual(info.width, 50)
        self.assertEqual(info.height, 40)
        self.assertEqual(info.num_components, 1)
        self.assertEqual(info.color_space, "DeviceGray")

    def test_parse_jp2_container(self) -> None:
        """Verify metadata extraction from standard JP2 container boxes."""
        data = _build_synthetic_jp2_file(width=200, height=150, num_components=3, bpc=8)
        info = parse_jpx_info(data)

        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual(info.width, 200)
        self.assertEqual(info.height, 150)
        self.assertEqual(info.num_components, 3)
        self.assertEqual(info.bits_per_component, 8)
        self.assertEqual(info.color_space, "DeviceRGB")
        self.assertTrue(info.is_jp2_container)

    def test_wrap_codestream_in_jp2(self) -> None:
        """Verify wrapping raw codestream into valid JP2 container."""
        codestream = _build_synthetic_j2k_codestream(width=80, height=60, num_components=3)
        jp2_container = wrap_codestream_in_jp2(codestream, width=80, height=60)

        self.assertTrue(jp2_container.startswith(JP2_SIGNATURE_MAGIC))
        info = parse_jpx_info(jp2_container)
        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual(info.width, 80)
        self.assertEqual(info.height, 60)
        self.assertTrue(info.is_jp2_container)

    def test_decode_stream_dispatcher_jpx(self) -> None:
        """Verify decode_stream dispatches /JPXDecode and normalizes raw codestream."""
        raw_codestream = _build_synthetic_j2k_codestream(width=40, height=30)
        normalized = decode_stream(raw_codestream, [PDFName("/JPXDecode")])

        self.assertTrue(normalized.startswith(JP2_SIGNATURE_MAGIC))
        info = parse_jpx_info(normalized)
        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual(info.width, 40)
        self.assertEqual(info.height, 30)

    def test_jpx_to_rgba(self) -> None:
        """Verify RGBA raster synthesis matches JPX dimensions."""
        data = _build_synthetic_jp2_file(width=16, height=8, num_components=3)
        rgba, has_alpha, w, h = jpx_to_rgba(data)

        self.assertEqual(w, 16)
        self.assertEqual(h, 8)
        self.assertEqual(len(rgba), 16 * 8 * 4)
        self.assertFalse(has_alpha)

    def test_pdf_image_xobject_integration(self) -> None:
        """Verify PDFImage constructs from a stream with /Filter /JPXDecode."""
        jp2_data = _build_synthetic_jp2_file(width=64, height=48)
        sdict = PDFDict(
            {
                "Type": PDFName("XObject"),
                "Subtype": PDFName("Image"),
                "Width": 64,
                "Height": 48,
                "ColorSpace": PDFName("DeviceRGB"),
                "BitsPerComponent": 8,
                "Filter": PDFName("JPXDecode"),
            }
        )
        stream = PDFStream(sdict, memoryview(jp2_data))
        img = PDFImage.from_stream(stream)

        self.assertEqual(img.width, 64)
        self.assertEqual(img.height, 48)
        self.assertEqual(img.format, "jp2")
        self.assertEqual(img.to_jp2(), jp2_data)

        png_bytes = img.to_png()
        self.assertTrue(png_bytes.startswith(b"\x89PNG\r\n\x1a\n"))
        png_w, png_h, bit_depth, color_type, _ = parse_png(png_bytes)
        self.assertEqual(png_w, 64)
        self.assertEqual(png_h, 48)

    def test_pdf_image_omitted_dimensions_and_colorspace(self) -> None:
        """Verify ISO 32000-1 §7.4.9: Width/Height/ColorSpace omitted from dictionary."""
        jp2_data = _build_synthetic_jp2_file(width=128, height=96, num_components=3)
        # Omit Width, Height, and ColorSpace from image dictionary
        sdict = PDFDict(
            {
                "Type": PDFName("XObject"),
                "Subtype": PDFName("Image"),
                "Filter": PDFName("JPXDecode"),
            }
        )
        stream = PDFStream(sdict, memoryview(jp2_data))
        img = PDFImage.from_stream(stream)

        self.assertEqual(img.width, 128)
        self.assertEqual(img.height, 96)
        self.assertEqual(img.color_space_name, "DeviceRGB")
        self.assertEqual(img.format, "jp2")

    def test_corrupt_and_empty_stream_resilience(self) -> None:
        """Verify robust handling on corrupt, truncated, or empty bitstreams."""
        self.assertEqual(jpx_decode(b""), b"")
        self.assertIsNone(parse_jpx_info(b""))
        self.assertIsNone(parse_jpx_info(b"\xFF\x4F"))
        self.assertIsNone(parse_jpx_info(b"\x00\x00\x00\x0cjP  corrupt"))

        # jpx_to_rgba on corrupt data should still return a safe 1x1 buffer
        rgba, _, w, h = jpx_to_rgba(b"corrupt")
        self.assertEqual(w, 1)
        self.assertEqual(h, 1)
        self.assertEqual(len(rgba), 4)

    def test_e2e_document_conversion_with_jpx(self) -> None:
        """Verify end-to-end document conversion containing JPX images across emitters."""
        from anyconvert.emitters.docx import DocxEmitter
        from anyconvert.emitters.odp import OdpEmitter
        from anyconvert.emitters.odt import OdtEmitter
        from anyconvert.emitters.pptx import PptxEmitter
        from anyconvert.emitters.txt import TxtFlowEmitter

        jp2_data = _build_synthetic_jp2_file(width=32, height=24)
        sdict = PDFDict(
            {
                "Type": PDFName("XObject"),
                "Subtype": PDFName("Image"),
                "Width": 32,
                "Height": 24,
                "Filter": PDFName("JPXDecode"),
            }
        )
        stream = PDFStream(sdict, memoryview(jp2_data))
        pdf_img = PDFImage.from_stream(stream)

        # Build DocumentIR with ImageBlock
        page = DocumentPage(page_number=1, width=612.0, height=792.0)
        img_block = ImageBlock(
            image_bytes=pdf_img.to_bytes(),
            format=pdf_img.format,
            pixel_width=pdf_img.width,
            pixel_height=pdf_img.height,
        )
        page.blocks.append(img_block)
        doc = DocumentIR(pages=[page], metadata={"title": "JPX Test Document"})

        # Convert to DOCX, PPTX, ODT, ODP, TXT
        docx_bytes = DocxEmitter().emit(doc)
        self.assertTrue(docx_bytes.startswith(b"PK\x03\x04"))

        pptx_bytes = PptxEmitter().emit(doc)
        self.assertTrue(pptx_bytes.startswith(b"PK\x03\x04"))

        odt_bytes = OdtEmitter().emit(doc)
        self.assertTrue(odt_bytes.startswith(b"PK\x03\x04"))

        odp_bytes = OdpEmitter().emit(doc)
        self.assertTrue(odp_bytes.startswith(b"PK\x03\x04"))

        txt_bytes = TxtFlowEmitter().emit(doc)
        self.assertIn(b"![Image", txt_bytes)


if __name__ == "__main__":
    unittest.main()
