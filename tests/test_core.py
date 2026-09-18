"""
Unit tests for anyconvert core architecture, models, options, and registry.
"""

from pathlib import Path
import pytest

from anyconvert.core.exceptions import (
    AnyConvertError,
    CancelledError,
    FormatDetectionError,
    MissingDependencyError,
    UnsupportedFormatError,
    ValidationError,
)
from anyconvert.core.models import (
    Color,
    Document,
    ImageBlock,
    Page,
    ParagraphBlock,
    Point,
    Rect,
    TableBlock,
    TableCell,
    TextLine,
    TextRun,
)
from anyconvert.core.options import (
    CancellationToken,
    ConversionOptions,
    ConversionResult,
)
from anyconvert.core.registry import (
    ConverterRegistry,
    detect_format,
    detect_format_from_bytes,
    normalize_format,
)
from anyconvert.converters.base import BaseConverter
from anyconvert.cli.main import main


# ---------------------------------------------------------------------------
# Test Intermediate Representation (IR) Models
# ---------------------------------------------------------------------------

def test_rect_geometry():
    r1 = Rect(0, 0, 100, 200)
    assert r1.width == 100
    assert r1.height == 200
    assert r1.area == 20000

    r2 = Rect(10, 10, 50, 50)
    assert r1.contains(r2)
    assert not r2.contains(r1)
    assert r1.intersects(r2)

    r3 = Rect(150, 150, 200, 200)
    assert not r1.intersects(r3)

    union_r = r1.union(r3)
    assert union_r.x0 == 0
    assert union_r.y0 == 0
    assert union_r.x1 == 200
    assert union_r.y1 == 200


def test_color_conversions():
    c1 = Color.from_hex("#ff8000")
    assert c1.r == 255
    assert c1.g == 128
    assert c1.b == 0
    assert c1.to_hex() == "#ff8000"

    c2 = Color.from_hex("00ff00")
    assert c2.to_rgb_tuple() == (0, 255, 0)


def test_document_and_page_hierarchy():
    doc = Document()
    page = Page(page_number=0, width=612.0, height=792.0)

    run1 = TextRun(
        text="Hello ",
        bbox=Rect(50, 50, 100, 65),
        font_name="Helvetica",
        font_size=12.0,
        is_bold=True,
    )
    run2 = TextRun(
        text="World",
        bbox=Rect(100, 50, 150, 65),
        font_name="Helvetica",
        font_size=12.0,
    )
    line = TextLine(runs=[run1, run2], bbox=Rect(50, 50, 150, 65))
    para = ParagraphBlock(lines=[line], bbox=Rect(50, 50, 150, 65))

    page.blocks.append(para)
    doc.pages.append(page)

    assert doc.page_count == 1
    assert para.text == "Hello World"
    assert len(page.blocks) == 1


def test_table_block():
    cell_0_0 = TableCell(row_idx=0, col_idx=0, bbox=Rect(0, 0, 50, 20), text="Name")
    cell_0_1 = TableCell(row_idx=0, col_idx=1, bbox=Rect(50, 0, 100, 20), text="Age")
    cell_1_0 = TableCell(row_idx=1, col_idx=0, bbox=Rect(0, 20, 50, 40), text="Alice")
    cell_1_1 = TableCell(row_idx=1, col_idx=1, bbox=Rect(50, 20, 100, 40), text="30")

    table = TableBlock(
        bbox=Rect(0, 0, 100, 40),
        rows=2,
        cols=2,
        cells=[cell_0_0, cell_0_1, cell_1_0, cell_1_1],
    )

    assert table.get_cell(0, 0).text == "Name"
    assert table.get_cell(1, 1).text == "30"
    assert table.get_cell(2, 2) is None

    matrix = table.as_matrix()
    assert matrix == [["Name", "Age"], ["Alice", "30"]]


# ---------------------------------------------------------------------------
# Test Options & Cancellation
# ---------------------------------------------------------------------------

