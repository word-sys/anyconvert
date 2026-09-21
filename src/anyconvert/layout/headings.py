"""Statistical heading detector and classification engine (H1-H6).

Evaluates font sizes, weights, and structural isolation relative to the document's
modal body text metrics to classify headings into standard hierarchical levels.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Dict, Optional, Sequence

from anyconvert.layout.paragraph import ParagraphCluster


class HeadingLevel(Enum):
    """Hierarchical heading levels matching HTML/DOCX standards."""

    H1 = 1
    H2 = 2
    H3 = 3
    H4 = 4
    H5 = 5
    H6 = 6


# Numbered heading pattern: e.g. "1. Introduction", "2.1 Background"
_NUMBERED_HEADING_REGEX = re.compile(r"^\d+(?:\.\d+)*\.?\s+[A-Z]")


def compute_modal_body_font_size(paragraphs: Sequence[ParagraphCluster]) -> float:
    """Determine the dominant body text font size by character-weighted modal distribution.

    Args:
        paragraphs: Sequence of synthesized ParagraphCluster instances.

    Returns:
        Modal body text font size in points.
    """
    if not paragraphs:
        return 12.0

    histogram: Dict[float, int] = {}
    for p in paragraphs:
        # Group font sizes rounded to 0.5 pt
        rounded_size = round(p.font_size * 2) / 2.0
        char_count = sum(len(l.text) for l in p.lines)
        if char_count > 0:
            histogram[rounded_size] = histogram.get(rounded_size, 0) + char_count

    if not histogram:
        return 12.0

    # Pick size with maximum character volume
    return max(histogram.items(), key=lambda kv: kv[1])[0]


def classify_headings(
    paragraphs: Sequence[ParagraphCluster],
    body_size: Optional[float] = None,
) -> None:
    """Classify headings across paragraphs and assign heading_level (1-6 or None).

    Modifies paragraph.heading_level in-place.

    Args:
        paragraphs: Sequence of ParagraphCluster instances to evaluate.
        body_size: Optional precomputed body text size. If None, computes dynamically.
    """
    if not paragraphs:
        return

    b_size = body_size if body_size is not None else compute_modal_body_font_size(paragraphs)

    for p in paragraphs:
        text = p.text.strip()
        if not text:
            p.heading_level = None
            continue

        # Criteria to disqualify long body paragraphs
        # Headings are concise, rarely exceeding 2-3 lines or 180 characters
        num_lines = len(p.lines)
        char_len = len(text)
        if num_lines > 3 or char_len > 200:
            p.heading_level = None
            continue

        # Check ending punctuation: body paragraphs typically end with ., ?, !
        # Unless it matches a numbered heading pattern like "1. Introduction"
        ends_with_sentence_punct = text.endswith((".", "?", "!"))
        is_numbered = bool(_NUMBERED_HEADING_REGEX.match(text))

        if ends_with_sentence_punct and not is_numbered and num_lines > 1:
            p.heading_level = None
            continue

        size = p.font_size
        is_bold = p.is_bold
        size_ratio = size / b_size

        # Classification thresholds
        if size_ratio >= 1.6:
            p.heading_level = HeadingLevel.H1.value
        elif size_ratio >= 1.35:
            p.heading_level = HeadingLevel.H2.value
        elif size_ratio >= 1.18:
            p.heading_level = HeadingLevel.H3.value
        elif size_ratio >= 1.05 and is_bold:
            p.heading_level = HeadingLevel.H4.value
        elif is_bold and num_lines == 1 and char_len < 100 and not ends_with_sentence_punct:
            p.heading_level = HeadingLevel.H5.value
        elif (p.is_italic or text.isupper()) and num_lines == 1 and char_len < 80 and not ends_with_sentence_punct:
            p.heading_level = HeadingLevel.H6.value
        else:
            p.heading_level = None


__all__ = [
    "HeadingLevel",
    "compute_modal_body_font_size",
    "classify_headings",
]
