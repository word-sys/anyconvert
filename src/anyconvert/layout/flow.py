"""Running header, footer, and page number detection and flow partitioning.

Isolates marginal page headers, footers, and page numbers from document body flow,
enabling clean single-story or continuous flow reconstruction in DOCX/ODT/TXT.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Set, Tuple

from anyconvert.layout.cluster import TextLine
from anyconvert.layout.xycut import LayoutBlock

# Page number regex patterns
_PAGE_NUM_PATTERNS = [
    re.compile(r"^\d+$"),                                    # "1", "42"
    re.compile(r"^\s*-\s*\d+\s*-\s*$"),                      # "- 1 -"
    re.compile(r"^Page\s+\d+(\s+(?:of|/)\s+\d+)?$", re.I),   # "Page 1", "Page 2 of 10"
    re.compile(r"^\d+\s*/\s*\d+$"),                          # "1 / 5"
    re.compile(r"^[ivxlcdmIVXLCDM]+$"),                      # "i", "iv", "xii"
]


def is_page_number_pattern(text: str) -> bool:
    """Check if text matches standard page number formatting."""
    cleaned = text.strip()
    return any(p.match(cleaned) for p in _PAGE_NUM_PATTERNS)


def is_header_candidate(
    line: TextLine,
    page_height: float,
    top_margin: float = 72.0,
) -> bool:
    """Determine whether a line is positioned within the top page margin."""
    # In document space, y0 is distance from top of page
    return line.bbox.y0 <= top_margin


def is_footer_candidate(
    line: TextLine,
    page_height: float,
    bottom_margin: float = 72.0,
) -> bool:
    """Determine whether a line is positioned within the bottom page margin."""
    return line.bbox.y1 >= page_height - bottom_margin


@dataclass(slots=True)
class PageFlowPartition:
    """Segregated page flow content separating margins from body story."""

    headers: List[TextLine] = field(default_factory=list)
    footers: List[TextLine] = field(default_factory=list)
    page_numbers: List[TextLine] = field(default_factory=list)
    body_lines: List[TextLine] = field(default_factory=list)
    body_blocks: List[LayoutBlock] = field(default_factory=list)


def partition_page_flow(
    lines: Sequence[TextLine],
    blocks: Optional[Sequence[LayoutBlock]] = None,
    page_height: float = 792.0,
    top_margin: float = 72.0,
    bottom_margin: float = 72.0,
    known_headers: Optional[Set[str]] = None,
    known_footers: Optional[Set[str]] = None,
) -> PageFlowPartition:
    """Segregate text lines and layout blocks into headers, footers, page numbers, and body.

    Args:
        lines: Sequence of TextLine objects on the page.
        blocks: Optional Sequence of LayoutBlock objects on the page.
        page_height: Page height in points (e.g. 792 for US Letter, 842 for A4).
        top_margin: Top margin boundary in points (default 72 pt = 1 inch).
        bottom_margin: Bottom margin boundary in points (default 72 pt = 1 inch).
        known_headers: Optional set of normalized strings confirmed as headers.
        known_footers: Optional set of normalized strings confirmed as footers.

    Returns:
        PageFlowPartition containing isolated marginal and body elements.
    """
    headers: List[TextLine] = []
    footers: List[TextLine] = []
    page_nums: List[TextLine] = []
    body_lines: List[TextLine] = []

    for l in lines:
        text = l.text.strip()
        if not text:
            continue

        # 1. Page Number check
        if is_page_number_pattern(text) and (
            is_header_candidate(l, page_height, top_margin)
            or is_footer_candidate(l, page_height, bottom_margin)
        ):
            page_nums.append(l)
            continue

        # 2. Known repeating headers/footers
        if known_headers is not None:
            if text in known_headers:
                headers.append(l)
            elif known_footers is not None and text in known_footers:
                footers.append(l)
            else:
                body_lines.append(l)
            continue

        # 3. Position-based candidate check (only when cross-page repetition is not known)
        if is_header_candidate(l, page_height, top_margin) and l.font_size <= 11.0 and len(text) < 80:
            headers.append(l)
        elif is_footer_candidate(l, page_height, bottom_margin) and l.font_size <= 11.0 and len(text) < 80:
            footers.append(l)
        else:
            body_lines.append(l)

    # Filter blocks: remove blocks whose lines are entirely marginal
    body_blocks: List[LayoutBlock] = []
    marginal_lines = set(id(l) for l in headers + footers + page_nums)

    if blocks:
        for b in blocks:
            # Retain block if it contains body lines or non-text elements
            has_body_text = any(id(l) not in marginal_lines for l in b.lines)
            has_other_elements = any(type(e).__name__ != "TextLine" for e in b.elements)
            if has_body_text or has_other_elements:
                body_blocks.append(b)

    return PageFlowPartition(
        headers=headers,
        footers=footers,
        page_numbers=page_nums,
        body_lines=body_lines,
        body_blocks=body_blocks,
    )


def detect_repeating_headers_footers(
    pages_lines: Sequence[Sequence[TextLine]],
    page_height: float = 792.0,
    top_margin: float = 72.0,
    bottom_margin: float = 72.0,
) -> Tuple[Set[str], Set[str]]:
    """Identify repeating running headers and footers across multiple pages.

    Args:
        pages_lines: Sequence of pages, each containing its list of TextLine objects.
        page_height: Page height in points.
        top_margin: Top margin boundary in points.
        bottom_margin: Bottom margin boundary in points.

    Returns:
        Tuple of (repeating_headers, repeating_footers) sets of normalized strings.
    """
    if len(pages_lines) < 2:
        return set(), set()

    header_counts: dict[str, int] = {}
    footer_counts: dict[str, int] = {}

    for p_lines in pages_lines:
        p_headers = set()
        p_footers = set()
        for l in p_lines:
            t = l.text.strip()
            if not t or is_page_number_pattern(t):
                continue
            if is_header_candidate(l, page_height, top_margin):
                p_headers.add(t)
            elif is_footer_candidate(l, page_height, bottom_margin):
                p_footers.add(t)

        for h in p_headers:
            header_counts[h] = header_counts.get(h, 0) + 1
        for f in p_footers:
            footer_counts[f] = footer_counts.get(f, 0) + 1

    # Text appearing in margin across 2 or more pages is confirmed running header/footer
    repeating_headers = {h for h, count in header_counts.items() if count >= 2}
    repeating_footers = {f for f, count in footer_counts.items() if count >= 2}

    return repeating_headers, repeating_footers


__all__ = [
    "PageFlowPartition",
    "is_page_number_pattern",
    "is_header_candidate",
    "is_footer_candidate",
    "partition_page_flow",
    "detect_repeating_headers_footers",
]
