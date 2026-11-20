r"""RTF 1.9.1 paragraph styles, heading hierarchy, indentation, and run formatting.

Translates DocumentIR Paragraph and TextRun attributes into Word/LibreOffice
compliant RTF control words:
- Stylesheet (\stylesheet) with Normal (\s0), Heading 1-6 (\s1-\s6), List (\s7),
  Quote (\s8), Header (\s9), and Footer (\s10).
- Alignment (\ql, \qc, \qr, \qj), indentations (\liN, \riN, \fiN, \txN),
  vertical spacing (\sbN, \saN), and proportional line spacing (\slN\slmult1).
- Character typography (\fN, \fsN, \cfN, \b, \i, \ul, \strike, \super, \sub, \expndtwN).
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

from anyconvert.emitters.base import pt_to_dxa, pt_to_half_pt
from anyconvert.emitters.rtf.unicode import encode_rtf_unicode
from anyconvert.ir.model import Alignment, HeadingLevel, Paragraph, TextRun

# Style indices matching RtfStyleSheet
STYLE_NORMAL = 0
STYLE_HEADING_BASE = 0  # H1 -> 1 .. H6 -> 6
STYLE_LIST = 7
STYLE_QUOTE = 8
STYLE_HEADER = 9
STYLE_FOOTER = 10

# Standard heading font sizes in half-points (\fsN)
HEADING_HALF_PT: Dict[int, int] = {
    1: 40,  # 20 pt
    2: 32,  # 16 pt
    3: 28,  # 14 pt
    4: 24,  # 12 pt
    5: 22,  # 11 pt
    6: 20,  # 10 pt
}

# Default heading spacing (space_before_twips, space_after_twips)
HEADING_DEFAULT_SPACING: Dict[int, Tuple[int, int]] = {
    1: (280, 140),
    2: (240, 120),
    3: (180, 80),
    4: (160, 80),
    5: (140, 60),
    6: (120, 60),
}

_ALIGN_CONTROL: Dict[Alignment, str] = {
    Alignment.LEFT: r"\ql",
    Alignment.CENTER: r"\qc",
    Alignment.RIGHT: r"\qr",
    Alignment.JUSTIFIED: r"\qj",
}


class RtfStyleSheet:
    """RTF 1.9.1 \\stylesheet definition for Normal, Heading 1-6, List, Quote, and Marginals."""

    __slots__ = ("default_font_idx", "body_half_pt")

    def __init__(self, default_font_idx: int = 0, body_half_pt: int = 22) -> None:
        self.default_font_idx = default_font_idx
        self.body_half_pt = body_half_pt

    def to_rtf(self) -> str:
        """Serialize the complete \\stylesheet header group."""
        f_idx = self.default_font_idx
        lines: List[str] = [
            "{\\stylesheet",
            (
                f"{{\\s{STYLE_NORMAL}\\ql\\li0\\ri0\\sa120\\sl276\\slmult1"
                f"\\widctlpar\\f{f_idx}\\fs{self.body_half_pt} Normal;}}"
            ),
        ]
        for lvl in range(1, 7):
            fs = HEADING_HALF_PT[lvl]
            sb, sa = HEADING_DEFAULT_SPACING[lvl]
            outline = lvl - 1
            lines.append(
                f"{{\\s{lvl}\\ql\\sb{sb}\\sa{sa}\\keepn\\widctlpar"
                f"\\outlinelevel{outline}\\snext0\\b\\f{f_idx}\\fs{fs} heading {lvl};}}"
            )
        lines.append(
            f"{{\\s{STYLE_LIST}\\ql\\li720\\fi-360\\sa60\\widctlpar"
            f"\\f{f_idx}\\fs{self.body_half_pt} List Paragraph;}}"
        )
        lines.append(
            f"{{\\s{STYLE_QUOTE}\\ql\\li720\\ri720\\sa120\\widctlpar"
            f"\\i\\f{f_idx}\\fs{self.body_half_pt} Quote;}}"
        )
        lines.append(
            f"{{\\s{STYLE_HEADER}\\ql\\sa0\\f{f_idx}\\fs18 Header;}}"
        )
        lines.append(
            f"{{\\s{STYLE_FOOTER}\\ql\\sa0\\f{f_idx}\\fs18 Footer;}}"
        )
        lines.append("}")
        return "\n".join(lines)


def format_alignment(alignment: Alignment) -> str:
    """Translate IR Alignment enum to RTF alignment control word."""
    return _ALIGN_CONTROL.get(alignment, r"\ql")


def format_line_spacing(line_spacing: float) -> str:
    """Translate proportional line spacing multiplier into RTF \\slN\\slmult1."""
    if not (0.5 <= line_spacing <= 4.0):
        return ""
    sl_val = max(120, int(round(line_spacing * 240.0)))
    return f"\\sl{sl_val}\\slmult1"


def resolve_paragraph_style_index(p: Paragraph, role: Optional[str] = None) -> int:
    """Resolve the RTF stylesheet index (\\sN) for a Paragraph node."""
    if role == "header":
        return STYLE_HEADER
    if role == "footer":
        return STYLE_FOOTER
    if p.heading_level is not None:
        return max(1, min(6, p.heading_level.value))
    if p.list_marker:
        return STYLE_LIST
    return STYLE_NORMAL


def format_paragraph_controls(
    p: Paragraph,
    in_table: bool = False,
    role: Optional[str] = None,
) -> Tuple[str, int]:
    """Generate RTF paragraph control words (\\pard...) and list hanging indent twips.

    Returns:
        Tuple of (rtf_control_string, list_tab_twips).
    """
    ctrl: List[str] = ["\\pard"]
    if in_table:
        ctrl.append("\\intbl")

    style_idx = resolve_paragraph_style_index(p, role=role)
    ctrl.append(f"\\s{style_idx}")

    if p.heading_level is not None and role not in ("header", "footer"):
        lvl = max(1, min(6, p.heading_level.value))
        ctrl.append(f"\\outlinelevel{lvl - 1}\\keepn")

    ctrl.append("\\widctlpar")
    ctrl.append(format_alignment(p.alignment))

    # Resolve indentations cleanly without duplicate \li or \fi tokens
    li_twips = max(0, pt_to_dxa(p.indent_left)) if p.indent_left > 0.0 else 0
    ri_twips = max(0, pt_to_dxa(p.indent_right)) if p.indent_right > 0.0 else 0
    fi_twips = pt_to_dxa(p.indent_first_line) if abs(p.indent_first_line) > 0.0 else 0
    list_tab_twips = 0

    if p.list_marker and not in_table:
        level_indent = pt_to_dxa(18.0 * (max(0, p.list_level) + 1))
        li_twips = max(li_twips, level_indent)
        fi_twips = -360
        list_tab_twips = li_twips

    if li_twips != 0:
        ctrl.append(f"\\li{li_twips}")
    if ri_twips != 0:
        ctrl.append(f"\\ri{ri_twips}")
    if fi_twips != 0:
        ctrl.append(f"\\fi{fi_twips}")
    if list_tab_twips > 0:
        ctrl.append(f"\\tx{list_tab_twips}")

    # Vertical paragraph spacing (\sbN, \saN)
    if p.space_before > 0.0:
        ctrl.append(f"\\sb{pt_to_dxa(p.space_before)}")
    elif p.heading_level is not None and role not in ("header", "footer"):
        sb_def, _ = HEADING_DEFAULT_SPACING[max(1, min(6, p.heading_level.value))]
        ctrl.append(f"\\sb{sb_def}")

    if p.space_after > 0.0:
        ctrl.append(f"\\sa{pt_to_dxa(p.space_after)}")
    elif p.heading_level is not None and role not in ("header", "footer"):
        _, sa_def = HEADING_DEFAULT_SPACING[max(1, min(6, p.heading_level.value))]
        ctrl.append(f"\\sa{sa_def}")
    elif p.list_marker:
        ctrl.append("\\sa60")
    elif not in_table and role not in ("header", "footer"):
        ctrl.append("\\sa120")

    # Line spacing (\slN\slmult1)
    if abs(p.line_spacing - 1.0) > 0.01:
        sl_ctrl = format_line_spacing(p.line_spacing)
        if sl_ctrl:
            ctrl.append(sl_ctrl)

    return "".join(ctrl), list_tab_twips


def format_run_rtf(
    run: TextRun,
    font_index: int,
    color_index: int,
    codepage: int = 1252,
    override_text: Optional[str] = None,
) -> str:
    """Render an inline TextRun into an RTF formatted character group."""
    raw_text = override_text if override_text is not None else run.text
    if not raw_text:
        return ""

    fs = max(2, pt_to_half_pt(run.font_size if run.font_size > 0 else 11.0))
    attrs: List[str] = [f"\\f{font_index}", f"\\fs{fs}", f"\\cf{color_index}"]

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
    if abs(run.tracking) > 0.05:
        attrs.append(f"\\expndtw{pt_to_dxa(run.tracking)}")

    escaped = encode_rtf_unicode(raw_text, codepage=codepage)
    return "{" + "".join(attrs) + " " + escaped + "}"


def build_paragraph_rtf(
    p: Paragraph,
    render_run_fn: Callable[[TextRun, Optional[str]], str],
    codepage: int = 1252,
    in_table: bool = False,
    role: Optional[str] = None,
) -> str:
    """Assemble a complete RTF paragraph (\\pard ... \\par) with styles and list markers."""
    marker = p.list_marker.strip() if p.list_marker else ""
    strip_marker = bool(marker and p.runs and p.runs[0].text.lstrip().startswith(marker))

    run_parts: List[str] = []
    for idx, run in enumerate(p.runs):
        if idx == 0 and strip_marker:
            stripped = run.text.lstrip()[len(marker) :].lstrip()
            if stripped:
                run_parts.append(render_run_fn(run, stripped))
        else:
            rendered = render_run_fn(run, None)
            if rendered:
                run_parts.append(rendered)

    runs_rtf = "".join(run_parts)
    if not runs_rtf:
        return ""

    ctrl_str, _ = format_paragraph_controls(p, in_table=in_table, role=role)
    prefix = ""
    if marker and not in_table:
        prefix = f"{encode_rtf_unicode(marker, codepage=codepage)}\\tab "

    suffix = "" if in_table else "\\par"
    return f"{ctrl_str} {prefix}{runs_rtf}{suffix}"


__all__ = [
    "STYLE_NORMAL",
    "STYLE_LIST",
    "STYLE_QUOTE",
    "STYLE_HEADER",
    "STYLE_FOOTER",
    "HEADING_HALF_PT",
    "HEADING_DEFAULT_SPACING",
    "RtfStyleSheet",
    "format_alignment",
    "format_line_spacing",
    "resolve_paragraph_style_index",
    "format_paragraph_controls",
    "format_run_rtf",
    "build_paragraph_rtf",
]