def test_page_range_parsing():
    opts = ConversionOptions(page_range="1-3, 5")
    pages = opts.parse_pages(total_pages=10)
    assert pages == [0, 1, 2, 4]

    # All pages if None
    opts_all = ConversionOptions(page_range=None)
    assert opts_all.parse_pages(5) == [0, 1, 2, 3, 4]

    # Out of bounds ignored gracefully
    opts_boundary = ConversionOptions(page_range="1, 99")
    assert opts_boundary.parse_pages(5) == [0]

    # Invalid string raises ValidationError
    opts_invalid = ConversionOptions(page_range="abc")
    with pytest.raises(ValidationError):
        opts_invalid.parse_pages(5)


def test_cancellation_token():
    token = CancellationToken()
    assert not token.is_cancelled
    token.check_cancelled()  # Should not raise

    token.cancel()
    assert token.is_cancelled
    with pytest.raises(CancelledError):
        token.check_cancelled()


def test_conversion_result_write_to(tmp_path):
    res = ConversionResult(success=True, output_bytes=b"sample binary content")
    out_file = tmp_path / "out.bin"
    res.write_to(out_file)
    assert out_file.read_bytes() == b"sample binary content"
    assert res.output_path == str(out_file)


# ---------------------------------------------------------------------------
# Test Registry & Converter Routing
# ---------------------------------------------------------------------------

class DummyPdfToDocxConverter(BaseConverter):
    source_format = "pdf"
    target_format = "docx"

    def convert_file(self, source_path, target_path, options=None):
        return ConversionResult(success=True, page_count=1)

    def convert_bytes(self, data, options=None):
        return b"dummy-docx-bytes"


def test_registry_registration_and_lookup():
    registry = ConverterRegistry()
    registry.register(DummyPdfToDocxConverter)

    assert registry.has_converter("pdf", "docx")
    assert registry.has_converter("PDF", "DOCX")  # Case-insensitive
    assert not registry.has_converter("pdf", "pptx")

    converter = registry.get_converter("pdf", "docx")
    assert isinstance(converter, DummyPdfToDocxConverter)

    conversions = registry.supported_conversions()
    assert conversions == {"pdf": ["docx"]}


def test_unsupported_format_error():
    registry = ConverterRegistry()
    with pytest.raises(UnsupportedFormatError) as exc_info:
        registry.get_converter("pdf", "xyz")
    assert "xyz" in str(exc_info.value)


def test_missing_dependency_error():
    err = MissingDependencyError("python-docx", "docx")
    assert "pip install" in str(err)
    assert "docx" in str(err)


# ---------------------------------------------------------------------------
# Test Format Normalization & Detection
# ---------------------------------------------------------------------------

def test_format_normalization():
    assert normalize_format(".PDF") == "pdf"
    assert normalize_format("JPG") == "jpeg"
    assert normalize_format("WORD") == "docx"
    assert normalize_format("PPTX") == "pptx"


def test_format_detection():
    assert detect_format_from_bytes(b"%PDF-1.7") == "pdf"
    assert detect_format_from_bytes(b"\x89PNG\r\n\x1a\n") == "png"
    assert detect_format_from_bytes(b"\xff\xd8\xff\xe0") == "jpeg"
    assert detect_format("my_document.pdf") == "pdf"
    assert detect_format("presentation.pptx") == "pptx"
    assert detect_format("data.csv") == "csv"

    assert detect_format_from_bytes(b"") is None

    with pytest.raises(FormatDetectionError):
        detect_format(b"\x00\x01\x02\x03\x04\x05")

    with pytest.raises(FormatDetectionError):
        detect_format("unknown_file_without_ext")


# ---------------------------------------------------------------------------
# Test CLI
# ---------------------------------------------------------------------------

def test_cli_version(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0
    captured = capsys.readouterr()
    assert "anyconvert 0.1.0" in captured.out


def test_cli_list_formats(capsys):
    ret = main(["--list-formats"])
    assert ret == 0
