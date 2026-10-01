"""Tests for image signatures, format detection, and IR validation."""

from __future__ import annotations

import time
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
from anyconvert.pdf.graphics.image import PDFImage
from anyconvert.pdf.parser import PDFDict, PDFName, PDFStream
from anyconvert.utils.png import PNG_SIGNATURE, encode_rgb_png

JPEG_MAGIC_SAMPLE = b"\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + b"\x00" * 30 + b"\xFF\xD9"
WEBP_MAGIC_SAMPLE = b"RIFF\x24\x00\x00\x00WEBPVP8 \x18\x00\x00\x00" + b"\x00" * 24
GIF87A_SAMPLE = b"GIF87a\x0A\x00\x0A\x00\x80\x00\x00" + b"\x00" * 20
GIF89A_SAMPLE = b"GIF89a\x0A\x00\x0A\x00\x80\x00\x00" + b"\x00" * 20
BMP_SAMPLE = b"BM\x36\x00\x00\x00\x00\x00\x00\x00\x36\x00\x00\x00" + b"\x00" * 40
TIFF_LE_SAMPLE = b"II*\x00\x08\x00\x00\x00" + b"\x00" * 20
TIFF_BE_SAMPLE = b"MM\x00*\x00\x00\x00\x08" + b"\x00" * 20
SVG_SAMPLE = b"<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"100\" height=\"100\"><circle cx=\"50\" cy=\"50\" r=\"40\"/></svg>"
SVG_XML_SAMPLE = b"<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<svg width=\"50\" height=\"50\"></svg>"


def test_detect_image_format_png() -> None:
    png_data = encode_rgb_png(2, 2, b"\xFF\x00\x00\x00\xFF\x00\x00\x00\xFF\xFF\xFF\xFF")
    assert detect_image_format(png_data) == "png"
    assert detect_image_format(PNG_SIGNATURE + b"\x00" * 10) == "png"


def test_detect_image_format_jpeg() -> None:
    assert detect_image_format(JPEG_MAGIC_SAMPLE) == "jpeg"
    assert detect_image_format(b"\xFF\xD8\xFF\xEE\x00\x0eAdobe") == "jpeg"


def test_detect_image_format_webp() -> None:
    assert detect_image_format(WEBP_MAGIC_SAMPLE) == "webp"


def test_detect_image_format_gif() -> None:
    assert detect_image_format(GIF87A_SAMPLE) == "gif"
    assert detect_image_format(GIF89A_SAMPLE) == "gif"


def test_detect_image_format_bmp() -> None:
    assert detect_image_format(BMP_SAMPLE) == "bmp"


def test_detect_image_format_tiff() -> None:
    assert detect_image_format(TIFF_LE_SAMPLE) == "tiff"
    assert detect_image_format(TIFF_BE_SAMPLE) == "tiff"


def test_detect_image_format_svg() -> None:
    assert detect_image_format(SVG_SAMPLE) == "svg"
    assert detect_image_format(SVG_XML_SAMPLE) == "svg"


def test_detect_image_format_unknown_and_empty() -> None:
    assert detect_image_format(b"") == "unknown"
    assert detect_image_format(b"RANDOM_NON_IMAGE_BYTES_HERE") == "unknown"
    assert detect_image_format(b"\x00\x01\x02\x03\x04\x05") == "unknown"


def test_image_block_properties_and_mime_types() -> None:
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


def test_image_block_dual_initialization_and_setter() -> None:
    bbox = BoundingBox(0, 0, 50, 50)

    # Keyword image_bytes initialization
    b1 = ImageBlock(image_bytes=JPEG_MAGIC_SAMPLE, bbox=bbox, format="jpeg")
    assert b1.image_bytes == JPEG_MAGIC_SAMPLE
    assert b1.png_bytes == JPEG_MAGIC_SAMPLE

    # Keyword png_bytes initialization
    b2 = ImageBlock(png_bytes=JPEG_MAGIC_SAMPLE, bbox=bbox, format="jpeg")
    assert b2.image_bytes == JPEG_MAGIC_SAMPLE
    assert b2.png_bytes == JPEG_MAGIC_SAMPLE

    # Positional initialization
    b3 = ImageBlock(JPEG_MAGIC_SAMPLE, bbox)
    assert b3.image_bytes == JPEG_MAGIC_SAMPLE
    assert b3.png_bytes == JPEG_MAGIC_SAMPLE

    # Setter test
    b3.png_bytes = WEBP_MAGIC_SAMPLE
    assert b3.image_bytes == WEBP_MAGIC_SAMPLE
    assert b3.png_bytes == WEBP_MAGIC_SAMPLE


