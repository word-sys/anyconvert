"""Hierarchical text clustering heuristics for PDF layout analysis.

Implements character-to-word and word-to-line clustering based on font metric thresholds,
spatial baseline alignments, and whitespace gaps (ISO 32000-1 / document analysis heuristics).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from anyconvert.common.color import Color
from anyconvert.common.geometry import BoundingBox, Point
from anyconvert.layout.spatial import normalize_bbox_pdf_to_doc, normalize_point_pdf_to_doc
from anyconvert.pdf.content.interpreter import TextElement


@dataclass(slots=True)
class TextWord:
    """Represents a coherent word composed of one or more adjacent glyph elements."""

    text: str
    bbox: BoundingBox
    baseline_y: float
    font_name: str
    font_size: float
    color: Color
    is_bold: bool = False
    is_italic: bool = False
    elements: List[TextElement] = field(default_factory=list)

    @property
    def width(self) -> float:
        """Horizontal width of the word."""
        return self.bbox.width

    @property
    def height(self) -> float:
        """Vertical height of the word."""
        return self.bbox.height


@dataclass(slots=True)
class TextLine:
    """Represents a horizontal line of clustered text words."""

    words: List[TextWord]
    bbox: BoundingBox
    baseline_y: float
    text: str
    font_name: str
    font_size: float
    color: Color
    is_bold: bool = False
    is_italic: bool = False

    @property
    def width(self) -> float:
        """Horizontal width of the line."""
        return self.bbox.width

    @property
    def height(self) -> float:
        """Vertical height of the line."""
        return self.bbox.height


def cluster_characters_to_words(
    elements: Sequence[TextElement],
    page_height: Optional[float] = None,
    space_width_factor: float = 0.28,
) -> List[TextWord]:
    """Cluster raw text elements into words using geometric adjacency and font metrics.

    Args:
        elements: Sequence of TextElement objects from the content interpreter.
        page_height: If provided, transforms PDF coordinates (bottom-left) to document space (top-left).
        space_width_factor: Threshold factor of font size determining word breaks (default 0.28).

    Returns:
        List of TextWord objects ordered by reading position.
    """
    if not elements:
        return []

    # 1. Normalize coordinates to document presentation space if page_height is supplied
    normalized_elements: List[Tuple[TextElement, BoundingBox, float]] = []
    for el in elements:
        if not el.text:
            continue
        if page_height is not None:
            norm_bbox = normalize_bbox_pdf_to_doc(el.bbox, page_height)
            norm_origin_y = page_height - el.origin.y
        else:
            norm_bbox = el.bbox.normalized()
            norm_origin_y = el.origin.y
        normalized_elements.append((el, norm_bbox, norm_origin_y))

    if not normalized_elements:
        return []

    # 2. Decompose elements that contain embedded whitespace (e.g. "(Hello World)" from single Tj)
    atomic_tokens: List[Tuple[str, BoundingBox, float, TextElement]] = []
    for el, bbox, baseline_y in normalized_elements:
        raw_text = el.text
        if " " in raw_text or "\t" in raw_text:
            # Tokenize preserving relative bounding boxes
            tokens = re.split(r"(\s+)", raw_text)
            total_chars = max(1, len(raw_text))
            char_w = bbox.width / total_chars
            curr_x = bbox.x0

            for tok in tokens:
                tok_len = len(tok)
                tok_w = tok_len * char_w
                tok_bbox = BoundingBox(curr_x, bbox.y0, curr_x + tok_w, bbox.y1)
                curr_x += tok_w

                if not tok.isspace() and tok:
                    atomic_tokens.append((tok, tok_bbox, baseline_y, el))
        else:
            atomic_tokens.append((raw_text, bbox, baseline_y, el))

    if not atomic_tokens:
        return []

    # 3. Sort atomic tokens top-to-bottom, left-to-right
    # Bucket into horizontal lines using baseline proximity
    def sort_key(item: Tuple[str, BoundingBox, float, TextElement]) -> Tuple[float, float]:
        _, b, base, _ = item
        return (round(base, 1), b.x0)

    atomic_tokens.sort(key=sort_key)

    # 4. Group adjacent characters/tokens into words
    words: List[TextWord] = []
    curr_text: List[str] = []
    curr_bbox: Optional[BoundingBox] = None
    curr_baseline: float = 0.0
    curr_elements: List[TextElement] = []
    curr_font: str = ""
    curr_size: float = 0.0
    curr_color: Optional[Color] = None
    curr_bold: bool = False
    curr_italic: bool = False

    for tok_text, tok_bbox, tok_base, el in atomic_tokens:
        if not curr_text:
            # Start first word
            curr_text = [tok_text]
            curr_bbox = tok_bbox
            curr_baseline = tok_base
            curr_elements = [el]
            curr_font = el.font_name
            curr_size = el.font_size
            curr_color = el.color
            curr_bold = el.is_bold
            curr_italic = el.is_italic
            continue

        assert curr_bbox is not None
        # Check merge criteria:
        # a. Baseline alignment
        baseline_delta = abs(tok_base - curr_baseline)
        max_size = max(curr_size, el.font_size, 1.0)
        same_line = baseline_delta <= 0.35 * max_size

        # b. Horizontal proximity
        h_gap = tok_bbox.x0 - curr_bbox.x1
        space_threshold = max_size * space_width_factor
        close_enough = -0.2 * max_size <= h_gap <= space_threshold

        # c. Compatible style
        same_style = (
            el.font_name == curr_font
            and abs(el.font_size - curr_size) <= 0.5
            and el.is_bold == curr_bold
            and el.is_italic == curr_italic
        )

        if same_line and close_enough and same_style:
            # Append to current word
            curr_text.append(tok_text)
            curr_bbox = curr_bbox.union(tok_bbox)
            curr_baseline = (curr_baseline * len(curr_elements) + tok_base) / (len(curr_elements) + 1)
            curr_elements.append(el)
        else:
            # Flush completed word
            words.append(
                TextWord(
                    text="".join(curr_text),
                    bbox=curr_bbox,
                    baseline_y=curr_baseline,
                    font_name=curr_font,
                    font_size=curr_size,
                    color=curr_color if curr_color is not None else el.color,
                    is_bold=curr_bold,
                    is_italic=curr_italic,
                    elements=curr_elements,
                )
            )
            # Start new word
            curr_text = [tok_text]
            curr_bbox = tok_bbox
            curr_baseline = tok_base
            curr_elements = [el]
            curr_font = el.font_name
            curr_size = el.font_size
            curr_color = el.color
            curr_bold = el.is_bold
            curr_italic = el.is_italic

    # Flush last word
    if curr_text and curr_bbox is not None:
        words.append(
            TextWord(
                text="".join(curr_text),
                bbox=curr_bbox,
                baseline_y=curr_baseline,
                font_name=curr_font,
                font_size=curr_size,
                color=curr_color if curr_color is not None else Color.black(),
                is_bold=curr_bold,
                is_italic=curr_italic,
                elements=curr_elements,
            )
        )

    return words


def cluster_words_to_lines(
    words: Sequence[TextWord],
    vertical_overlap_ratio: float = 0.4,
) -> List[TextLine]:
    """Group words into horizontal lines based on baseline alignment and vertical overlap.

    Args:
        words: Sequence of TextWord instances.
        vertical_overlap_ratio: Minimum ratio of vertical bounding box overlap to join a line.

    Returns:
        List of TextLine objects ordered top-to-bottom, left-to-right.
    """
    if not words:
        return []

    # Sort words primarily by vertical baseline, secondarily by horizontal x0
    sorted_words = sorted(words, key=lambda w: (round(w.baseline_y, 1), w.bbox.x0))

    # Active lines under construction: list of lists of TextWord
    raw_lines: List[List[TextWord]] = []

    for w in sorted_words:
        matched_line: Optional[List[TextWord]] = None
        min_base_diff = float("inf")

        for line_words in raw_lines:
            # Check baseline proximity against the line's average baseline
            line_base = sum(lw.baseline_y for lw in line_words) / len(line_words)
            line_size = sum(lw.font_size for lw in line_words) / len(line_words)
            diff = abs(w.baseline_y - line_base)

            # Check vertical box overlap
            line_y0 = min(lw.bbox.y0 for lw in line_words)
            line_y1 = max(lw.bbox.y1 for lw in line_words)
            overlap_y = max(0.0, min(w.bbox.y1, line_y1) - max(w.bbox.y0, line_y0))
            min_height = min(w.height, line_y1 - line_y0)
            overlap_ratio = overlap_y / min_height if min_height > 0 else 0.0

            if (diff <= 0.4 * line_size or overlap_ratio >= vertical_overlap_ratio) and diff < min_base_diff:
                min_base_diff = diff
                matched_line = line_words

        if matched_line is not None:
            matched_line.append(w)
        else:
            raw_lines.append([w])

    # Build finalized TextLine objects
    final_lines: List[TextLine] = []
    for line_words in raw_lines:
        # Sort words in line horizontally from left to right
        line_words.sort(key=lambda w: w.bbox.x0)

        # Split line if there is a significant horizontal gap between words
        # (e.g. multi-column layout or separated blocks on same baseline)
        split_groups: List[List[TextWord]] = [[line_words[0]]]
        for w in line_words[1:]:
            prev_w = split_groups[-1][-1]
            gap = w.bbox.x0 - prev_w.bbox.x1
            max_gap = max(24.0, 2.5 * max(w.font_size, prev_w.font_size))
            if gap > max_gap:
                split_groups.append([w])
            else:
                split_groups[-1].append(w)

        for grp in split_groups:
            # Merge bounding box
            x0 = min(w.bbox.x0 for w in grp)
            y0 = min(w.bbox.y0 for w in grp)
            x1 = max(w.bbox.x1 for w in grp)
            y1 = max(w.bbox.y1 for w in grp)
            line_bbox = BoundingBox(x0, y0, x1, y1)

            avg_base = sum(w.baseline_y for w in grp) / len(grp)
            line_text = " ".join(w.text for w in grp)

            # Statistical dominant font attributes
            font_counts: dict[str, int] = {}
            for w in grp:
                font_counts[w.font_name] = font_counts.get(w.font_name, 0) + len(w.text)
            dominant_font = max(font_counts.items(), key=lambda kv: kv[1])[0]

            dominant_size = sum(w.font_size * len(w.text) for w in grp) / max(1, sum(len(w.text) for w in grp))
            dominant_color = grp[0].color
            has_bold = any(w.is_bold for w in grp)
            has_italic = any(w.is_italic for w in grp)

            final_lines.append(
                TextLine(
                    words=grp,
                    bbox=line_bbox,
                    baseline_y=avg_base,
                    text=line_text,
                    font_name=dominant_font,
                    font_size=dominant_size,
                    color=dominant_color,
                    is_bold=has_bold,
                    is_italic=has_italic,
                )
            )

    # Sort final lines top-to-bottom (Y ascending in doc coordinates), then left-to-right
    final_lines.sort(key=lambda l: (round(l.bbox.y0, 1), l.bbox.x0))
    return final_lines


__all__ = [
    "TextWord",
    "TextLine",
    "cluster_characters_to_words",
    "cluster_words_to_lines",
]
