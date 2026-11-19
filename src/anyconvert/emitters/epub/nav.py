"""EPUB 3.3 Navigation Document (nav.xhtml) and legacy NCX (toc.ncx) generator.

Builds hierarchical H1-H3 tables of contents adhering to:
- W3C EPUB 3.3 Navigation Document specification (<nav epub:type="toc"> and landmarks).
- DAISY 2005-1 NCX specification (<navMap>, <navPoint>, sequential playOrder)
  for legacy Kindle, Kobo, and EPUB 2 e-readers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from anyconvert.emitters.base import xml_escape
from anyconvert.emitters.epub.opf import normalize_opf_href
from anyconvert.ir.model import DocumentIR, Paragraph

XHTML_NS = "http://www.w3.org/1999/xhtml"
EPUB_OPS_NS = "http://www.idpf.org/2007/ops"
NCX_NS = "http://www.daisy.org/z3986/2005/ncx/"
NCX_VERSION = "2005-1"


@dataclass(slots=True)
class TocEntry:
    """Single node in a hierarchical EPUB table of contents."""

    title: str
    href: str
    level: int = 1
    children: List[TocEntry] = field(default_factory=list)
    entry_id: Optional[str] = None

    def __post_init__(self) -> None:
        self.title = self.title.strip() or "Untitled Section"
        self.level = max(1, min(6, int(self.level)))
        self.href = _normalize_nav_href(self.href)


def _normalize_nav_href(href: str) -> str:
    """Normalize a navigation target href while preserving optional #fragment."""
    raw = href.strip()
    if "#" in raw:
        path_part, frag = raw.split("#", 1)
        norm_path = normalize_opf_href(path_part) if path_part else ""
        return f"{norm_path}#{frag}" if frag else norm_path
    return normalize_opf_href(raw)


def build_toc_tree(flat_entries: Sequence[TocEntry]) -> List[TocEntry]:
    """Convert a flat sequence of H1-H3 TocEntry items into a nested TOC tree.

    Handles skipped heading levels (e.g. H1 -> H3) and documents starting with
    H2/H3 without raising errors. Input entries are cloned so callers' objects
    are not mutated.
    """
    roots: List[TocEntry] = []
    stack: List[TocEntry] = []

    for src in flat_entries:
        node = TocEntry(
            title=src.title,
            href=src.href,
            level=src.level,
            children=[],
            entry_id=src.entry_id,
        )
        while stack and stack[-1].level >= node.level:
            stack.pop()

        if stack:
            stack[-1].children.append(node)
        else:
            roots.append(node)

        stack.append(node)

    return roots


def compute_toc_depth(entries: Sequence[TocEntry]) -> int:
    """Compute the maximum nesting depth of a TOC tree (minimum 1 when non-empty)."""
    if not entries:
        return 1

    def _depth(nodes: Sequence[TocEntry]) -> int:
        best = 0
        for node in nodes:
            child_d = _depth(node.children) if node.children else 0
            best = max(best, 1 + child_d)
        return best

    return max(1, _depth(entries))


def extract_toc_entries_from_ir(
    doc_ir: DocumentIR,
    default_href: str = "Text/chapter_1.xhtml",
    max_level: int = 3,
) -> List[TocEntry]:
    """Extract a hierarchical H1-H3 TOC tree from DocumentIR heading paragraphs."""
    flat: List[TocEntry] = []
    heading_idx = 0

    for page in doc_ir.pages:
        for block in page.blocks:
            if not isinstance(block, Paragraph):
                continue
            if block.heading_level is None:
                continue
            lvl = block.heading_level.value
            if not (1 <= lvl <= max_level):
                continue
            text = block.text.strip()
            if not text:
                continue
            heading_idx += 1
            anchor = f"heading-{heading_idx}"
            flat.append(
                TocEntry(
                    title=text,
                    href=f"{default_href}#{anchor}",
                    level=lvl,
                    entry_id=anchor,
                )
            )

    return build_toc_tree(flat)


