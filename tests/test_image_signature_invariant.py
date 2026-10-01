"""Comprehensive tests for ImageBlock signatures, format detection, and IR validation invariants.

Validates that:
1. detect_image_format recognizes PNG, JPEG, WebP, GIF, BMP, TIFF, SVG, and rejects unknown bytes.
2. ImageBlock properties (image_bytes, mime_type) operate correctly across all formats.
3. validate_document_ir auto-heals format mismatches (e.g. format="jpeg" with PNG bytes, or format="png" with JPEG bytes)
   and completely prevents the "Page 1 ImageBlock has invalid JPEG signature" failure.
4. validate_document_ir strictly rejects truly corrupted or non-image payloads.
5. DocumentIRBuilder produces valid ImageBlocks that pass IR validation for both JPEG and PNG streams.
"""

from __future__ import annotations

import pytest

from anyconvert.common.color import Color
from anyconvert.common.geometry import BoundingBox, Matrix3x3, Point
from anyconvert.exceptions import IRValidationError
from anyconvert.ir.builder import DocumentIRBuilder
from anyconvert.ir.model import (
    DocumentIR,
    DocumentPage,
    ImageBlock,
    Paragraph,
    TextRun,
    detect_image_format,
)
from anyconvert.ir.validator import validate_document_ir
from anyconvert.pdf.content.interpreter import ImageElement, InterpreterOutput
from anyconvert.pdf.parser import PDFDict, PDFName, PDFStream
from anyconvert.utils.png import PNG_SIGNATURE, encode_rgb_png

# Sample valid signatures
JPEG_MAGIC_SAMPLE = b"\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + b"\x00" * 30 + b"\xFF\xD9"
WEBP_MAGIC_SAMPLE = b"RIFF\x24\x00\x00\x00WEBPVP8 \x18\x00\x00\x00" + b"\x00" * 24
GIF87A_SAMPLE = b"GIF87a\x0A\x00\x0A\x00\x80\x00\x00" + b"\x00" * 20
GIF89A_SAMPLE = b"GIF89a\x0A\x00\x0A\x00\x80\x00\x00" + b"\x00" * 20
BMP_SAMPLE = b"BM\x36\x00\x00\x00\x00\x00\x00\x00\x36\x00\x00\x00" + b"\x00" * 40
TIFF_LE_SAMPLE = b"II*\x00\x08\x00\x00\x00" + b"\x00" * 20
TIFF_BE_SAMPLE = b"MM\x00*\x00\x00\x00\x08" + b"\x00" * 20
SVG_SAMPLE = b"<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"100\" height=\"100\"><circle cx=\"50\" cy=\"50\" r=\"40\"/></svg>"
SVG_XML_SAMPLE = b"<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<svg width=\"50\" height=\"50\"></svg>"


# ==============================================================================
# 1. detect_image_format Unit Tests
# ==============================================================================

def test_detect_image_format_png() -> None:
    """Test detecting valid PNG signatures."""
    png_data = encode_rgb_png(2, 2, b"\xFF\x00\x00\x00\xFF\x00\x00\x00\xFF\xFF\xFF\xFF")
    assert detect_image_format(png_data) == "png"
    assert detect_image_format(PNG_SIGNATURE + b"\x00" * 10) == "png"


def test_detect_image_format_jpeg() -> None:
    """Test detecting valid JPEG magic bytes."""
    assert detect_image_format(JPEG_MAGIC_SAMPLE) == "jpeg"
    assert detect_image_format(b"\xFF\xD8\xFF\xEE\x00\x0eAdobe") == "jpeg"


def test_detect_image_format_webp() -> None:
    """Test detecting valid WebP magic bytes."""
    assert detect_image_format(WEBP_MAGIC_SAMPLE) == "webp"


def test_detect_image_format_gif() -> None:
    """Test detecting GIF87a and GIF89a signatures."""
    assert detect_image_format(GIF87A_SAMPLE) == "gif"
    assert detect_image_format(GIF89A_SAMPLE) == "gif"


def test_detect_image_format_bmp() -> None:
    """Test detecting BMP signature."""
    assert detect_image_format(BMP_SAMPLE) == "bmp"


def test_detect_image_format_tiff() -> None:
    """Test detecting little-endian and big-endian TIFF signatures."""
    assert detect_image_format(TIFF_LE_SAMPLE) == "tiff"
    assert detect_image_format(TIFF_BE_SAMPLE) == "tiff"


def test_detect_image_format_svg() -> None:
    """Test detecting raw and XML-prefixed SVG markup."""
    assert detect_image_format(SVG_SAMPLE) == "svg"
    assert detect_image_format(SVG_XML_SAMPLE) == "svg"


