"""Tests for pure-Python WebP image parser, metadata extraction, and emitter integration."""

from __future__ import annotations

import unittest
import zipfile
import io

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

        # webp_to_rgba on corrupt data should safely return a 1x1 fallback buffer
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
