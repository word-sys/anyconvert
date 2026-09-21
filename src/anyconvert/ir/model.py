"""Universal Document Intermediate Representation (DIR) object models.

Provides strictly typed, serialization-agnostic dataclasses representing document
structure, text runs, paragraphs, tables, images, shapes, headers/footers, and pages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Union

from anyconvert.common.color import Color
from anyconvert.common.geometry import BoundingBox


class Alignment(Enum):
    """Horizontal text or block alignment."""

    LEFT = auto()
    CENTER = auto()
    RIGHT = auto()
    JUSTIFIED = auto()


class HeadingLevel(Enum):
    """Standard hierarchical heading levels."""

    H1 = 1
    H2 = 2
    H3 = 3
    H4 = 4
    H5 = 5
    H6 = 6


@dataclass(slots=True)
class TextRun:
    """An inline sequence of text sharing uniform typographic and styling attributes."""

    text: str
    font_name: str
    font_size: float
    color: Color
    is_bold: bool = False
    is_italic: bool = False
    is_underline: bool = False
    is_strikethrough: bool = False
    tracking: float = 0.0
    baseline_offset: float = 0.0
    bbox: Optional[BoundingBox] = None


@dataclass(slots=True)
class Paragraph:
    """A structural block of text composed of styled inline text runs."""

    runs: List[TextRun] = field(default_factory=list)
    alignment: Alignment = Alignment.LEFT
    heading_level: Optional[HeadingLevel] = None
    line_spacing: float = 1.15
    space_before: float = 0.0
    space_after: float = 0.0
    indent_left: float = 0.0
    indent_right: float = 0.0
    indent_first_line: float = 0.0
    list_marker: Optional[str] = None
    list_level: int = 0
    bbox: Optional[BoundingBox] = None

    @property
    def text(self) -> str:
        """Aggregated plaintext of all runs."""
        return "".join(r.text for r in self.runs)


@dataclass(slots=True)
class Border:
    """Styling specification for a table or box border."""

    style: str = "solid"  # 'solid', 'dashed', 'dotted', 'none'
    width: float = 1.0
    color: Color = field(default_factory=lambda: Color(0, 0, 0))


@dataclass(slots=True)
class TableCell:
    """A single cell within a table grid, supporting nested content and spanning."""

    content: List[BlockNode] = field(default_factory=list)
    col_span: int = 1
    row_span: int = 1
    width: float = 0.0
    height: float = 0.0
    background_color: Optional[Color] = None
    borders: Dict[str, Border] = field(default_factory=dict)  # 'top', 'bottom', 'left', 'right'


@dataclass(slots=True)
class TableRow:
    """A horizontal row of cells within a table."""

    cells: List[TableCell] = field(default_factory=list)
    height: float = 0.0
    is_header: bool = False


@dataclass(slots=True)
class Table:
    """A 2D structured grid of rows, columns, and cells."""

    rows: List[TableRow] = field(default_factory=list)
    col_widths: List[float] = field(default_factory=list)
    alignment: Alignment = Alignment.CENTER
    bbox: Optional[BoundingBox] = None


@dataclass(slots=True)
class ImageBlock:
    """A raster image block embedded in presentation or flow layout."""

    png_bytes: bytes
    bbox: BoundingBox
    alt_text: str = ""
    rotation: float = 0.0
    format: str = "png"


@dataclass(slots=True)
class VectorBlock:
    """A vector graphic shape or path in presentation layout."""

    svg_path: str
    bbox: BoundingBox
    fill_color: Optional[Color] = None
    stroke_color: Optional[Color] = None
    stroke_width: float = 1.0


BlockNode = Union[Paragraph, Table, ImageBlock, VectorBlock]


@dataclass(slots=True)
class PageHeaderFooter:
    """A running marginal header or footer region."""

    content: List[Paragraph] = field(default_factory=list)
    is_footer: bool = False


@dataclass(slots=True)
class DocumentPage:
    """A single document page containing layout blocks and marginal headers/footers."""

    page_number: int
    width: float   # Points (1 pt = 1/72 inch)
    height: float  # Points
    margin_top: float = 72.0
    margin_bottom: float = 72.0
    margin_left: float = 72.0
    margin_right: float = 72.0
    blocks: List[BlockNode] = field(default_factory=list)
    header: Optional[PageHeaderFooter] = None
    footer: Optional[PageHeaderFooter] = None


@dataclass(slots=True)
class DocumentIR:
    """Root container representing the entire document in Intermediate Representation."""

    pages: List[DocumentPage] = field(default_factory=list)
    metadata: Dict[str, str] = field(default_factory=dict)


__all__ = [
    "Alignment",
    "HeadingLevel",
    "TextRun",
    "Paragraph",
    "Border",
    "TableCell",
    "TableRow",
    "Table",
    "ImageBlock",
    "VectorBlock",
    "BlockNode",
    "PageHeaderFooter",
    "DocumentPage",
    "DocumentIR",
]
