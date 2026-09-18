"""
Unit and integration tests for Part 2: Layout Analysis, Text, Markdown, and Image converters.
"""

import io
from pathlib import Path
import pytest
from PIL import Image
import pymupdf

import anyconvert
from anyconvert.analysis.layout import extract_document_layout
from anyconvert.core.models import ImageBlock, ParagraphBlock





def test_dla_layout_analysis(sample_pdf: Path):
    """Verify that layout analysis reconstructs paragraphs, headings, bullets, and images."""
    ir_doc = extract_document_layout(sample_pdf)
    assert ir_doc.page_count == 2

    page1 = ir_doc.pages[0]
    assert page1.width == 612.0
    assert page1.height == 792.0

    paragraphs = [b for b in page1.blocks if isinstance(b, ParagraphBlock)]
    images = [b for b in page1.blocks if isinstance(b, ImageBlock)]

    # Heading detection
    assert any(p.heading_level == 1 and "Annual Tech Report" in p.text for p in paragraphs)
    assert any(p.heading_level == 2 and "Executive Overview" in p.text for p in paragraphs)

    # Bullet list detection
    bullet_items = [p for p in paragraphs if p.is_list_item]
    assert len(bullet_items) >= 3
    assert any("Lossless layout" in p.text for p in bullet_items)

    # Image extraction
    assert len(images) >= 1
    assert images[0].image_bytes is not None


def test_pdf_to_txt_conversion(sample_pdf: Path, tmp_path: Path):
    """Test PDF to plain text conversion."""
    out_txt = tmp_path / "exported.txt"
    res = anyconvert.convert(sample_pdf, out_txt)

    assert res.success
    assert res.page_count == 2
    assert out_txt.exists()

    content = out_txt.read_text(encoding="utf-8")
    assert "Annual Tech Report" in content
    assert "Executive Overview" in content
    assert "Lossless layout preservation" in content
    assert "Architecture Details" in content


def test_pdf_to_txt_bytes(sample_pdf: Path):
    """Test in-memory conversion of PDF to plain text."""
    pdf_bytes = sample_pdf.read_bytes()
    txt_bytes = anyconvert.convert_bytes(pdf_bytes, to_format="txt")
    text = txt_bytes.decode("utf-8")
    assert "Annual Tech Report" in text


def test_pdf_to_markdown_conversion(sample_pdf: Path, tmp_path: Path):
    """Test PDF to structured markdown conversion."""
    out_md = tmp_path / "exported.md"
    res = anyconvert.convert(sample_pdf, out_md)

    assert res.success
    assert out_md.exists()

    content = out_md.read_text(encoding="utf-8")
    # Headings formatted with #
    assert "# Annual Tech Report" in content or "#" in content
    # Bullets formatted with -
    assert "- Lossless layout preservation" in content or "Lossless layout preservation" in content
    # Page 2 separated
    assert "Architecture Details" in content


def test_pdf_to_png_conversion(sample_pdf: Path, tmp_path: Path):
    """Test PDF to PNG raster rendering."""
    out_png = tmp_path / "page.png"
    res = anyconvert.convert(sample_pdf, out_png, options=anyconvert.ConversionOptions(page_range="1"))

    assert res.success
    assert out_png.exists()

    # Verify valid PNG header
    header = out_png.read_bytes()[:8]
    assert header == b"\x89PNG\r\n\x1a\n"


def test_pdf_to_png_bytes(sample_pdf: Path):
    """Test in-memory conversion of PDF to PNG."""
    pdf_bytes = sample_pdf.read_bytes()
    png_bytes = anyconvert.convert_bytes(pdf_bytes, to_format="png")
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")


def test_pdf_to_jpeg_conversion(sample_pdf: Path, tmp_path: Path):
    """Test PDF to JPEG conversion."""
    out_jpg = tmp_path / "page.jpeg"
    res = anyconvert.convert(sample_pdf, out_jpg, options=anyconvert.ConversionOptions(page_range="1"))

    assert res.success
    assert out_jpg.exists()
    assert out_jpg.read_bytes().startswith(b"\xff\xd8\xff")


def test_pdf_to_webp_conversion(sample_pdf: Path, tmp_path: Path):
    """Test PDF to WebP conversion."""
    out_webp = tmp_path / "page.webp"
    res = anyconvert.convert(sample_pdf, out_webp, options=anyconvert.ConversionOptions(page_range="1"))

    assert res.success
    assert out_webp.exists()
    data = out_webp.read_bytes()
    assert data.startswith(b"RIFF") and data[8:12] == b"WEBP"


def test_pdf_to_svg_conversion(sample_pdf: Path, tmp_path: Path):
    """Test PDF to SVG vector conversion."""
    out_svg = tmp_path / "page.svg"
    res = anyconvert.convert(sample_pdf, out_svg, options=anyconvert.ConversionOptions(page_range="1"))

    assert res.success
    assert out_svg.exists()
    svg_text = out_svg.read_text(encoding="utf-8")
    assert "<svg" in svg_text and "</svg>" in svg_text


def test_multipage_image_export(sample_pdf: Path, tmp_path: Path):
    """Test that rendering multi-page PDF generates separate numbered image files."""
    out_base = tmp_path / "report.png"
    res = anyconvert.convert(sample_pdf, out_base)

    assert res.success
    assert res.page_count == 2
    rendered_files = res.metadata.get("rendered_files", [])
    assert len(rendered_files) == 2
    for f in rendered_files:
        assert Path(f).exists()