def test_image_block_file_extension() -> None:
    bbox = BoundingBox(0, 0, 50, 50)
    assert ImageBlock(image_bytes=b"...", bbox=bbox, format="png").file_extension == ".png"
    assert ImageBlock(image_bytes=b"...", bbox=bbox, format="jpeg").file_extension == ".jpeg"
    assert ImageBlock(image_bytes=b"...", bbox=bbox, format="jpg").file_extension == ".jpeg"
    assert ImageBlock(image_bytes=b"...", bbox=bbox, format="webp").file_extension == ".webp"
    assert ImageBlock(image_bytes=b"...", bbox=bbox, format="svg").file_extension == ".svg"
    assert ImageBlock(image_bytes=b"...", bbox=bbox, format="gif").file_extension == ".gif"
    assert ImageBlock(image_bytes=b"...", bbox=bbox, format="bmp").file_extension == ".bmp"
    assert ImageBlock(image_bytes=b"...", bbox=bbox, format="tiff").file_extension == ".tiff"


def test_image_block_sync_format() -> None:
    bbox = BoundingBox(0, 0, 50, 50)
    img_jpeg = ImageBlock(image_bytes=JPEG_MAGIC_SAMPLE, bbox=bbox, format="unknown")
    assert img_jpeg.sync_format() == "jpeg"
    assert img_jpeg.format == "jpeg"

    valid_png = encode_rgb_png(1, 1, b"\x00\x00\x00")
    img_png = ImageBlock(image_bytes=valid_png, bbox=bbox, format="other")
    assert img_png.sync_format() == "png"
    assert img_png.format == "png"

    img_webp = ImageBlock(image_bytes=WEBP_MAGIC_SAMPLE, bbox=bbox, format="other")
    assert img_webp.sync_format() == "webp"
    assert img_webp.format == "webp"


def test_validator_auto_heals_jpeg_format_with_png_bytes() -> None:
    """Test format auto-healing when jpeg format contains png bytes."""
    valid_png = encode_rgb_png(2, 2, b"\xFF\x00\x00\x00\xFF\x00\x00\x00\xFF\xFF\xFF\xFF")

    img = ImageBlock(
        png_bytes=valid_png,
        bbox=BoundingBox(50, 50, 200, 200),
        format="jpeg",
    )
    page = DocumentPage(page_number=1, width=612.0, height=792.0, blocks=[img])
    doc_ir = DocumentIR(pages=[page])

    validate_document_ir(doc_ir)
    assert img.format == "png"


def test_validator_auto_heals_png_format_with_jpeg_bytes() -> None:
    """Test format auto-healing when png format contains jpeg bytes."""
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
    img = ImageBlock(
        png_bytes=JPEG_MAGIC_SAMPLE,
        bbox=BoundingBox(10, 10, 100, 100),
        format="jpeg",
    )
    page = DocumentPage(page_number=1, width=612.0, height=792.0, blocks=[img])
    doc_ir = DocumentIR(pages=[page])
    validate_document_ir(doc_ir)


def test_validator_accepts_pure_webp_block() -> None:
    img = ImageBlock(
        png_bytes=WEBP_MAGIC_SAMPLE,
        bbox=BoundingBox(10, 10, 100, 100),
        format="webp",
    )
    page = DocumentPage(page_number=1, width=612.0, height=792.0, blocks=[img])
    doc_ir = DocumentIR(pages=[page])
    validate_document_ir(doc_ir)


def test_validator_rejects_empty_image_bytes() -> None:
    img = ImageBlock(png_bytes=b"", bbox=BoundingBox(10, 10, 50, 50))
    page = DocumentPage(page_number=1, width=612.0, height=792.0, blocks=[img])
    with pytest.raises(IRValidationError, match="empty png_bytes"):
        validate_document_ir(DocumentIR(pages=[page]))


def test_validator_rejects_corrupted_non_image_payload() -> None:
    img = ImageBlock(
        png_bytes=b"CORRUPT_NOT_ANY_IMAGE_FORMAT_RANDOM_DATA_12345",
        bbox=BoundingBox(10, 10, 50, 50),
        format="png",
    )
    page = DocumentPage(page_number=1, width=612.0, height=792.0, blocks=[img])
    with pytest.raises(IRValidationError):
        validate_document_ir(DocumentIR(pages=[page]))


