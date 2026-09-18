"""
Shared test fixtures for anyconvert tests.
"""

import io
from pathlib import Path
from PIL import Image
import pymupdf
import pytest


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """Synthetic multi-page PDF fixture with headings, styles, lists, links, and an image."""
    pdf_path = tmp_path / "sample_doc.pdf"
    doc = pymupdf.open()

    # Page 1
    page1 = doc.new_page(width=612, height=792)
    page1.insert_text((72, 72), "Annual Tech Report", fontsize=24, fontname="helv")
    page1.insert_text((72, 110), "Executive Overview", fontsize=16, fontname="helv")
    page1.insert_text(
        (72, 150),
        "This is an introductory paragraph describing our next-generation conversion engine.",
        fontsize=11,
        fontname="helv",
    )
    page1.insert_text((72, 190), "• Lossless layout preservation", fontsize=11, fontname="helv")
    page1.insert_text((72, 210), "• High-DPI image rasterization", fontsize=11, fontname="helv")
    page1.insert_text((72, 230), "• Pure Python wheel distribution", fontsize=11, fontname="helv")

    link_rect = pymupdf.Rect(72, 260, 250, 275)
    page1.insert_text((72, 270), "Visit our Project Repository", fontsize=11, fontname="helv")
    page1.insert_link({
        "kind": pymupdf.LINK_URI,
        "from": link_rect,
        "uri": "https://github.com/word-sys/anyconvert",
    })

    test_img = Image.new("RGBA", (100, 100), color=(255, 0, 0, 128))
    img_buf = io.BytesIO()
    test_img.save(img_buf, format="PNG")
    page1.insert_image(pymupdf.Rect(72, 300, 172, 400), stream=img_buf.getvalue())

    # Page 2
    page2 = doc.new_page(width=612, height=792)
    page2.insert_text((72, 72), "Architecture Details", fontsize=18, fontname="helv")
    page2.insert_text((72, 110), "Page two contains extended structural specifications.", fontsize=11, fontname="helv")

    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


@pytest.fixture
def table_pdf(tmp_path: Path) -> Path:
    """Synthetic PDF with a 3x3 bordered table and paragraph text."""
    pdf_path = tmp_path / "table_doc.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=500, height=500)

    page.insert_text((50, 40), "Product Inventory Table", fontsize=16)

    x_coords = [50, 150, 250, 350]
    y_coords = [70, 100, 130, 160]

    for y in y_coords:
        page.draw_line((x_coords[0], y), (x_coords[-1], y))

    for x in x_coords:
        page.draw_line((x, y_coords[0]), (x, y_coords[-1]))

    data = [
        ["Item", "Qty", "Price"],
        ["Widget", "5", "$10.00"],
        ["Gadget", "2", "$25.00"],
    ]
    for r_idx, row in enumerate(data):
        y_text = y_coords[r_idx] + 20
        for c_idx, val in enumerate(row):
            x_text = x_coords[c_idx] + 10
            page.insert_text((x_text, y_text), val, fontsize=10)

    page.insert_text((50, 200), "End of Inventory Report.", fontsize=11)

    doc.save(str(pdf_path))
    doc.close()
    return pdf_path
