"""Tests for pure-Python PNG serialization and PDF raster image extraction."""

import zlib
import pytest

from anyconvert.exceptions import PDFSyntaxError, SerializationError
from anyconvert.pdf.content.interpreter import ContentInterpreter
from anyconvert.pdf.graphics.image import PDFImage
from anyconvert.pdf.parser import (
    PDFArray,
    PDFDict,
    PDFHexString,
    PDFIndirectRef,
    PDFName,
    PDFStream,
    PDFString,
)
from anyconvert.utils.png import (
    COLOR_TYPE_GRAY,
    COLOR_TYPE_INDEXED,
    COLOR_TYPE_RGB,
    COLOR_TYPE_RGBA,
    PNG_SIGNATURE,
    create_chunk,
    encode_gray_png,
    encode_png,
    encode_rgb_png,
    encode_rgba_png,
    parse_png,
)


def test_png_signature_and_create_chunk() -> None:
    """Test standard PNG signature and chunk creation with CRC32."""
    assert PNG_SIGNATURE == b"\x89PNG\r\n\x1a\n"

    chunk = create_chunk(b"IEND", b"")
    # Length (4 bytes: 0) + Type (4 bytes: b"IEND") + CRC32 (4 bytes: 0xAE426082)
    assert len(chunk) == 12
    assert chunk[:4] == b"\x00\x00\x00\x00"
    assert chunk[4:8] == b"IEND"
    crc_expected = zlib.crc32(b"IEND") & 0xFFFFFFFF
    assert chunk[8:12] == crc_expected.to_bytes(4, "big")

    with pytest.raises(SerializationError):
        create_chunk(b"BAD", b"")


def test_png_encode_parse_roundtrip_rgba() -> None:
    """Test encoding and parsing RGBA 8-bit PNG."""
    width = 2
    height = 2
    # 2x2 image: Red, Green, Blue, Semi-transparent White
    pixels = bytes([
        255, 0, 0, 255,    # (0, 0)
        0, 255, 0, 255,    # (1, 0)
        0, 0, 255, 255,    # (0, 1)
        255, 255, 255, 128 # (1, 1)
    ])

    png_bytes = encode_rgba_png(width, height, pixels)
    assert png_bytes.startswith(PNG_SIGNATURE)

    w, h, ct, bd, raw = parse_png(png_bytes)
    assert w == width
    assert h == height
    assert ct == COLOR_TYPE_RGBA
    assert bd == 8
    assert raw == pixels


def test_png_encode_parse_roundtrip_rgb() -> None:
    """Test encoding and parsing RGB 8-bit PNG."""
    width = 3
    height = 1
    # 3x1 image: Red, Green, Blue
    pixels = bytes([
        255, 0, 0,
        0, 255, 0,
        0, 0, 255,
    ])

    png_bytes = encode_rgb_png(width, height, pixels)
    w, h, ct, bd, raw = parse_png(png_bytes)
    assert w == width
    assert h == height
    assert ct == COLOR_TYPE_RGB
    assert bd == 8
    assert raw == pixels


def test_png_encode_parse_roundtrip_gray() -> None:
    """Test encoding and parsing Grayscale 8-bit PNG."""
    width = 4
    height = 2
    pixels = bytes([
        0, 64, 128, 255,
        10, 20, 30, 40,
    ])

    png_bytes = encode_gray_png(width, height, pixels, bit_depth=8)
    w, h, ct, bd, raw = parse_png(png_bytes)
    assert w == width
    assert h == height
    assert ct == COLOR_TYPE_GRAY
    assert bd == 8
    assert raw == pixels


def test_png_encode_indexed() -> None:
    """Test encoding Indexed PNG with PLTE chunk."""
    width = 2
    height = 2
    palette = bytes([
        255, 0, 0,   # 0: Red
        0, 255, 0,   # 1: Green
        0, 0, 255,   # 2: Blue
    ])
    indices = bytes([0, 1, 2, 0])

    png_bytes = encode_png(
        width=width,
        height=height,
        data=indices,
        color_type=COLOR_TYPE_INDEXED,
        bit_depth=8,
        palette=palette,
    )
    w, h, ct, bd, raw = parse_png(png_bytes)
    assert w == width
    assert h == height
    assert ct == COLOR_TYPE_INDEXED
    assert raw == indices