def test_validator_rejects_non_positive_bbox() -> None:
    valid_png = encode_rgb_png(1, 1, b"\x00\x00\x00")
    img = ImageBlock(png_bytes=valid_png, bbox=BoundingBox(10, 10, 10, 10))
    page = DocumentPage(page_number=1, width=612.0, height=792.0, blocks=[img])
    with pytest.raises(IRValidationError, match="non-positive bbox"):
        validate_document_ir(DocumentIR(pages=[page]))


def test_builder_with_jpeg_stream_passes_validation() -> None:
    """Test builder processes JPEG streams into valid IR."""
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
        page_width=612.0,
        page_height=792.0,
        page_number=1,
    )
    doc_ir = builder.build_document([doc_page])

    validate_document_ir(doc_ir)
    assert len(doc_ir.pages) == 1
    page = doc_ir.pages[0]
    images = [b for b in page.blocks if isinstance(b, ImageBlock)]
    assert len(images) == 1
    img = images[0]
    assert img.format in ("jpeg", "png")
    if img.format == "jpeg":
        assert img.png_bytes.startswith(b"\xFF\xD8\xFF")
    else:
        assert img.png_bytes.startswith(PNG_SIGNATURE)


def test_builder_with_fallback_image_passes_validation() -> None:
    """Test builder gracefully handles broken image streams."""
    im_el = ImageElement(
        name="BrokenIm",
        ctm=Matrix3x3.identity(),
        bbox=BoundingBox(50, 400, 250, 600),
        stream=None,
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


def test_pdfimage_lossless_jpeg_passthrough() -> None:
    """Test PDFImage lossless pass-through on DCT stream."""
    stream_dict = PDFDict({
        "Type": PDFName("XObject"),
        "Subtype": PDFName("Image"),
        "Width": 640,
        "Height": 480,
        "BitsPerComponent": 8,
        "ColorSpace": PDFName("DeviceRGB"),
        "Filter": PDFName("DCTDecode"),
    })
    jpeg_stream = PDFStream(stream_dict, memoryview(JPEG_MAGIC_SAMPLE))

    img = PDFImage.from_stream(jpeg_stream)

    assert img.format == "jpeg"
    assert img.has_alpha is False
    assert img.width == 640
    assert img.height == 480
    assert img.raw_data == JPEG_MAGIC_SAMPLE
    assert img.to_bytes() == JPEG_MAGIC_SAMPLE

    png = img.to_png()
    assert png.startswith(PNG_SIGNATURE)
    assert len(img.to_rgba()) == 640 * 480 * 4
    assert len(img.to_rgb()) == 640 * 480 * 3


def test_pdfimage_lossless_jpeg_passthrough_instant_execution() -> None:
    """Test PDFImage pass-through performance without raster decoding."""
    stream_dict = PDFDict({
        "Type": PDFName("XObject"),
        "Subtype": PDFName("Image"),
        "Width": 4000,
        "Height": 3000,
        "BitsPerComponent": 8,
        "ColorSpace": PDFName("DeviceRGB"),
        "Filter": PDFName("DCTDecode"),
    })
    jpeg_stream = PDFStream(stream_dict, memoryview(JPEG_MAGIC_SAMPLE))

    t0 = time.perf_counter()
    img = PDFImage.from_stream(jpeg_stream)
    elapsed = time.perf_counter() - t0

    assert img.format == "jpeg"
    assert elapsed < 0.05


def test_pdfimage_jpeg_with_smask_transparency_blends_to_png() -> None:
    """Test PDFImage blends DCT stream with SMask into PNG."""
    base_dict = PDFDict({
        "Type": PDFName("XObject"),
        "Subtype": PDFName("Image"),
        "Width": 2,
        "Height": 2,
        "BitsPerComponent": 8,
        "ColorSpace": PDFName("DeviceRGB"),
        "Filter": PDFName("DCTDecode"),
    })
    smask_dict = PDFDict({
        "Type": PDFName("XObject"),
        "Subtype": PDFName("Image"),
        "Width": 2,
        "Height": 2,
        "BitsPerComponent": 8,
        "ColorSpace": PDFName("DeviceGray"),
    })
    smask_stream = PDFStream(smask_dict, memoryview(bytes([0, 128, 200, 255])))

    base_dict["SMask"] = smask_stream
    base_stream = PDFStream(base_dict, memoryview(JPEG_MAGIC_SAMPLE))

    img = PDFImage.from_stream(base_stream)

    assert img.has_alpha is True
    assert img.format == "png"
    assert img.to_bytes().startswith(PNG_SIGNATURE)