def test_detect_image_format_unknown_and_empty() -> None:
    """Test that empty or random corrupt bytes return 'unknown'."""
    assert detect_image_format(b"") == "unknown"
    assert detect_image_format(b"RANDOM_NON_IMAGE_BYTES_HERE") == "unknown"
    assert detect_image_format(b"\x00\x01\x02\x03\x04\x05") == "unknown"


# ==============================================================================
# 2. ImageBlock Model Properties & Multi-Format Attributes
# ==============================================================================

def test_image_block_properties_and_mime_types() -> None:
    """Test ImageBlock image_bytes alias and MIME type mappings."""
    bbox = BoundingBox(10, 10, 110, 110)

    png_block = ImageBlock(png_bytes=PNG_SIGNATURE + b"...", bbox=bbox, format="png")
    assert png_block.image_bytes == png_block.png_bytes
    assert png_block.mime_type == "image/png"

    jpeg_block = ImageBlock(png_bytes=JPEG_MAGIC_SAMPLE, bbox=bbox, format="jpeg")
    assert jpeg_block.image_bytes == JPEG_MAGIC_SAMPLE
    assert jpeg_block.mime_type == "image/jpeg"

    jpg_block = ImageBlock(png_bytes=JPEG_MAGIC_SAMPLE, bbox=bbox, format="jpg")
    assert jpg_block.mime_type == "image/jpeg"

    webp_block = ImageBlock(png_bytes=WEBP_MAGIC_SAMPLE, bbox=bbox, format="webp")
    assert webp_block.mime_type == "image/webp"

    gif_block = ImageBlock(png_bytes=GIF89A_SAMPLE, bbox=bbox, format="gif")
    assert gif_block.mime_type == "image/gif"

    bmp_block = ImageBlock(png_bytes=BMP_SAMPLE, bbox=bbox, format="bmp")
    assert bmp_block.mime_type == "image/bmp"

    tiff_block = ImageBlock(png_bytes=TIFF_LE_SAMPLE, bbox=bbox, format="tiff")
    assert tiff_block.mime_type == "image/tiff"

    svg_block = ImageBlock(png_bytes=SVG_SAMPLE, bbox=bbox, format="svg")
    assert svg_block.mime_type == "image/svg+xml"

    unknown_block = ImageBlock(png_bytes=b"mystery", bbox=bbox, format="other")
    assert unknown_block.mime_type == "application/octet-stream"


# ==============================================================================
# 3. Validation & Auto-Healing of Format Mismatches
# ==============================================================================

def test_validator_auto_heals_jpeg_format_with_png_bytes() -> None:
    """Reproduces the exact bug from the screenshot:
    format='jpeg' but png_bytes contains valid PNG data from to_png().
    validate_document_ir must auto-heal format to 'png' and pass without error.
    """
    valid_png = encode_rgb_png(2, 2, b"\xFF\x00\x00\x00\xFF\x00\x00\x00\xFF\xFF\xFF\xFF")

    # Mismatched ImageBlock: format claims jpeg, but bytes are png
    img = ImageBlock(
        png_bytes=valid_png,
        bbox=BoundingBox(50, 50, 200, 200),
        format="jpeg",
    )

    page = DocumentPage(page_number=1, width=612.0, height=792.0, blocks=[img])
    doc_ir = DocumentIR(pages=[page])

    # Must NOT raise IRValidationError!
    validate_document_ir(doc_ir)

    # Format should be auto-healed to 'png'
    assert img.format == "png"


def test_validator_auto_heals_png_format_with_jpeg_bytes() -> None:
    """Test that format='png' with valid JPEG bytes auto-heals to 'jpeg' and passes."""
    img = ImageBlock(
        png_bytes=JPEG_MAGIC_SAMPLE,
        bbox=BoundingBox(50, 50, 200, 200),
        format="png",
    )

    page = DocumentPage(page_number=1, width=612.0, height=792.0, blocks=[img])
    doc_ir = DocumentIR(pages=[page])

    validate_document_ir(doc_ir)
    assert img.format == "jpeg"


def test_validator_accepts_pure_jpeg_block() -> None:
    """Test that a standard format='jpeg' with valid JPEG bytes passes cleanly."""
    img = ImageBlock(
        png_bytes=JPEG_MAGIC_SAMPLE,
        bbox=BoundingBox(10, 10, 100, 100),
        format="jpeg",
    )
    page = DocumentPage(page_number=1, width=612.0, height=792.0, blocks=[img])
    doc_ir = DocumentIR(pages=[page])
    validate_document_ir(doc_ir)


def test_validator_accepts_pure_webp_block() -> None:
    """Test that a format='webp' with valid WebP bytes passes cleanly."""
    img = ImageBlock(
        png_bytes=WEBP_MAGIC_SAMPLE,
        bbox=BoundingBox(10, 10, 100, 100),
        format="webp",
    )
    page = DocumentPage(page_number=1, width=612.0, height=792.0, blocks=[img])
    doc_ir = DocumentIR(pages=[page])
    validate_document_ir(doc_ir)