def test_png_invalid_parameters() -> None:
    """Test defensive validation in PNG encoder and parser."""
    with pytest.raises(SerializationError):
        encode_png(0, 10, b"")

    with pytest.raises(SerializationError):
        encode_png(10, 10, b"123", color_type=99)

    with pytest.raises(SerializationError):
        encode_png(10, 10, b"123", color_type=COLOR_TYPE_RGB, bit_depth=1)

    with pytest.raises(SerializationError):
        parse_png(b"NOT_A_PNG")

    with pytest.raises(SerializationError):
        # Truncated after signature
        parse_png(PNG_SIGNATURE + b"\x00\x00")


def test_pdf_image_1bit_monochrome_row_padding() -> None:
    """Test 1-bit monochrome image with byte-aligned row padding (e.g. 5x2 pixels)."""
    # 5 pixels per row: requires 5 bits. Rounded up to byte alignment = 1 byte per row.
    # Total stream size = 2 rows * 1 byte = 2 bytes.
    # Row 0: 5 bits 1, 0, 1, 0, 1 -> 0b10101000 = 0xA8
    # Row 1: 5 bits 0, 1, 0, 1, 0 -> 0b01010000 = 0x50
    raw_stream_data = bytes([0xA8, 0x50])

    stream = PDFStream(
        dict=PDFDict({
            "Type": PDFName("XObject"),
            "Subtype": PDFName("Image"),
            "Width": 5,
            "Height": 2,
            "ColorSpace": PDFName("DeviceGray"),
            "BitsPerComponent": 1,
        }),
        data=memoryview(raw_stream_data),
    )

    img = PDFImage.from_stream(stream)
    assert img.width == 5
    assert img.height == 2
    assert img.color_space_name == "DeviceGray"
    assert img.bits_per_component == 1
    assert not img.has_alpha

    gray = img.to_gray()
    assert len(gray) == 10
    # 1-bit 1 maps to 255, 0 maps to 0
    assert list(gray[:5]) == [255, 0, 255, 0, 255]
    assert list(gray[5:]) == [0, 255, 0, 255, 0]

    # Verify PNG generation
    png_bytes = img.to_png()
    w, h, ct, bd, raw = parse_png(png_bytes)
    assert w == 5
    assert h == 2
    assert raw == gray


def test_pdf_image_1bit_inverted_decode() -> None:
    """Test 1-bit monochrome image with inverted /Decode [1, 0] array."""
    raw_stream_data = bytes([0x80])  # 1 pixel = 1, rest padding

    stream = PDFStream(
        dict=PDFDict({
            "Type": PDFName("XObject"),
            "Subtype": PDFName("Image"),
            "Width": 1,
            "Height": 1,
            "ColorSpace": PDFName("DeviceGray"),
            "BitsPerComponent": 1,
            "Decode": PDFArray([1, 0]),
        }),
        data=memoryview(raw_stream_data),
    )

    img = PDFImage.from_stream(stream)
    # With [1, 0], sample 1 becomes 0 (black), sample 0 becomes 255 (white)
    gray = img.to_gray()
    assert gray[0] == 0


def test_pdf_image_8bit_grayscale_flate() -> None:
    """Test 8-bit DeviceGray image compressed with FlateDecode."""
    width = 2
    height = 2
    raw_pixels = bytes([0, 85, 170, 255])
    compressed = zlib.compress(raw_pixels)

    stream = PDFStream(
        dict=PDFDict({
            "Type": PDFName("XObject"),
            "Subtype": PDFName("Image"),
            "Width": width,
            "Height": height,
            "ColorSpace": PDFName("DeviceGray"),
            "BitsPerComponent": 8,
            "Filter": PDFName("FlateDecode"),
        }),
        data=memoryview(compressed),
    )

    img = PDFImage.from_stream(stream)
    assert img.width == 2
    assert img.height == 2
    assert img.to_gray() == raw_pixels
    assert img.to_rgb() == bytes([0, 0, 0, 85, 85, 85, 170, 170, 170, 255, 255, 255])