def _ensure_non_empty_toc(
    entries: Sequence[TocEntry],
    fallback_title: str,
    default_href: str,
) -> List[TocEntry]:
    """Guarantee at least one valid TOC entry as required by EPUB 3.3 and NCX."""
    if entries:
        return list(entries)
    return [TocEntry(title=fallback_title or "Start", href=default_href, level=1)]


def _render_nav_ol(entries: Sequence[TocEntry], indent: str) -> List[str]:
    """Recursively render an XHTML <ol> list for EPUB 3 <nav epub:type='toc'>."""
    lines: List[str] = [f"{indent}<ol>"]
    item_indent = indent + "  "
    for entry in entries:
        href_esc = xml_escape(entry.href)
        title_esc = xml_escape(entry.title)
        if entry.children:
            lines.append(f'{item_indent}<li>')
            lines.append(f'{item_indent}  <a href="{href_esc}">{title_esc}</a>')
            lines.extend(_render_nav_ol(entry.children, item_indent + "  "))
            lines.append(f"{item_indent}</li>")
        else:
            lines.append(f'{item_indent}<li><a href="{href_esc}">{title_esc}</a></li>')
    lines.append(f"{indent}</ol>")
    return lines


def generate_nav_xhtml(
    entries: Sequence[TocEntry],
    title: str = "Table of Contents",
    language: str = "en",
    stylesheet_href: Optional[str] = None,
    default_href: str = "Text/chapter_1.xhtml",
    include_landmarks: bool = True,
) -> bytes:
    """Generate an EPUB 3.3 compliant Navigation Document (nav.xhtml)."""
    lang = language.strip().replace("_", "-") or "en"
    toc_title = title.strip() or "Table of Contents"
    resolved_entries = _ensure_non_empty_toc(entries, toc_title, default_href)

    head_lines: List[str] = [
        "  <head>",
        '    <meta charset="utf-8"/>',
        f"    <title>{xml_escape(toc_title)}</title>",
    ]
    if stylesheet_href:
        css_href = normalize_opf_href(stylesheet_href)
        head_lines.append(
            f'    <link rel="stylesheet" type="text/css" href="{xml_escape(css_href)}"/>'
        )
    head_lines.append("  </head>")

    body_lines: List[str] = [
        "  <body>",
        '    <nav epub:type="toc" id="toc" role="doc-toc">',
        f"      <h1>{xml_escape(toc_title)}</h1>",
    ]
    body_lines.extend(_render_nav_ol(resolved_entries, "      "))
    body_lines.append("    </nav>")

    if include_landmarks:
        first_href = resolved_entries[0].href
        body_lines.extend(
            [
                '    <nav epub:type="landmarks" id="landmarks" hidden="">',
                "      <h2>Landmarks</h2>",
                "      <ol>",
                f'        <li><a epub:type="toc" href="#toc">{xml_escape(toc_title)}</a></li>',
                f'        <li><a epub:type="bodymatter" href="{xml_escape(first_href)}">Start of Content</a></li>',
                "      </ol>",
                "    </nav>",
            ]
        )

    body_lines.append("  </body>")

    lines: List[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!DOCTYPE html>",
        (
            f'<html xmlns="{XHTML_NS}" xmlns:epub="{EPUB_OPS_NS}" '
            f'xml:lang="{xml_escape(lang)}" lang="{xml_escape(lang)}">'
        ),
    ]
    lines.extend(head_lines)
    lines.extend(body_lines)
    lines.append("</html>")
    return "\n".join(lines).encode("utf-8")


def _render_ncx_navpoints(
    entries: Sequence[TocEntry],
    indent: str,
    play_order_counter: List[int],
) -> List[str]:
    """Recursively serialize <navPoint> elements with monotonic depth-first playOrder."""
    lines: List[str] = []
    for entry in entries:
        order = play_order_counter[0]
        play_order_counter[0] += 1
        nav_id = f"navPoint-{order}"
        lines.append(f'{indent}<navPoint id="{nav_id}" playOrder="{order}">')
        lines.append(f"{indent}  <navLabel>")
        lines.append(f"{indent}    <text>{xml_escape(entry.title)}</text>")
        lines.append(f"{indent}  </navLabel>")
        lines.append(f'{indent}  <content src="{xml_escape(entry.href)}"/>')
        if entry.children:
            lines.extend(_render_ncx_navpoints(entry.children, indent + "  ", play_order_counter))
        lines.append(f"{indent}</navPoint>")
    return lines