def test_validator_rejects_empty_image_bytes() -> None:
    """Test that an ImageBlock with empty bytes raises IRValidationError."""
    img = ImageBlock(png_bytes=b"", bbox=BoundingBox(10, 10, 50, 50))
    page = DocumentPage(page_number=1, width=612.0, height=792.0, blocks=[img])
    with pytest.raises(IRValidationError, match="empty png_bytes"):
        validate_document_ir(DocumentIR(pages=[page]))


def test_validator_rejects_corrupted_non_image_payload() -> None:
    """Test that non-image garbage bytes raise IRValidationError."""
    img = ImageBlock(
        png_bytes=b"CORRUPT_NOT_ANY_IMAGE_FORMAT_RANDOM_DATA_12345",
        bbox=BoundingBox(10, 10, 50, 50),
        format="png",
    )
    page = DocumentPage(page_number=1, width=612.0, height=792.0, blocks=[img])
    with pytest.raises(IRValidationError):
        validate_document_ir(DocumentIR(pages=[page]))


def test_validator_rejects_non_positive_bbox() -> None:
    """Test that an ImageBlock with non-positive dimensions raises IRValidationError."""
    valid_png = encode_rgb_png(1, 1, b"\x00\x00\x00")
    img = ImageBlock(png_bytes=valid_png, bbox=BoundingBox(10, 10, 10, 10))  # width=0, height=0
    page = DocumentPage(page_number=1, width=612.0, height=792.0, blocks=[img])
    with pytest.raises(IRValidationError, match="non-positive bbox"):
        validate_document_ir(DocumentIR(pages=[page]))


# ==============================================================================
# 4. DocumentIRBuilder Image Integration Tests
# ==============================================================================

def test_builder_with_jpeg_stream_passes_validation() -> None:
    """Test that DocumentIRBuilder processes a page with a JPEG stream and passes validation."""
    page_w = 612.0
    page_h = 792.0

    # Create a synthetic PDF stream representing a DCT-compressed image
    # Note: JPEG SOI (\xFF\xD8\xFF) header
    stream_dict = PDFDict({
        "Type": PDFName("XObject"),
        "Subtype": PDFName("Image"),
        "Width": 10,
        "Height": 10,
        "BitsPerComponent": 8,
        "ColorSpace": PDFName("DeviceRGB"),
        "Filter": PDFName("DCTDecode"),
    })
    jpeg_stream = PDFStream(stream_dict, memoryview(JPEG_MAGIC_SAMPLE))

    im_el = ImageElement(
        name="Im1",
        ctm=Matrix3x3.identity(),
        bbox=BoundingBox(50, 400, 250, 600),
        stream=jpeg_stream,
    )

    interp_output = InterpreterOutput(
        text_elements=[],
        vector_elements=[],
        image_elements=[im_el],
    )

    builder = DocumentIRBuilder()
    doc_page = builder.build_page(
        output=interp_output,
        page_width=page_w,
        page_height=page_h,
        page_number=1,
    )
    doc_ir = builder.build_document([doc_page])

    # Must pass validation without raising "invalid JPEG signature"!
    validate_document_ir(doc_ir)

    assert len(doc_ir.pages) == 1
    page = doc_ir.pages[0]
    images = [b for b in page.blocks if isinstance(b, ImageBlock)]
    assert len(images) == 1
    img = images[0]
    # Check that format is valid and matches the actual bytes
    assert img.format in ("jpeg", "png")
    if img.format == "jpeg":
        assert img.png_bytes.startswith(b"\xFF\xD8\xFF")
    else:
        assert img.png_bytes.startswith(PNG_SIGNATURE)


def test_builder_with_fallback_image_passes_validation() -> None:
    """Test that DocumentIRBuilder gracefully handles broken streams and passes validation."""
    im_el = ImageElement(
        name="BrokenIm",
        ctm=Matrix3x3.identity(),
        bbox=BoundingBox(50, 400, 250, 600),
        stream=None,  # No stream -> fallback 1x1 PNG
    )
    interp_output = InterpreterOutput(
        text_elements=[],
        vector_elements=[],
        image_elements=[im_el],
    )

    builder = DocumentIRBuilder()
    doc_page = builder.build_page(
        output=interp_output,
        page_width=612.0,
        page_height=792.0,
        page_number=1,
    )
    doc_ir = builder.build_document([doc_page])

    validate_document_ir(doc_ir)
    images = [b for b in doc_ir.pages[0].blocks if isinstance(b, ImageBlock)]
    assert len(images) == 1
    assert images[0].format == "png"
    assert images[0].png_bytes.startswith(PNG_SIGNATURE)
