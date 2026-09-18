"""
Intermediate Representation (IR) data models for anyconvert.
These structures represent the normalized document elements across all input formats.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple, Union


@dataclass
class Point:
    """2D coordinate point."""
    x: float
    y: float


@dataclass
class Rect:
    """2D bounding box (x0, y0, x1, y1)."""
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return max(0.0, self.x1 - self.x0)

    @property
    def height(self) -> float:
        return max(0.0, self.y1 - self.y0)

    @property
    def area(self) -> float:
        return self.width * self.height

    def contains(self, other: "Rect") -> bool:
        """Check if this rect completely encloses another rect."""
        return (
            self.x0 <= other.x0 + 1e-4
            and self.y0 <= other.y0 + 1e-4
            and self.x1 >= other.x1 - 1e-4
            and self.y1 >= other.y1 - 1e-4
        )

    def intersects(self, other: "Rect") -> bool:
        """Check if this rect intersects another rect."""
        return not (
            self.x1 < other.x0 or self.x0 > other.x1 or self.y1 < other.y0 or self.y0 > other.y1
        )

    def union(self, other: "Rect") -> "Rect":
        """Compute the bounding box enclosing both rects."""
        return Rect(
            min(self.x0, other.x0),
            min(self.y0, other.y0),
            max(self.x1, other.x1),
            max(self.y1, other.y1),
        )

    def as_tuple(self) -> Tuple[float, float, float, float]:
        return (self.x0, self.y0, self.x1, self.y1)


@dataclass
class Color:
    """RGBA Color representation."""
    r: int = 0
    g: int = 0
    b: int = 0
    a: float = 1.0

    @classmethod
    def from_hex(cls, hex_str: str) -> "Color":
        hex_clean = hex_str.lstrip("#")
        if len(hex_clean) == 6:
            r = int(hex_clean[0:2], 16)
            g = int(hex_clean[2:4], 16)
            b = int(hex_clean[4:6], 16)
            return cls(r, g, b)
        elif len(hex_clean) == 8:
            r = int(hex_clean[0:2], 16)
            g = int(hex_clean[2:4], 16)
            b = int(hex_clean[4:6], 16)
            a = int(hex_clean[6:8], 16) / 255.0
            return cls(r, g, b, a)
        return cls(0, 0, 0)

    def to_hex(self) -> str:
        return f"#{self.r:02x}{self.g:02x}{self.b:02x}"

    def to_rgb_tuple(self) -> Tuple[int, int, int]:
        return (self.r, self.g, self.b)


@dataclass
class TextRun:
    """A contiguous span of text sharing uniform font styling."""
    text: str
    bbox: Rect
    font_name: str = "sans-serif"
    font_size: float = 11.0
    is_bold: bool = False
    is_italic: bool = False
    is_underline: bool = False
    color: Color = field(default_factory=Color)
    hyperlink_uri: Optional[str] = None


@dataclass
class TextLine:
    """A single line of text comprising one or more TextRuns."""
    runs: List[TextRun] = field(default_factory=list)
    bbox: Rect = field(default_factory=lambda: Rect(0, 0, 0, 0))
    baseline: float = 0.0

    @property
    def text(self) -> str:
        return "".join(run.text for run in self.runs)


@dataclass
class ParagraphBlock:
    """A block of text forming a semantic paragraph or heading."""
    lines: List[TextLine] = field(default_factory=list)
    bbox: Rect = field(default_factory=lambda: Rect(0, 0, 0, 0))
    alignment: Literal["left", "center", "right", "justify"] = "left"
    heading_level: Optional[int] = None  # 1 to 6 if heading, None if body paragraph
    is_list_item: bool = False
    list_bullet: Optional[str] = None
    line_spacing: float = 1.15

    @property
    def text(self) -> str:
        return " ".join(line.text.strip() for line in self.lines if line.text.strip())


@dataclass
class TableCell:
    """A single cell inside a TableBlock."""
    row_idx: int
    col_idx: int
    bbox: Rect
    text: str = ""
    paragraphs: List[ParagraphBlock] = field(default_factory=list)
    row_span: int = 1
    col_span: int = 1
    background_color: Optional[Color] = None
    border_top: bool = True
    border_bottom: bool = True
    border_left: bool = True
    border_right: bool = True


@dataclass
class TableBlock:
    """A detected or parsed table grid."""
    bbox: Rect
    rows: int
    cols: int
    cells: List[TableCell] = field(default_factory=list)

    def get_cell(self, row: int, col: int) -> Optional[TableCell]:
        for cell in self.cells:
            if cell.row_idx == row and cell.col_idx == col:
                return cell
        return None

    def as_matrix(self) -> List[List[str]]:
        """Return the table content as a 2D string matrix."""
        matrix = [["" for _ in range(self.cols)] for _ in range(self.rows)]
        for cell in self.cells:
            if 0 <= cell.row_idx < self.rows and 0 <= cell.col_idx < self.cols:
                matrix[cell.row_idx][cell.col_idx] = cell.text
        return matrix


@dataclass
class ImageBlock:
    """An embedded bitmap image."""
    bbox: Rect
    image_bytes: bytes
    image_format: str = "png"  # png, jpeg, webp, etc.
    width: int = 0
    height: int = 0
    smask_bytes: Optional[bytes] = None


@dataclass
class VectorShapeBlock:
    """A vector shape (line, polygon, rectangle, bezier curve)."""
    bbox: Rect
    shape_type: Literal["line", "rect", "polygon", "curve"] = "rect"
    stroke_color: Optional[Color] = None
    fill_color: Optional[Color] = None
    stroke_width: float = 1.0
    points: List[Point] = field(default_factory=list)


Block = Union[ParagraphBlock, TableBlock, ImageBlock, VectorShapeBlock]


@dataclass
class Hyperlink:
    """A clickable hyperlink within a page."""
    bbox: Rect
    uri: Optional[str] = None
    target_page: Optional[int] = None


@dataclass
class Page:
    """A single page of a document."""
    page_number: int  # 0-indexed
    width: float      # in points (1 pt = 1/72 inch)
    height: float
    rotation: int = 0  # 0, 90, 180, 270
    blocks: List[Block] = field(default_factory=list)
    links: List[Hyperlink] = field(default_factory=list)
    header_margin: float = 36.0
    footer_margin: float = 36.0


@dataclass
class TOCItem:
    """Table of Contents / Outline item."""
    title: str
    page: int
    level: int = 1


@dataclass
class Document:
    """A full multi-page document in Intermediate Representation."""
    pages: List[Page] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    toc: List[TOCItem] = field(default_factory=list)

    @property
    def page_count(self) -> int:
        return len(self.pages)