def generate_toc_ncx(
    entries: Sequence[TocEntry],
    identifier: str,
    title: str = "Untitled Document",
    author: str = "",
    language: str = "en",
    default_href: str = "Text/chapter_1.xhtml",
) -> bytes:
    """Generate a legacy DAISY 2005-1 NCX table of contents (toc.ncx)."""
    lang = language.strip().replace("_", "-") or "en"
    doc_title = title.strip() or "Untitled Document"
    uid = identifier.strip() or "urn:uuid:00000000-0000-0000-0000-000000000000"
    resolved_entries = _ensure_non_empty_toc(entries, doc_title, default_href)
    depth = compute_toc_depth(resolved_entries)

    lines: List[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<ncx xmlns="{NCX_NS}" version="{NCX_VERSION}" xml:lang="{xml_escape(lang)}">',
        "  <head>",
        f'    <meta name="dtb:uid" content="{xml_escape(uid)}"/>',
        f'    <meta name="dtb:depth" content="{depth}"/>',
        '    <meta name="dtb:totalPageCount" content="0"/>',
        '    <meta name="dtb:maxPageNumber" content="0"/>',
        "  </head>",
        "  <docTitle>",
        f"    <text>{xml_escape(doc_title)}</text>",
        "  </docTitle>",
    ]

    if author.strip():
        lines.extend(
            [
                "  <docAuthor>",
                f"    <text>{xml_escape(author.strip())}</text>",
                "  </docAuthor>",
            ]
        )

    lines.append("  <navMap>")
    lines.extend(_render_ncx_navpoints(resolved_entries, "    ", [1]))
    lines.append("  </navMap>")
    lines.append("</ncx>")
    return "\n".join(lines).encode("utf-8")


class NavigationBuilder:
    """Stateful helper generating paired EPUB 3 nav.xhtml and EPUB 2 toc.ncx documents."""

    __slots__ = (
        "entries",
        "title",
        "identifier",
        "author",
        "language",
        "stylesheet_href",
        "default_href",
    )

    def __init__(
        self,
        entries: Sequence[TocEntry],
        identifier: str,
        title: str = "Untitled Document",
        author: str = "",
        language: str = "en",
        stylesheet_href: Optional[str] = None,
        default_href: str = "Text/chapter_1.xhtml",
    ) -> None:
        self.entries: List[TocEntry] = list(entries)
        self.identifier: str = identifier
        self.title: str = title
        self.author: str = author
        self.language: str = language
        self.stylesheet_href: Optional[str] = stylesheet_href
        self.default_href: str = default_href

    def build_nav_xhtml(
        self,
        toc_title: str = "Table of Contents",
        include_landmarks: bool = True,
    ) -> bytes:
        """Render EPUB 3.3 nav.xhtml bytes."""
        return generate_nav_xhtml(
            entries=self.entries,
            title=toc_title,
            language=self.language,
            stylesheet_href=self.stylesheet_href,
            default_href=self.default_href,
            include_landmarks=include_landmarks,
        )

    def build_toc_ncx(self) -> bytes:
        """Render legacy EPUB 2 toc.ncx bytes."""
        return generate_toc_ncx(
            entries=self.entries,
            identifier=self.identifier,
            title=self.title,
            author=self.author,
            language=self.language,
            default_href=self.default_href,
        )


__all__ = [
    "XHTML_NS",
    "EPUB_OPS_NS",
    "NCX_NS",
    "NCX_VERSION",
    "TocEntry",
    "NavigationBuilder",
    "build_toc_tree",
    "compute_toc_depth",
    "extract_toc_entries_from_ir",
    "generate_nav_xhtml",
    "generate_toc_ncx",
]
