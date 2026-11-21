"""Pure-Python Typst (.typ) document emitter architecture.

Generates clean, compilable Typst markup with idiomatic document setup:
- Metadata configuration (#set document(title: ..., author: ..., keywords: ...)).
- Page geometry and margins (#set page(width: ..., height: ..., margin: (...))).
- Typography defaults (#set text(font: ..., size: ..., lang: ...), #set par(...)).
- Multi-page section transitions (#pagebreak(weak: true) and dynamic page sizes).
- Reflowable headings, inline styling, lists, tables, and figures.
"""

from __future__ import annotations

from collections import Counter
import pathlib
import re
from typing import Dict, List, Optional, Tuple, Union

from anyconvert.emitters.base import BaseEmitter, ConversionMode
from anyconvert.exceptions import SerializationError
from anyconvert.ir.model import (
    BlockNode,
    DocumentIR,
    DocumentPage,
    ImageBlock,
    Paragraph,
    Table,
    TextRun,
    VectorBlock,
)

# PDF embedded font subset tag pattern (e.g. "ABCDEF+TimesNewRoman-Bold")
_SUBSET_PREFIX_RE = re.compile(r"^[A-Z]{6}\+")

# Characters that carry special meaning in Typst markup mode
_TYPST_ESCAPE_CHARS = frozenset("\\#*_`$<>\x40[]=~")


def clean_typst_font_name(raw_name: str) -> str:
    """Normalize a PDF font name into a clean Typst font family string."""
    if not raw_name or not raw_name.strip():
        return "Libertinus Serif"
    cleaned = _SUBSET_PREFIX_RE.sub("", raw_name.strip())
    base = re.split(r"[-,]", cleaned, maxsplit=1)[0].strip()
    base = base.replace('"', "").replace("\\", "")
    return base or "Libertinus Serif"


def escape_typst_string(text: str) -> str:
    """Escape a Python string for placement inside a Typst double-quoted literal."""
    if not text:
        return ""
    cleaned = "".join(ch for ch in text if ord(ch) >= 0x20 or ch in ("\t", "\n"))
    return (
        cleaned.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\t", "\\t")
        .replace("\n", "\\n")
    )


def escape_typst_markup(text: str) -> str:
    """Escape raw text for safe inclusion in Typst markup content mode."""
    if not text:
        return ""
    out: List[str] = []
    n = len(text)
    for i, ch in enumerate(text):
        code = ord(ch)
        if ch == "\r":
            continue
        if ch == "\n":
            out.append(" \\\n")
            continue
        if ch == "\t":
            out.append("  ")
            continue
        if code < 0x20 or code == 0x7F:
            continue
        if ch in _TYPST_ESCAPE_CHARS:
            out.append("\\" + ch)
        elif ch == "/" and i + 1 < n and text[i + 1] in ("/", "*"):
            # Prevent accidental // line comment or /* block comment
            out.append("\\/")
        else:
            out.append(ch)
    return "".join(out)


def _format_pt(value: float) -> str:
    """Format a point measurement cleanly (e.g., 612pt or 595.28pt)."""
    rounded = round(value, 2)
    if abs(rounded - round(rounded)) < 1e-6:
        return f"{int(round(rounded))}pt"
    return f"{rounded:.2f}".rstrip("0").rstrip(".") + "pt"


def _detect_modal_typography(doc_ir: DocumentIR) -> Tuple[str, float]:
    """Detect the dominant body font family and font size across DocumentIR."""
    font_counts: Counter[str] = Counter()
    size_counts: Counter[float] = Counter()

    for page in doc_ir.pages:
        for block in page.blocks:
            if isinstance(block, Paragraph) and block.heading_level is None:
                for run in block.runs:
                    weight = len(run.text.strip())
                    if weight <= 0:
                        continue
                    if run.font_name:
                        font_counts[clean_typst_font_name(run.font_name)] += weight
                    if run.font_size > 0:
                        size_counts[round(run.font_size, 1)] += weight

    dominant_font = font_counts.most_common(1)[0][0] if font_counts else "Libertinus Serif"
    dominant_size = size_counts.most_common(1)[0][0] if size_counts else 11.0
    dominant_size = max(6.0, min(36.0, dominant_size))
    return dominant_font, dominant_size