def test_pdf_image_8bit_rgb() -> None:
    """Test 8-bit DeviceRGB image extraction."""
    width = 2
    height = 1
    rgb_pixels = bytes([
        255, 0, 0,   # Red
        0, 255, 0,   # Green
    ])

    stream = PDFStream(
        dict=PDFDict({
            "Type": PDFName("XObject"),
            "Subtype": PDFName("Image"),
            "Width": width,
            "Height": height,
            "ColorSpace": PDFName("DeviceRGB"),
            "BitsPerComponent": 8,
        }),
        data=memoryview(rgb_pixels),
    )

    img = PDFImage.from_stream(stream)
    assert img.width == 2
    assert img.height == 1
    assert img.to_rgb() == rgb_pixels
    rgba = img.to_rgba()
    assert rgba == bytes([255, 0, 0, 255, 0, 255, 0, 255])


def test_pdf_image_cmyk_subtractive_conversion() -> None:
    """Test 8-bit DeviceCMYK conversion using subtractive RGB equations."""
    # 5 test pixels in CMYK:
    # 1. Pure Cyan: (255, 0, 0, 0) -> R = 255*(1-1)*(1-0) = 0, G = 255, B = 255 -> (0, 255, 255)
    # 2. Pure Magenta: (0, 255, 0, 0) -> (255, 0, 255)
    # 3. Pure Yellow: (0, 0, 255, 0) -> (255, 255, 0)
    # 4. Pure Black: (0, 0, 0, 255) -> (0, 0, 0)
    # 5. Pure White: (0, 0, 0, 0) -> (255, 255, 255)
    cmyk_data = bytes([
        255, 0, 0, 0,
        0, 255, 0, 0,
        0, 0, 255, 0,
        0, 0, 0, 255,
        0, 0, 0, 0,
    ])

    stream = PDFStream(
        dict=PDFDict({
            "Type": PDFName("XObject"),
            "Subtype": PDFName("Image"),
            "Width": 5,
            "Height": 1,
            "ColorSpace": PDFName("DeviceCMYK"),
            "BitsPerComponent": 8,
        }),
        data=memoryview(cmyk_data),
    )

    img = PDFImage.from_stream(stream)
    assert img.color_space_name == "DeviceCMYK"
    rgb = img.to_rgb()

    expected_rgb = bytes([
        0, 255, 255,    # Cyan
        255, 0, 255,    # Magenta
        255, 255, 0,    # Yellow
        0, 0, 0,        # Black
        255, 255, 255,  # White
    ])
    assert rgb == expected_rgb


def test_pdf_image_2bit_and_4bit_grayscale() -> None:
    """Test 2-bit and 4-bit grayscale sample unpacking."""
    # 2-bit: 4 samples per byte: 0, 1, 2, 3 -> (0, 85, 170, 255)
    # Width 4, Height 1 -> 1 byte
    stream_2bit = PDFStream(
        dict=PDFDict({
            "Type": PDFName("XObject"),
            "Subtype": PDFName("Image"),
            "Width": 4,
            "Height": 1,
            "ColorSpace": PDFName("DeviceGray"),
            "BitsPerComponent": 2,
        }),
        data=memoryview(bytes([0b00_01_10_11])),
    )
    img_2bit = PDFImage.from_stream(stream_2bit)
    assert list(img_2bit.to_gray()) == [0, 85, 170, 255]

    # 4-bit: 2 samples per byte: 0, 15 -> (0, 255)
    # Width 2, Height 1 -> 1 byte
    stream_4bit = PDFStream(
        dict=PDFDict({
            "Type": PDFName("XObject"),
            "Subtype": PDFName("Image"),
            "Width": 2,
            "Height": 1,
            "ColorSpace": PDFName("DeviceGray"),
            "BitsPerComponent": 4,
        }),
        data=memoryview(bytes([0x0F])),
    )
    img_4bit = PDFImage.from_stream(stream_4bit)
    assert list(img_4bit.to_gray()) == [0, 255]


