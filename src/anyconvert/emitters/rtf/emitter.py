r"""Pure-Python RTF 1.9.1 document emitter and control-word architecture.

Generates valid 7-bit ASCII Rich Text Format (RTF 1.9.1) documents featuring:
- Dynamic font table (\fonttbl) with PDF subset-prefix stripping and family classification.
- Deduplicated color table (\colortbl) with auto-color entry 0.
- Word/LibreOffice compatible stylesheet (\stylesheet) for Normal and Heading 1-6.
- Document info metadata group (\info).
- Twip-accurate page geometry (\paperw, \paperh, \margl, \margr, \margt, \margb).
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from anyconvert.common.color import Color
from anyconvert.emitters.base import BaseEmitter, ConversionMode, pt_to_dxa, pt_to_half_pt
from anyconvert.exceptions import SerializationError
from anyconvert.ir.model import (
    Alignment,
    BlockNode,
    DocumentIR,
    DocumentPage,
    HeadingLevel,
    ImageBlock,
    Paragraph,
    Table,
    TextRun,
    VectorBlock,
)

# PDF embedded font subset tag pattern (e.g., "ABCDEF+Helvetica-Bold")
_SUBSET_PREFIX_RE = re.compile(r"^[A-Z]{6}\+")

_MONOSPACE_HINTS = (
    "mono",
    "courier",
    "consolas",
    "menlo",
    "monaco",
    "terminal",
    "sourcecode",
)
_SERIF_HINTS = (
    "times",
    "georgia",
    "garamond",
    "cambria",
    "palatino",
    "serif",
    "book",
    "baskerville",
)
_SANS_HINTS = (
    "helvetica",
    "arial",
    "calibri",
    "verdana",
    "tahoma",
    "segoe",
    "sans",
    "roboto",
    "inter",
    "open",
)
_TECH_HINTS = ("symbol", "wingdings", "webdings", "zapf")

# Standard stylesheet heading sizes in half-points (RTF \fsN)
_HEADING_HALF_PT: Dict[int, int] = {
    1: 40,  # 20 pt
    2: 32,  # 16 pt
    3: 28,  # 14 pt
    4: 24,  # 12 pt
    5: 22,  # 11 pt
    6: 20,  # 10 pt
}


def clean_rtf_font_name(raw_name: str) -> str:
    """Normalize a PDF font name into a clean RTF font face name."""
    if not raw_name or not raw_name.strip():
        return "Helvetica"
    cleaned = _SUBSET_PREFIX_RE.sub("", raw_name.strip())
    # Strip common PDF style suffixes after hyphen/comma
    base = re.split(r"[-,]", cleaned, maxsplit=1)[0].strip()
    base = base.replace(";", "").replace("{", "").replace("}", "").replace("\\", "")
    return base or "Helvetica"


def classify_rtf_font_family(font_name: str) -> str:
    """Map a font name to its RTF 1.9.1 font family control word."""
    low = font_name.lower().replace(" ", "").replace("-", "").replace("_", "")
    if any(k in low for k in _MONOSPACE_HINTS):
        return r"\fmodern"
    if any(k in low for k in _TECH_HINTS):
        return r"\ftech"
    if any(k in low for k in _SERIF_HINTS):
        return r"\froman"
    if any(k in low for k in _SANS_HINTS):
        return r"\fswiss"
    return r"\fnil"


def escape_rtf_text(text: str) -> str:
    """Escape text into strict 7-bit ASCII RTF syntax using \\uN? for non-ASCII characters."""
    if not text:
        return ""
    out: List[str] = []
    for ch in text:
        code = ord(ch)
        if ch == "\\":
            out.append(r"\\")
        elif ch == "{":
            out.append(r"\{")
        elif ch == "}":
            out.append(r"\}")
        elif ch == "\n":
            out.append(r"\line ")
        elif ch == "\t":
            out.append(r"\tab ")
        elif ch == "\r":
            continue
        elif 0x20 <= code <= 0x7E:
            out.append(ch)
        elif code < 0x20 or code == 0x7F:
            continue
        elif code <= 0xFFFF:
            signed = code if code <= 32767 else code - 65536
            out.append(f"\\u{signed}?")
        else:
            # Encode supplementary plane code points as UTF-16 surrogate pair
            cp = code - 0x10000
            high = 0xD800 + (cp >> 10)
            low = 0xDC00 + (cp & 0x3FF)
            out.append(f"\\u{high - 65536}?\\u{low - 65536}?")
    return "".join(out)


class RtfFontTable:
    """Registry of RTF font definitions for the \\fonttbl header group."""

    __slots__ = ("_fonts", "_index_by_name")

    def __init__(self, default_font: str = "Helvetica") -> None:
        self._fonts: List[Tuple[str, str]] = []
        self._index_by_name: Dict[str, int] = {}
        self.register(default_font)

    def register(self, raw_font_name: str) -> int:
        """Register a font name and return its 0-based RTF font index (\\fN)."""
        clean = clean_rtf_font_name(raw_font_name)
        key = clean.lower()
        if key in self._index_by_name:
            return self._index_by_name[key]
        idx = len(self._fonts)
        family = classify_rtf_font_family(clean)
        self._fonts.append((clean, family))
        self._index_by_name[key] = idx
        return idx

    def get_index(self, raw_font_name: str) -> int:
        """Return existing or newly registered font index."""
        return self.register(raw_font_name)

    def to_rtf(self) -> str:
        """Serialize the \\fonttbl group."""
        entries = [
            f"{{\\f{idx}{family}\\fcharset0 {escape_rtf_text(name)};}}"
            for idx, (name, family) in enumerate(self._fonts)
        ]
        return "{\\fonttbl" + "".join(entries) + "}"


class RtfColorTable:
    """Registry of RGB colors for the \\colortbl header group (index 0 = auto)."""

    __slots__ = ("_colors", "_index_by_rgb")

    def __init__(self) -> None:
        self._colors: List[Tuple[int, int, int]] = []
        self._index_by_rgb: Dict[Tuple[int, int, int], int] = {}
        self.register(Color(0, 0, 0))

    def register(self, color: Optional[Color]) -> int:
        """Register a Color and return its 1-based RTF color index (0 = auto)."""
        if color is None:
            return 0
        rgb = (
            max(0, min(255, int(color.r))),
            max(0, min(255, int(color.g))),
            max(0, min(255, int(color.b))),
        )
        if rgb in self._index_by_rgb:
            return self._index_by_rgb[rgb]
        # Index 0 is reserved for the empty auto-color slot (';')
        idx = len(self._colors) + 1
        self._colors.append(rgb)
        self._index_by_rgb[rgb] = idx
        return idx

    def to_rtf(self) -> str:
        """Serialize the \\colortbl group."""
        entries = [f"\\red{r}\\green{g}\\blue{b};" for r, g, b in self._colors]
        return "{\\colortbl ;" + "".join(entries) + "}"


class RtfStyleSheet:
    """RTF 1.9.1 \\stylesheet definition for Normal (\\s0) and Heading 1-6 (\\s1-\\s6)."""

    __slots__ = ("default_font_idx", "body_half_pt")

    def __init__(self, default_font_idx: int = 0, body_half_pt: int = 22) -> None:
        self.default_font_idx = default_font_idx
        self.body_half_pt = body_half_pt

    def to_rtf(self) -> str:
        """Serialize the \\stylesheet group."""
        f_idx = self.default_font_idx
        lines: List[str] = [
            "{\\stylesheet",
            f"{{\\s0\\ql\\li0\\ri0\\sa120\\sl276\\slmult1\\f{f_idx}\\fs{self.body_half_pt} Normal;}}",
        ]
        for lvl in range(1, 7):
            fs = _HEADING_HALF_PT[lvl]
            outline = lvl - 1
            sb = 240 if lvl <= 2 else 180
            sa = 120 if lvl <= 2 else 80
            lines.append(
                f"{{\\s{lvl}\\ql\\sb{sb}\\sa{sa}\\keepn\\outlinelevel{outline}"
                f"\\b\\f{f_idx}\\fs{fs} heading {lvl};}}"
            )
        lines.append("}")
        return "\n".join(lines)


class RtfEmitter(BaseEmitter):
    """Pure-Python RTF 1.9.1 document emitter generating valid 7-bit ASCII RTF streams."""

    __slots__ = ("default_font", "default_codepage", "default_lang")

    def __init__(
        self,
        default_font: str = "Helvetica",
        default_codepage: int = 1252,
        default_lang: int = 1033,
    ) -> None:
        self.default_font = default_font
        self.default_codepage = default_codepage
        self.default_lang = default_lang

    def emit(
        self,
        doc_ir: DocumentIR,
        mode: ConversionMode = ConversionMode.FLOW,
    ) -> bytes:
        """Serialize DocumentIR into 7-bit ASCII RTF 1.9.1 bytes.

        Args:
            doc_ir: Validated DocumentIR structure.
            mode: Layout mode (informational; RTF uses reflowable control words).

        Returns:
            ASCII-encoded bytes of the RTF 1.9.1 document.

        Raises:
            SerializationError: If doc_ir contains no pages.
        """
        if not doc_ir.pages:
            raise SerializationError("Cannot emit RTF from empty DocumentIR")

        rtf_str = self.render(doc_ir)
        return rtf_str.encode("ascii")

    def render(self, doc_ir: DocumentIR) -> str:
        """Render DocumentIR into a complete 7-bit ASCII RTF 1.9.1 string."""
        if not doc_ir.pages:
            raise SerializationError("Cannot emit RTF from empty DocumentIR")

        font_table = RtfFontTable(default_font=self.default_font)
        color_table = RtfColorTable()
        stylesheet = RtfStyleSheet(default_font_idx=0)

        # Pre-scan all runs, tables, and headers/footers to populate font and color tables
        self._prescan_resources(doc_ir, font_table, color_table)

        parts: List[str] = [
            f"{{\\rtf1\\ansi\\ansicpg{self.default_codepage}\\deff0\\nouicompat\\deflang{self.default_lang}",
            font_table.to_rtf(),
            color_table.to_rtf(),
            stylesheet.to_rtf(),
        ]

        info_group = self._build_info_group(doc_ir.metadata)
        if info_group:
            parts.append(info_group)

        # Document-level page setup from first page
        first_page = doc_ir.pages[0]
        parts.append(self._build_page_setup(first_page))
        parts.append("\\viewkind4\\uc1")

        # Render pages sequentially
        for page_idx, page in enumerate(doc_ir.pages):
            if page_idx > 0:
                prev_page = doc_ir.pages[page_idx - 1]
                if (
                    abs(page.width - prev_page.width) > 1.0
                    or abs(page.height - prev_page.height) > 1.0
                ):
                    parts.append(self._build_section_break(page))
                else:
                    parts.append("\\page")
            parts.extend(self._render_page(page, font_table, color_table))

        parts.append("}")
        return "\n".join(parts) + "\n"

    def _prescan_resources(
        self,
        doc_ir: DocumentIR,
        font_table: RtfFontTable,
        color_table: RtfColorTable,
    ) -> None:
        """Register all fonts and colors appearing anywhere in DocumentIR."""
        for page in doc_ir.pages:
            if page.header:
                for p in page.header.content:
                    self._prescan_paragraph(p, font_table, color_table)
            for block in page.blocks:
                self._prescan_block(block, font_table, color_table)
            if page.footer:
                for p in page.footer.content:
                    self._prescan_paragraph(p, font_table, color_table)

    def _prescan_block(
        self,
        block: BlockNode,
        font_table: RtfFontTable,
        color_table: RtfColorTable,
    ) -> None:
        if isinstance(block, Paragraph):
            self._prescan_paragraph(block, font_table, color_table)
        elif isinstance(block, Table):
            for row in block.rows:
                for cell in row.cells:
                    if cell.background_color is not None:
                        color_table.register(cell.background_color)
                    for border in cell.borders.values():
                        color_table.register(border.color)
                    for sub in cell.content:
                        self._prescan_block(sub, font_table, color_table)

    def _prescan_paragraph(
        self,
        p: Paragraph,
        font_table: RtfFontTable,
        color_table: RtfColorTable,
    ) -> None:
        for run in p.runs:
            if run.font_name:
                font_table.register(run.font_name)
            color_table.register(run.color)

    def _build_info_group(self, metadata: Dict[str, str]) -> str:
        """Build the optional RTF \\info metadata group."""
        if not metadata:
            return ""
        lowered = {k.lstrip("/").lower(): v.strip() for k, v in metadata.items() if v and v.strip()}
        entries: List[str] = []
        if "title" in lowered:
            entries.append(f"{{\\title {escape_rtf_text(lowered['title'])}}}")
        if "author" in lowered:
            entries.append(f"{{\\author {escape_rtf_text(lowered['author'])}}}")
        if "subject" in lowered:
            entries.append(f"{{\\subject {escape_rtf_text(lowered['subject'])}}}")
        if "keywords" in lowered:
            entries.append(f"{{\\keywords {escape_rtf_text(lowered['keywords'])}}}")
        if not entries:
            return ""
        entries.append("{\\operator anyconvert}")
        return "{\\info" + "".join(entries) + "}"

    def _build_page_setup(self, page: DocumentPage) -> str:
        """Emit document-level page size and margin control words in twips."""
        paperw = max(1440, pt_to_dxa(page.width))
        paperh = max(1440, pt_to_dxa(page.height))
        margl = max(0, pt_to_dxa(page.margin_left))
        margr = max(0, pt_to_dxa(page.margin_right))
        margt = max(0, pt_to_dxa(page.margin_top))
        margb = max(0, pt_to_dxa(page.margin_bottom))
        landscape = "\\landscape" if paperw > paperh else ""
        return (
            f"\\paperw{paperw}\\paperh{paperh}"
            f"\\margl{margl}\\margr{margr}\\margt{margt}\\margb{margb}{landscape}"
        )

    def _build_section_break(self, page: DocumentPage) -> str:
        """Emit an RTF section break with updated page dimensions in twips."""
        pgw = max(1440, pt_to_dxa(page.width))
        pgh = max(1440, pt_to_dxa(page.height))
        margl = max(0, pt_to_dxa(page.margin_left))
        margr = max(0, pt_to_dxa(page.margin_right))
        margt = max(0, pt_to_dxa(page.margin_top))
        margb = max(0, pt_to_dxa(page.margin_bottom))
        orient = "\\lndscpsxn" if pgw > pgh else ""
        return (
            f"\\sect\\sectd\\pgwsxn{pgw}\\pghsxn{pgh}"
            f"\\marglsxn{margl}\\margrsxn{margr}\\margtsxn{margt}\\margbsxn{margb}{orient}"
        )

    def _render_page(
        self,
        page: DocumentPage,
        font_table: RtfFontTable,
        color_table: RtfColorTable,
    ) -> List[str]:
        """Render a single DocumentPage into RTF control-word paragraphs."""
        lines: List[str] = []

        if page.header and page.header.content:
            hdr_body = "".join(
                self.render_paragraph(p, font_table, color_table) for p in page.header.content
            )
            if hdr_body:
                lines.append(f"{{\\header {hdr_body}}}")

        if page.footer and page.footer.content:
            ftr_body = "".join(
                self.render_paragraph(p, font_table, color_table) for p in page.footer.content
            )
            if ftr_body:
                lines.append(f"{{\\footer {ftr_body}}}")

        for block in page.blocks:
            rendered = self.render_block(block, font_table, color_table)
            if rendered:
                lines.append(rendered)

        return lines

    def render_block(
        self,
        block: BlockNode,
        font_table: RtfFontTable,
        color_table: RtfColorTable,
    ) -> str:
        """Render a single BlockNode into RTF control words."""
        if isinstance(block, Paragraph):
            return self.render_paragraph(block, font_table, color_table)
        if isinstance(block, Table):
            return self.render_table(block, font_table, color_table)
        if isinstance(block, ImageBlock):
            return self.render_image(block)
        if isinstance(block, VectorBlock):
            return ""
        return ""

    def render_paragraph(
        self,
        p: Paragraph,
        font_table: RtfFontTable,
        color_table: RtfColorTable,
    ) -> str:
        """Render a Paragraph into an RTF \\pard ... \\par block."""
        runs_rtf = "".join(self.render_run(r, font_table, color_table) for r in p.runs)
        if not runs_rtf:
            return ""

        ctrl: List[str] = ["\\pard"]

        if p.heading_level is not None:
            lvl = max(1, min(6, p.heading_level.value))
            ctrl.append(f"\\s{lvl}\\outlinelevel{lvl - 1}\\keepn")
        else:
            ctrl.append("\\s0")

        align_map = {
            Alignment.LEFT: "\\ql",
            Alignment.CENTER: "\\qc",
            Alignment.RIGHT: "\\qr",
            Alignment.JUSTIFIED: "\\qj",
        }
        ctrl.append(align_map.get(p.alignment, "\\ql"))

        if p.indent_left > 0.0:
            ctrl.append(f"\\li{pt_to_dxa(p.indent_left)}")
        if p.indent_right > 0.0:
            ctrl.append(f"\\ri{pt_to_dxa(p.indent_right)}")
        if abs(p.indent_first_line) > 0.0:
            ctrl.append(f"\\fi{pt_to_dxa(p.indent_first_line)}")
        if p.space_before > 0.0:
            ctrl.append(f"\\sb{pt_to_dxa(p.space_before)}")
        if p.space_after > 0.0:
            ctrl.append(f"\\sa{pt_to_dxa(p.space_after)}")
        else:
            ctrl.append("\\sa120")

        prefix = ""
        if p.list_marker:
            indent_twips = pt_to_dxa(18.0 * (max(0, p.list_level) + 1))
            ctrl.append(f"\\li{indent_twips}\\fi-360")
            prefix = f"{escape_rtf_text(p.list_marker.strip())}\\tab "

        return "".join(ctrl) + " " + prefix + runs_rtf + "\\par"

    def render_run(
        self,
        run: TextRun,
        font_table: RtfFontTable,
        color_table: RtfColorTable,
    ) -> str:
        """Render an inline TextRun wrapped in an RTF character formatting group."""
        if not run.text:
            return ""

        f_idx = font_table.get_index(run.font_name)
        fs = max(2, pt_to_half_pt(run.font_size if run.font_size > 0 else 11.0))
        cf_idx = color_table.register(run.color)

        attrs: List[str] = [f"\\f{f_idx}", f"\\fs{fs}", f"\\cf{cf_idx}"]
        if run.is_bold:
            attrs.append("\\b")
        if run.is_italic:
            attrs.append("\\i")
        if run.is_underline:
            attrs.append("\\ul")
        if run.is_strikethrough:
            attrs.append("\\strike")
        if run.baseline_offset > 0.5:
            attrs.append("\\super")
        elif run.baseline_offset < -0.5:
            attrs.append("\\sub")

        escaped = escape_rtf_text(run.text)
        return "{" + "".join(attrs) + " " + escaped + "}"

    def render_table(
        self,
        table: Table,
        font_table: RtfFontTable,
        color_table: RtfColorTable,
    ) -> str:
        """Render a basic RTF table row sequence (extended in tables.py)."""
        if not table.rows:
            return ""

        num_cols = max((len(r.cells) for r in table.rows), default=0)
        if num_cols == 0:
            return ""

        default_cell_w = max(1440, 9360 // num_cols)
        lines: List[str] = []
        for row in table.rows:
            cell_defs: List[str] = ["\\trowd\\trgaph108"]
            cell_bodies: List[str] = []
            right_x = 0
            for idx, cell in enumerate(row.cells):
                w_twips = (
                    pt_to_dxa(cell.width)
                    if cell.width > 0
                    else (
                        pt_to_dxa(table.col_widths[idx])
                        if idx < len(table.col_widths) and table.col_widths[idx] > 0
                        else default_cell_w
                    )
                )
                right_x += max(360, w_twips)
                cell_defs.append(f"\\cellx{right_x}")
                cell_parts: List[str] = []
                for sub in cell.content:
                    if isinstance(sub, Paragraph):
                        cell_parts.append(
                            "".join(self.render_run(r, font_table, color_table) for r in sub.runs)
                        )
                cell_bodies.append("\\pard\\intbl " + "\\line ".join(cell_parts) + "\\cell")
            lines.append("".join(cell_defs) + "".join(cell_bodies) + "\\row")
        return "\n".join(lines)

    def render_image(self, img: ImageBlock) -> str:
        """Render an ImageBlock placeholder (binary \\pict embedding added in pictures.py)."""
        alt = img.alt_text.strip() if img.alt_text else "Image"
        return f"\\pard\\s0\\qc\\sa120 [{escape_rtf_text(alt)}]\\par"


__all__ = [
    "RtfEmitter",
    "RtfFontTable",
    "RtfColorTable",
    "RtfStyleSheet",
    "clean_rtf_font_name",
    "classify_rtf_font_family",
    "escape_rtf_text",
]