class TypstEmitter(BaseEmitter):
    """Pure-Python Typst (.typ) document emitter generating clean, compilable source."""

    __slots__ = (
        "language",
        "render_headers_footers",
        "emit_pagebreaks",
        "enable_math_heuristics",
        "image_dir",
        "extracted_images",
    )

    def __init__(
        self,
        language: str = "en",
        render_headers_footers: bool = True,
        emit_pagebreaks: bool = True,
        enable_math_heuristics: bool = True,
        image_dir: Optional[Union[str, pathlib.Path]] = None,
    ) -> None:
        self.language: str = language.strip().replace("_", "-") or "en"
        self.render_headers_footers: bool = render_headers_footers
        self.emit_pagebreaks: bool = emit_pagebreaks
        self.enable_math_heuristics: bool = enable_math_heuristics
        self.image_dir: Optional[pathlib.Path] = (
            pathlib.Path(image_dir) if image_dir is not None else None
        )
        self.extracted_images: List[pathlib.Path] = []

    def emit(
        self,
        doc_ir: DocumentIR,
        mode: ConversionMode = ConversionMode.FLOW,
    ) -> bytes:
        """Serialize DocumentIR into UTF-8 encoded Typst (.typ) source bytes.

        Args:
            doc_ir: Validated DocumentIR structure.
            mode: Layout mode (informational; Typst uses reflowable layout rules).

        Returns:
            UTF-8 encoded bytes of the generated Typst source.

        Raises:
            SerializationError: If doc_ir contains no pages.
        """
        if not doc_ir.pages:
            raise SerializationError("Cannot emit Typst from empty DocumentIR")

        return self.render(doc_ir).encode("utf-8")

    def render(self, doc_ir: DocumentIR) -> str:
        """Render DocumentIR into a complete Typst source string."""
        if not doc_ir.pages:
            raise SerializationError("Cannot emit Typst from empty DocumentIR")

        self.extracted_images = []
        sections: List[str] = []

        # 1. Preamble: #set document(...), #set page(...), #set text(...), #set par(...)
        preamble = self.build_preamble(doc_ir)
        if preamble:
            sections.append(preamble)

        # 2. Body pages
        image_counter = [1]
        for page_idx, page in enumerate(doc_ir.pages):
            if page_idx > 0:
                prev = doc_ir.pages[page_idx - 1]
                dims_changed = (
                    abs(page.width - prev.width) > 1.0
                    or abs(page.height - prev.height) > 1.0
                )
                if dims_changed:
                    sections.append(self.build_page_setup(page, include_marginals=False))
                elif self.emit_pagebreaks:
                    sections.append("#pagebreak(weak: true)")

            page_body = self.render_page(page, image_counter=image_counter)
            if page_body:
                sections.append(page_body)

        return "\n\n".join(sections).strip() + "\n"

    def build_preamble(self, doc_ir: DocumentIR) -> str:
        """Construct the Typst document setup preamble (#set document, page, text, par)."""
        lines: List[str] = []

        doc_setup = self.build_document_setup(doc_ir.metadata)
        if doc_setup:
            lines.append(doc_setup)

        first_page = doc_ir.pages[0]
        lines.append(self.build_page_setup(first_page, include_marginals=True))

        font_name, font_size = _detect_modal_typography(doc_ir)
        lines.append(self.build_text_setup(font_name=font_name, font_size=font_size))
        lines.append("#set par(leading: 0.65em)")
        lines.append("#set heading(numbering: none)")

        return "\n".join(lines)

    def build_document_setup(self, metadata: Dict[str, str]) -> str:
        """Build #set document(...) directive from DocumentIR metadata."""
        if not metadata:
            return ""
        lowered = {
            k.lstrip("/").lower(): v.strip()
            for k, v in metadata.items()
            if v and v.strip()
        }
        args: List[str] = []
        if "title" in lowered:
            args.append(f'title: "{escape_typst_string(lowered["title"])}"')
        if "author" in lowered:
            authors = [a.strip() for a in re.split(r"[;]+", lowered["author"]) if a.strip()]
            if len(authors) == 1:
                args.append(f'author: "{escape_typst_string(authors[0])}"')
            elif len(authors) > 1:
                joined = ", ".join(f'"{escape_typst_string(a)}"' for a in authors)
                args.append(f"author: ({joined})")
        if "subject" in lowered:
            args.append(f'description: "{escape_typst_string(lowered["subject"])}"')
        if "keywords" in lowered:
            kws = [kw.strip() for kw in re.split(r"[,;]+", lowered["keywords"]) if kw.strip()]
            if kws:
                joined_kw = ", ".join(f'"{escape_typst_string(kw)}"' for kw in kws)
                if len(kws) == 1:
                    joined_kw += ","
                args.append(f"keywords: ({joined_kw})")

        if not args:
            return ""
        return "#set document(\n  " + ",\n  ".join(args) + ",\n)"

    def build_page_setup(
        self,
        page: DocumentPage,
        include_marginals: bool = True,
    ) -> str:
        """Build #set page(...) directive with dimensions, margins, and optional header/footer."""
        w = max(72.0, page.width)
        h = max(72.0, page.height)
        m_top = max(0.0, page.margin_top)
        m_bottom = max(0.0, page.margin_bottom)
        m_left = max(0.0, page.margin_left)
        m_right = max(0.0, page.margin_right)

        args: List[str] = [
            f"width: {_format_pt(w)}",
            f"height: {_format_pt(h)}",
            (
                f"margin: (top: {_format_pt(m_top)}, bottom: {_format_pt(m_bottom)}, "
                f"left: {_format_pt(m_left)}, right: {_format_pt(m_right)})"
            ),
        ]

        if include_marginals and self.render_headers_footers:
            if page.header and page.header.content:
                hdr_txt = " ".join(
                    escape_typst_markup(p.text.strip())
                    for p in page.header.content
                    if p.text.strip()
                )
                if hdr_txt:
                    args.append(f"header: align(right)[#text(size: 9pt)[{hdr_txt}]]")
            if page.footer and page.footer.content:
                ftr_txt = " ".join(
                    escape_typst_markup(p.text.strip())
                    for p in page.footer.content
                    if p.text.strip()
                )
                if ftr_txt:
                    args.append(f"footer: align(center)[#text(size: 9pt)[{ftr_txt}]]")

        return "#set page(\n  " + ",\n  ".join(args) + ",\n)"

    def build_text_setup(self, font_name: str, font_size: float) -> str:
        """Build #set text(...) directive with primary font and fallback stack."""
        safe_font = escape_typst_string(font_name)
        lang_short = escape_typst_string(self.language.split("-")[0] or "en")
        return (
            "#set text(\n"
            f'  font: ("{safe_font}", "Libertinus Serif", "DejaVu Sans"),\n'
            f"  size: {_format_pt(font_size)},\n"
            f'  lang: "{lang_short}",\n'
            ")"
        )

    def render_page(
        self,
        page: DocumentPage,
        image_counter: Optional[List[int]] = None,
    ) -> str:
        """Render all body blocks of a single DocumentPage into Typst markup."""
        from anyconvert.emitters.typst.content import render_typst_page_blocks

        counter = image_counter if image_counter is not None else [1]
        return render_typst_page_blocks(page.blocks, self.render_block, counter)

    def render_block(self, block: BlockNode, image_counter: List[int]) -> str:
        """Render a single BlockNode into Typst markup."""
        if isinstance(block, Paragraph):
            return self.render_paragraph(block)
        if isinstance(block, Table):
            return self.render_table(block)
        if isinstance(block, ImageBlock):
            return self.render_image(block, image_counter)
        if isinstance(block, VectorBlock):
            return ""
        return ""

    def render_paragraph(self, p: Paragraph) -> str:
        """Render a Paragraph node into Typst heading, list item, code block, or prose."""
        from anyconvert.emitters.typst.content import render_typst_paragraph

        return render_typst_paragraph(
            p,
            render_run_fn=lambda r, override, sup_bold: self.render_run(
                r, override_text=override, suppress_bold=sup_bold
            ),
            enable_math_heuristics=self.enable_math_heuristics,
        )

    def render_run(
        self,
        run: TextRun,
        override_text: Optional[str] = None,
        suppress_bold: bool = False,
    ) -> str:
        """Render an inline TextRun into idiomatic Typst markup."""
        from anyconvert.emitters.typst.content import render_typst_run

        return render_typst_run(
            run,
            override_text=override_text,
            suppress_bold=suppress_bold,
        )

    def render_table(self, table: Table) -> str:
        """Render a Table node into an idiomatic Typst #table(...) block."""
        from anyconvert.emitters.typst.content import render_typst_table

        return render_typst_table(
            table,
            render_run_fn=lambda r: self.render_run(r),
            enable_math_heuristics=self.enable_math_heuristics,
        )

    def render_image(self, img: ImageBlock, image_counter: List[int]) -> str:
        """Render an ImageBlock as an external #image(...) if extracted, or compilable figure placeholder."""
        idx = image_counter[0]
        image_counter[0] += 1
        img.sync_format()
        alt = img.alt_text.strip() if img.alt_text else f"Image {idx}"

        if self.image_dir is not None and img.image_bytes:
            ext = img.file_extension
            filename = f"img_{idx}{ext}"
            self.image_dir.mkdir(parents=True, exist_ok=True)
            target = self.image_dir / filename
            target.write_bytes(img.image_bytes)
            self.extracted_images.append(target)
            rel_ref = f"{self.image_dir.as_posix().rstrip('/')}/{filename}"
            return (
                f'#figure(\n  image("{escape_typst_string(rel_ref)}"),\n'
                f"  caption: [{escape_typst_markup(alt)}],\n)"
            )

        return (
            f"#figure(\n"
            f"  rect(inset: 8pt, stroke: 0.5pt + luma(160))[{escape_typst_markup(alt)}],\n"
            f"  caption: [{escape_typst_markup(alt)}],\n"
            f")"
        )


__all__ = [
    "TypstEmitter",
    "clean_typst_font_name",
    "escape_typst_string",
    "escape_typst_markup",
]
