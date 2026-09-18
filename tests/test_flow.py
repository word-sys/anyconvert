"""
Unit and integration tests for Part 6: High-Fidelity Paragraph Flow & Line Reconstruction.
"""

from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile
import pytest

import pymupdf
import anyconvert
from anyconvert.analysis.layout import (
    _build_paragraph,
    compute_page_body_font_size,
    extract_document_layout,
    sort_page_blocks,
)
from anyconvert.core.models import (
    Document,
    ImageBlock,
    Page,
    ParagraphBlock,
    Rect,
    TextLine,
    TextRun,
)
from anyconvert.core.options import ConversionOptions
from anyconvert.synthesizers.docx import DocxSynthesizer
from anyconvert.synthesizers.odt import OdtSynthesizer


def test_interline_spacing_docx():
    """Verify that lines within a paragraph without boundary whitespace have a space inserted in DOCX."""
    line1 = TextLine(
        runs=[TextRun(text="Word-Sys PDF Editor,", bbox=Rect(10, 10, 100, 20))],
        bbox=Rect(10, 10, 100, 20),
    )
    line2 = TextLine(
        runs=[TextRun(text="this is a test", bbox=Rect(10, 25, 100, 35))],
        bbox=Rect(10, 25, 100, 35),
    )
    para = ParagraphBlock(lines=[line1, line2], bbox=Rect(10, 10, 100, 35))
    doc = Document(pages=[Page(page_number=0, width=595, height=842, blocks=[para])])

    synth = DocxSynthesizer(doc, ConversionOptions())
    docx_bytes = synth.build_bytes()

    with zipfile.ZipFile(pytest.importorskip("io").BytesIO(docx_bytes)) as zf:
        xml_str = zf.read("word/document.xml").decode("utf-8")
        root = ET.fromstring(xml_str)
        w_ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        p = root.find(".//w:p", w_ns)
        assert p is not None
        runs_text = "".join(t.text for t in p.findall(".//w:t", w_ns) if t.text)
        assert "Editor, this is" in runs_text
        assert "Editor,this is" not in runs_text


def test_interline_spacing_odt():
    """Verify that lines within a paragraph without boundary whitespace have a space inserted in ODT."""
    line1 = TextLine(
        runs=[TextRun(text="Word-Sys PDF Editor,", bbox=Rect(10, 10, 100, 20))],
        bbox=Rect(10, 10, 100, 20),
    )
    line2 = TextLine(
        runs=[TextRun(text="this is a test", bbox=Rect(10, 25, 100, 35))],
        bbox=Rect(10, 25, 100, 35),
    )
    para = ParagraphBlock(lines=[line1, line2], bbox=Rect(10, 10, 100, 35))
    doc = Document(pages=[Page(page_number=0, width=595, height=842, blocks=[para])])

    synth = OdtSynthesizer(doc, ConversionOptions())
    odt_bytes = synth.build_bytes()

    with zipfile.ZipFile(pytest.importorskip("io").BytesIO(odt_bytes)) as zf:
        xml_str = zf.read("content.xml").decode("utf-8")
        root = ET.fromstring(xml_str)
        p = root.find(".//{urn:oasis:names:tc:opendocument:xmlns:text:1.0}p")
        assert p is not None
        rendered = []
        for elem in p.iter():
            if elem.tag.endswith("s"):
                rendered.append(" ")
            elif elem.text:
                rendered.append(elem.text)
        full_text = "".join(rendered)
        assert "Editor, this is" in full_text
        assert "Editor,this is" not in full_text


def test_interline_hyphen_preservation():
    """Verify that lines ending with a hyphen do not get an extra space in DOCX."""
    line1 = TextLine(
        runs=[TextRun(text="multi-", bbox=Rect(10, 10, 50, 20))],
        bbox=Rect(10, 10, 50, 20),
    )
    line2 = TextLine(
        runs=[TextRun(text="line", bbox=Rect(10, 25, 40, 35))],
        bbox=Rect(10, 25, 40, 35),
    )
    para = ParagraphBlock(lines=[line1, line2], bbox=Rect(10, 10, 50, 35))
    doc = Document(pages=[Page(page_number=0, width=595, height=842, blocks=[para])])

    synth = DocxSynthesizer(doc, ConversionOptions())
    docx_bytes = synth.build_bytes()

    with zipfile.ZipFile(pytest.importorskip("io").BytesIO(docx_bytes)) as zf:
        xml_str = zf.read("word/document.xml").decode("utf-8")
        root = ET.fromstring(xml_str)
        w_ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        p = root.find(".//w:p", w_ns)
        runs_text = "".join(t.text for t in p.findall(".//w:t", w_ns) if t.text)
        assert "multi-line" in runs_text


def test_page_body_font_size_false_headings():
    """Verify that page-level body font size prevents uniform large text from being false headings."""
    page_dict = {
        "blocks": [
            {
                "type": 0,
                "lines": [
                    {
                        "spans": [
                            {"text": "Line one of large body text for thermal receipt. ", "size": 29.0},
                            {"text": "Line two of large body text for thermal receipt. ", "size": 29.0},
                            {"text": "Line three of large body text for thermal receipt.", "size": 29.0},
                        ]
                    }
                ],
            }
        ]
    }
    detected_size = compute_page_body_font_size(page_dict, fallback=11.0)
    assert detected_size == 29.0

    line = TextLine(
        runs=[TextRun(text="Short sentence on receipt", font_size=29.0, bbox=Rect(10, 10, 200, 40))],
        bbox=Rect(10, 10, 200, 40),
    )
    para = _build_paragraph([line], ConversionOptions(detect_headings=True), body_font_size=detected_size)
    assert para is not None
    assert para.heading_level is None


def test_band_aware_block_sorting():
    """Verify that side-by-side elements (e.g. label and image) maintain left-to-right order."""
    label_block = ParagraphBlock(
        lines=[TextLine(runs=[TextRun(text="Image:", bbox=Rect(10, 100, 60, 120))], bbox=Rect(10, 100, 60, 120))],
        bbox=Rect(10, 100, 60, 120),
    )
    # Image has top at 90 (above label top at 100), but is to the right (x0=120)
    img_block = ImageBlock(
        bbox=Rect(120, 90, 300, 250),
        image_bytes=b"",
        image_format="png",
        width=180,
        height=160,
    )

    # Pass in reversed order (image before label)
    sorted_blocks = sort_page_blocks([img_block, label_block])
    assert sorted_blocks[0] is label_block
    assert sorted_blocks[1] is img_block
