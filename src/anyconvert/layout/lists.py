"""List and bullet point detection, marker extraction, and nesting level tracking.

Identifies bullet characters, numbering patterns (Arabic, Roman, Alphabetic),
and computes hierarchical list nesting levels from spatial indentations.
"""

from __future__ import annotations

import re
from typing import Optional, Sequence, Tuple

from anyconvert.layout.paragraph import ParagraphCluster

# Bullet characters recognized across documents
BULLET_CHARS = {
    "\u2022",  # • Bullet
    "\u2023",  # ‣ Triangular bullet
    "\u25cf",  # ● Black circle
    "\u25cb",  # ○ White circle
    "\u25e6",  # ◦ White bullet
    "\u25aa",  # ▪ Black small square
    "\u25ab",  # ▫ White small square
    "\u25c6",  # ◆ Black diamond
    "\u25c7",  # ◇ White diamond
    "\u2713",  # ✓ Check mark
    "\u27a4",  # ➤ Black right arrow
    "\u2013",  # – En dash
    "\u2014",  # — Em dash
    "*",
    "-",
}

# Regex for bullet symbol prefix
_BULLET_PREFIX_REGEX = re.compile(
    r"^([\u2022\u2023\u25cf\u25cb\u25e6\u25aa\u25ab\u25c6\u25c7\u2713\u27a4\u2013\u2014\*\-])\s+(.*)$",
    re.DOTALL,
)

# Regex for numbered list prefix:
# - Arabic: "1.", "1)", "(1)", "1.1", "1.1.1"
# - Alphabetic: "a.", "B)", "(c)"
# - Roman: "i.", "iv)", "(III)"
_NUMBERED_PREFIX_REGEX = re.compile(
    r"^(\(?\d+(?:\.\d+)*[\.\)]|\(?[a-zA-Z][\.\)]|\(?[ivxlcdmIVXLCDM]+[\.\)])\s+(.*)$",
    re.DOTALL,
)


def detect_list_item(
    text: str,
    indent: float = 0.0,
    base_indent: float = 0.0,
) -> Optional[Tuple[str, str, int]]:
    """Determine whether text begins with a bullet or numbering marker.

    Args:
        text: Raw paragraph or line text.
        indent: Left spatial indentation of the element in points.
        base_indent: Minimum left margin of the parent container in points.

    Returns:
        Tuple of (marker, clean_content, nest_level) if a list item is detected,
        or None otherwise.
    """
    stripped = text.strip()
    if not stripped:
        return None

    marker: Optional[str] = None
    clean_text: Optional[str] = None

    # 1. Match bullet symbols
    m_bullet = _BULLET_PREFIX_REGEX.match(stripped)
    if m_bullet:
        marker = m_bullet.group(1)
        clean_text = m_bullet.group(2).strip()
    else:
        # 2. Match numbered patterns
        m_num = _NUMBERED_PREFIX_REGEX.match(stripped)
        if m_num:
            marker = m_num.group(1)
            clean_text = m_num.group(2).strip()

    if marker is None or clean_text is None:
        return None

    # Calculate hierarchical nesting level based on indentation (approx 18-20 pt per level)
    delta_indent = max(0.0, indent - base_indent)
    nest_level = min(8, int(round(delta_indent / 18.0)))

    return marker, clean_text, nest_level


def process_list_paragraphs(
    paragraphs: Sequence[ParagraphCluster],
    base_indent: Optional[float] = None,
) -> None:
    """Analyze paragraphs for list markers and assign list_marker and list_level in-place.

    Args:
        paragraphs: Sequence of ParagraphCluster instances to process.
        base_indent: Container minimum left indentation. If None, computes dynamically.
    """
    if not paragraphs:
        return

    b_indent = (
        base_indent
        if base_indent is not None
        else min(p.indent_left for p in paragraphs)
    )

    for p in paragraphs:
        # Skip headings
        if p.heading_level is not None:
            p.list_marker = None
            p.list_level = 0
            continue

        raw_text = p.text.strip()
        result = detect_list_item(raw_text, indent=p.indent_left, base_indent=b_indent)
        if result is not None:
            marker, _, level = result
            p.list_marker = marker
            p.list_level = level
        else:
            p.list_marker = None
            p.list_level = 0


__all__ = [
    "BULLET_CHARS",
    "detect_list_item",
    "process_list_paragraphs",
]