def test_pdf_image_16bit_rgb() -> None:
    """Test 16-bit RGB downsampling to 8-bit RGBA and RGB."""
    # 1 pixel, 3 components, 16 bits = 6 bytes
    # Red = 0xFFFF (65535 -> 255), Green = 0x8000 (32768 -> 128), Blue = 0x0000 (0 -> 0)
    data = bytes([0xFF, 0xFF, 0x80, 0x00, 0x00, 0x00])

    stream = PDFStream(
        dict=PDFDict({
            "Type": PDFName("XObject"),
            "Subtype": PDFName("Image"),
            "Width": 1,
            "Height": 1,
            "ColorSpace": PDFName("DeviceRGB"),
            "BitsPerComponent": 16,
        }),
        data=memoryview(data),
    )
    img = PDFImage.from_stream(stream)
    rgb = img.to_rgb()
    assert rgb[0] == 255
    assert rgb[1] == 128
    assert rgb[2] == 0


def test_pdf_image_indexed_palette() -> None:
    """Test Indexed color space with palette lookup table."""
    # Palette with 3 colors (RGB):
    # Index 0: Red (255, 0, 0)
    # Index 1: Green (0, 255, 0)
    # Index 2: Blue (0, 0, 255)
    palette = bytes([
        255, 0, 0,
        0, 255, 0,
        0, 0, 255,
    ])

    color_space = PDFArray([
        PDFName("Indexed"),
        PDFName("DeviceRGB"),
        2,  # hival
        PDFString(palette),
    ])

    # 4 pixels with indices 0, 1, 2, 0
    indices = bytes([0, 1, 2, 0])

    stream = PDFStream(
        dict=PDFDict({
            "Type": PDFName("XObject"),
            "Subtype": PDFName("Image"),
            "Width": 2,
            "Height": 2,
            "ColorSpace": color_space,
            "BitsPerComponent": 8,
        }),
        data=memoryview(indices),
    )

    img = PDFImage.from_stream(stream)
    assert img.color_space_name == "Indexed"
    rgb = img.to_rgb()
    expected = bytes([
        255, 0, 0,
        0, 255, 0,
        0, 0, 255,
        255, 0, 0,
    ])
    assert rgb == expected


def test_pdf_image_soft_mask_smask_blending() -> None:
    """Test Soft Mask (/SMask) blending an 8-bit alpha channel into an image."""
    # Main image: 2x1 RGB (Red, Blue)
    main_pixels = bytes([255, 0, 0, 0, 0, 255])

    # SMask: 2x1 Grayscale alpha (50% transparent, 100% opaque)
    smask_pixels = bytes([128, 255])
    smask_stream = PDFStream(
        dict=PDFDict({
            "Type": PDFName("XObject"),
            "Subtype": PDFName("Image"),
            "Width": 2,
            "Height": 1,
            "ColorSpace": PDFName("DeviceGray"),
            "BitsPerComponent": 8,
        }),
        data=memoryview(smask_pixels),
    )

    main_stream = PDFStream(
        dict=PDFDict({
            "Type": PDFName("XObject"),
            "Subtype": PDFName("Image"),
            "Width": 2,
            "Height": 1,
            "ColorSpace": PDFName("DeviceRGB"),
            "BitsPerComponent": 8,
            "SMask": smask_stream,
        }),
        data=memoryview(main_pixels),
    )

    img = PDFImage.from_stream(main_stream)
    assert img.has_alpha
    rgba = img.to_rgba()
    assert len(rgba) == 8
    # Pixel 0: Red with alpha 128
    assert rgba[0] == 255
    assert rgba[1] == 0
    assert rgba[2] == 0
    assert rgba[3] == 128
    # Pixel 1: Blue with alpha 255
    assert rgba[4] == 0
    assert rgba[5] == 0
    assert rgba[6] == 255
    assert rgba[7] == 255

    # Verify PNG serialization retains RGBA
    png_bytes = img.to_png()
    w, h, ct, bd, raw = parse_png(png_bytes)
    assert ct == COLOR_TYPE_RGBA
    assert raw == rgba


