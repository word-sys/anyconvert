"""Line-to-paragraph grouping, alignment detection, and indentation metrics.

Implements structural heuristics to synthesize coherent paragraphs from clustered
text lines, computing text alignment, line spacing, margins, and indentations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional, Sequence

from anyconvert.common.geometry import BoundingBox
from anyconvert.layout.cluster import TextLine


class Alignment(Enum):
    """Paragraph horizontal text alignment."""

    LEFT = auto()
    CENTER = auto()
    RIGHT = auto()
    JUSTIFIED = auto()


@dataclass(slots=True)
class ParagraphCluster:
    """Represents a coherent synthesized paragraph of text lines."""

    lines: List[TextLine]
    bbox: BoundingBox
    alignment: Alignment = Alignment.LEFT
    line_spacing: float = 1.15
    space_before: float = 0.0
    space_after: float = 0.0
    indent_left: float = 0.0
    indent_right: float = 0.0
    indent_first_line: float = 0.0
    heading_level: Optional[int] = None
    list_marker: Optional[str] = None
    list_level: int = 0

    @property
    def text(self) -> str:
        """Joined plaintext of all lines in paragraph."""
        return " ".join(line.text for line in self.lines if line.text)

    @property
    def font_name(self) -> str:
        """Dominant font name of the paragraph."""
        return self.lines[0].font_name if self.lines else ""

    @property
    def font_size(self) -> float:
        """Dominant font size of the paragraph."""
        if not self.lines:
            return 12.0
        total_len = sum(len(l.text) for l in self.lines)
        if total_len == 0:
            return self.lines[0].font_size
        return sum(l.font_size * len(l.text) for l in self.lines) / total_len

    @property
    def is_bold(self) -> bool:
        """True if dominant style is bold."""
        return any(l.is_bold for l in self.lines)

    @property
    def is_italic(self) -> bool:
        """True if dominant style is italic."""
        return any(l.is_italic for l in self.lines)


def detect_alignment(
    lines: Sequence[TextLine],
    container_x0: float,
    container_x1: float,
    tolerance: float = 4.0,
) -> Alignment:
    """Determine paragraph text alignment relative to container margins.

    Args:
        lines: Sequence of TextLine objects in the paragraph.
        container_x0: Left boundary coordinate of the enclosing column or block.
        container_x1: Right boundary coordinate of the enclosing column or block.
        tolerance: Spatial tolerance for margin matching in points.

    Returns:
        Detected Alignment enum.
    """
    if not lines:
        return Alignment.LEFT

    if len(lines) == 1:
        line = lines[0]
        c_width = container_x1 - container_x0
        # Check center alignment
        line_center = (line.bbox.x0 + line.bbox.x1) / 2.0
        container_center = (container_x0 + container_x1) / 2.0
        if abs(line_center - container_center) <= tolerance:
            return Alignment.CENTER

        # Check right alignment
        if abs(line.bbox.x1 - container_x1) <= tolerance and line.bbox.x0 > container_x0 + tolerance * 2:
            return Alignment.RIGHT

        # Default single line to left
        return Alignment.LEFT

    # Multi-line alignment analysis
    # 1. Justified: body lines (all except possibly the last line) span full container width
    if len(lines) >= 2:
        body_lines = lines[:-1]
        all_left_align_container = all(abs(l.bbox.x0 - container_x0) <= tolerance for l in lines)
        body_right_align_container = all(abs(l.bbox.x1 - container_x1) <= tolerance for l in body_lines)
        if all_left_align_container and body_right_align_container:
            return Alignment.JUSTIFIED

    # 2. Centered: lines are centered relative to container center
    container_center = (container_x0 + container_x1) / 2.0
    centers = [(l.bbox.x0 + l.bbox.x1) / 2.0 for l in lines]
    all_centered = all(abs(c - container_center) <= tolerance for c in centers)
    if all_centered:
        return Alignment.CENTER

    # 3. Right-aligned: all lines share right margin
    all_right_aligned = all(abs(l.bbox.x1 - container_x1) <= tolerance for l in lines)
    if all_right_aligned:
        return Alignment.RIGHT

    return Alignment.LEFT



def cluster_lines_to_paragraphs(
    lines: Sequence[TextLine],
    container_bbox: Optional[BoundingBox] = None,
    max_line_gap_factor: float = 1.6,
) -> List[ParagraphCluster]:
    """Group consecutive text lines into paragraphs and calculate formatting metrics.

    Args:
        lines: Sequence of TextLine objects sorted top-to-bottom.
        container_bbox: Optional bounding box of the enclosing column or block.
        max_line_gap_factor: Threshold factor above median line gap triggering a paragraph break.

    Returns:
        List of ParagraphCluster instances with computed alignment and indentations.
    """
    if not lines:
        return []

    # Sort lines vertically
    sorted_lines = sorted(lines, key=lambda l: (round(l.bbox.y0, 1), l.bbox.x0))

    if len(sorted_lines) == 1:
        line = sorted_lines[0]
        c_x0 = container_bbox.x0 if container_bbox else line.bbox.x0
        c_x1 = container_bbox.x1 if container_bbox else line.bbox.x1
        align = detect_alignment([line], c_x0, c_x1)
        return [
            ParagraphCluster(
                lines=[line],
                bbox=line.bbox,
                alignment=align,
                line_spacing=1.15,
                indent_left=max(0.0, line.bbox.x0 - c_x0),
                indent_right=max(0.0, c_x1 - line.bbox.x1),
            )
        ]

    # Compute inter-line vertical gaps to find typical line spacing
    gaps: List[float] = []
    for i in range(len(sorted_lines) - 1):
        gap = sorted_lines[i + 1].bbox.y0 - sorted_lines[i].bbox.y1
        if gap >= 0.0:
            gaps.append(gap)

    median_gap = sorted(gaps)[len(gaps) // 2] if gaps else 4.0
    # Safe break threshold
    break_gap_threshold = max(8.0, median_gap * max_line_gap_factor)

    # Group lines into paragraph buckets
    para_buckets: List[List[TextLine]] = [[sorted_lines[0]]]

    for i in range(len(sorted_lines) - 1):
        curr_line = sorted_lines[i]
        next_line = sorted_lines[i + 1]
        gap = next_line.bbox.y0 - curr_line.bbox.y1

        # Criteria for paragraph break:
        # 1. Vertical gap significantly larger than median inter-line spacing
        large_gap = gap > break_gap_threshold

        # 2. Substantial font size change (e.g. heading following paragraph)
        font_change = abs(next_line.font_size - curr_line.font_size) > 1.5

        # 3. First-line indent on next line (traditional paragraph indent)
        indent_delta = next_line.bbox.x0 - curr_line.bbox.x0
        indent_break = indent_delta > 10.0 and len(para_buckets[-1]) >= 1

        if large_gap or font_change or indent_break:
            para_buckets.append([next_line])
        else:
            para_buckets[-1].append(next_line)

    # Determine container bounds
    all_x0 = min(l.bbox.x0 for l in sorted_lines)
    all_x1 = max(l.bbox.x1 for l in sorted_lines)
    cont_x0 = container_bbox.x0 if container_bbox is not None else all_x0
    cont_x1 = container_bbox.x1 if container_bbox is not None else all_x1

    paragraphs: List[ParagraphCluster] = []
    for p_idx, p_lines in enumerate(para_buckets):
        p_bbox = p_lines[0].bbox
        for l in p_lines[1:]:
            p_bbox = p_bbox.union(l.bbox)

        align = detect_alignment(p_lines, cont_x0, cont_x1)

        # Indentations
        indent_l = max(0.0, min(l.bbox.x0 for l in p_lines) - cont_x0)
        indent_r = max(0.0, cont_x1 - max(l.bbox.x1 for l in p_lines))
        first_line_indent = (
            p_lines[0].bbox.x0 - p_lines[1].bbox.x0 if len(p_lines) > 1 else 0.0
        )

        # Spacing before and after
        space_bef = 0.0
        if p_idx > 0:
            prev_p_bottom = paragraphs[p_idx - 1].bbox.y1
            space_bef = max(0.0, p_bbox.y0 - prev_p_bottom)

        space_aft = 0.0
        if p_idx < len(para_buckets) - 1:
            next_p_top = para_buckets[p_idx + 1][0].bbox.y0
            space_aft = max(0.0, next_p_top - p_bbox.y1)

        # Line spacing ratio
        line_spacing_val = 1.15
        if len(p_lines) > 1:
            line_height = sum(l.height for l in p_lines) / len(p_lines)
            if line_height > 0:
                avg_pitch = (p_lines[-1].bbox.y0 - p_lines[0].bbox.y0) / (len(p_lines) - 1)
                line_spacing_val = max(1.0, round(avg_pitch / line_height, 2))

        paragraphs.append(
            ParagraphCluster(
                lines=p_lines,
                bbox=p_bbox,
                alignment=align,
                line_spacing=line_spacing_val,
                space_before=space_bef,
                space_after=space_aft,
                indent_left=indent_l,
                indent_right=indent_r,
                indent_first_line=first_line_indent,
            )
        )

    return paragraphs


__all__ = [
    "Alignment",
    "ParagraphCluster",
    "detect_alignment",
    "cluster_lines_to_paragraphs",
]