def test_pdf_image_explicit_mask_stream() -> None:
    """Test explicit 1-bit /Mask stream transparency blending."""
    # Main image: 2x1 RGB
    main_pixels = bytes([255, 0, 0, 0, 255, 0])

    # Mask stream: 1-bit mask where pixel 0 is 1 (painted -> alpha=255) and pixel 1 is 0 (unpainted -> alpha=0)
    # Byte: 0b10000000 = 0x80
    mask_stream = PDFStream(
        dict=PDFDict({
            "Type": PDFName("XObject"),
            "Subtype": PDFName("Image"),
            "Width": 2,
            "Height": 1,
            "ColorSpace": PDFName("DeviceGray"),
            "BitsPerComponent": 1,
            "ImageMask": True,
        }),
        data=memoryview(bytes([0x80])),
    )

    main_stream = PDFStream(
        dict=PDFDict({
            "Type": PDFName("XObject"),
            "Subtype": PDFName("Image"),
            "Width": 2,
            "Height": 1,
            "ColorSpace": PDFName("DeviceRGB"),
            "BitsPerComponent": 8,
            "Mask": mask_stream,
        }),
        data=memoryview(main_pixels),
    )

    img = PDFImage.from_stream(main_stream)
    assert img.has_alpha
    rgba = img.to_rgba()
    # Pixel 0 is painted (opaque)
    assert rgba[3] == 255
    # Pixel 1 is unpainted (transparent)
    assert rgba[7] == 0



def test_pdf_image_color_key_mask() -> None:
    """Test Color Key Masking via /Mask [min max ...] array."""
    # 2x1 RGB: Pixel 0 is Green (0, 255, 0), Pixel 1 is Red (255, 0, 0)
    main_pixels = bytes([0, 255, 0, 255, 0, 0])

    # Mask green color: R: 0..10, G: 250..255, B: 0..10
    color_key = PDFArray([0, 10, 250, 255, 0, 10])

    main_stream = PDFStream(
        dict=PDFDict({
            "Type": PDFName("XObject"),
            "Subtype": PDFName("Image"),
            "Width": 2,
            "Height": 1,
            "ColorSpace": PDFName("DeviceRGB"),
            "BitsPerComponent": 8,
            "Mask": color_key,
        }),
        data=memoryview(main_pixels),
    )

    img = PDFImage.from_stream(main_stream)
    assert img.has_alpha
    rgba = img.to_rgba()
    # Pixel 0 (Green) should be transparent (alpha = 0)
    assert rgba[3] == 0
    # Pixel 1 (Red) should remain opaque (alpha = 255)
    assert rgba[7] == 255


def test_pdf_image_stencil_imagemask() -> None:
    """Test 1-bit stencil ImageMask (/ImageMask true)."""
    # 2x1 stencil mask: 0b10000000 = 0x80 -> pixel 0 is 1 (paint), pixel 1 is 0 (transparent)
    stream = PDFStream(
        dict=PDFDict({
            "Type": PDFName("XObject"),
            "Subtype": PDFName("Image"),
            "Width": 2,
            "Height": 1,
            "ImageMask": True,
            "BitsPerComponent": 1,
        }),
        data=memoryview(bytes([0x80])),
    )

    img = PDFImage.from_stream(stream)
    assert img.has_alpha
    rgba = img.to_rgba()
    # Pixel 0 painted black (opaque)
    assert rgba[:4] == bytes([0, 0, 0, 255])
    # Pixel 1 not painted (transparent)
    assert rgba[7] == 0


def test_interpreter_image_integration() -> None:
    """Test that ContentInterpreter captures ImageElement with stream and can decode PDFImage."""
    img_stream = PDFStream(
        dict=PDFDict({
            "Type": PDFName("XObject"),
            "Subtype": PDFName("Image"),
            "Width": 2,
            "Height": 2,
            "ColorSpace": PDFName("DeviceRGB"),
            "BitsPerComponent": 8,
        }),
        data=memoryview(bytes([255] * 12)),
    )

    resources = PDFDict({
        "XObject": PDFDict({
            "Logo": img_stream,
        })
    })

    content = """
    q
      200 0 0 100 50 150 cm
      /Logo Do
    Q
    """
    interpreter = ContentInterpreter(resources=resources)
    output = interpreter.interpret(content)

    assert len(output.image_elements) == 1
    el = output.image_elements[0]
    assert el.name == "Logo"
    assert el.stream is not None

    pdf_image = PDFImage.from_stream(el.stream)
    assert pdf_image.width == 2
    assert pdf_image.height == 2
    assert len(pdf_image.to_rgb()) == 12
    png_bytes = pdf_image.to_png()
    assert png_bytes.startswith(PNG_SIGNATURE)
