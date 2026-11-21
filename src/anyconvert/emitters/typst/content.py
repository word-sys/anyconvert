"""Idiomatic Typst (.typ) content, inline formatting, list, code block, and #table translator.

Translates DocumentIR blocks into clean, human-editable Typst markup ready for
`typst compile`:
- Headings (`=`, `==`, `===`, ...) with clean inline typography.
- Idiomatic inline styling (`*bold*`, `_italic_`, `` `code` ``, `#underline[...]`,
  `#strike[...]`, `#super[...]`, `#sub[...]`, `#link("...")[...]`, `#text(fill: ...)[...]`).
- Grouped unordered (`-`) and ordered (`+`) lists and fenced raw code blocks.
- Native `#table(...)` with `columns`, per-column `align`, `table.header(...)`,
  and `table.cell(colspan: ..., rowspan: ..., fill: ...)` with occupancy-grid tracking.
"""

from __future__ import annotations

import re
from typing import Callable, List, Optional, Sequence, Tuple

from anyconvert.emitters.base import color_to_hex
from anyconvert.emitters.typst.emitter import (
    _format_pt,
    escape_typst_markup,
    escape_typst_string,
)
from anyconvert.ir.model import (
    Alignment,
    BlockNode,
    Paragraph,
    Table,
    TableCell,
    TextRun,
)

_MONOSPACE_HINTS = (
    "mono",
    "courier",
    "consolas",
    "menlo",
    "monaco",
    "terminal",
    "sourcecode",
)

_UNORDERED_BULLET_CHARS = frozenset({"•", "·", "○", "●", "▪", "■", "▫", "–", "—", "*", "-", "+"})
_URL_RE = re.compile(r"^(https?://|mailto:)[^\s]+$")
_NUMERIC_CELL_RE = re.compile(r"^[\$€£¥₽₹]?\s*-?\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*%?$")


def is_monospace_font(font_name: str) -> bool:
    """Return True if font_name indicates a monospace typeface."""
    if not font_name:
        return False
    low = font_name.lower().replace("-", "").replace("_", "").replace(" ", "")
    return any(k in low for k in _MONOSPACE_HINTS)


def is_code_paragraph(p: Paragraph) -> bool:
    """Return True if Paragraph is a standalone monospace code block."""
    if p.heading_level is not None or p.list_marker:
        return False
    non_empty = [r for r in p.runs if r.text.strip()]
    if not non_empty:
        return False
    return all(is_monospace_font(r.font_name) for r in non_empty)


def render_typst_code_block(code_text: str) -> str:
    """Render preformatted monospace text into a Typst fenced raw block."""
    fence = "```"
    if "```" in code_text:
        matches = list(re.finditer(r"`+", code_text))
        max_bt = max((len(m.group(0)) for m in matches), default=3)
        fence = "`" * max(3, max_bt + 1)
    return f"{fence}\n{code_text}\n{fence}"


def render_typst_run(
    run: TextRun,
    override_text: Optional[str] = None,
    suppress_bold: bool = False,
) -> str:
    """Render an inline TextRun using idiomatic Typst (*bold*, _italic_, `code`)."""
    raw = override_text if override_text is not None else run.text
    if not raw:
        return ""

    # Separate outer horizontal whitespace so *bold* and _italic_ delimiters hug words cleanly
    stripped_core = raw.strip(" ")
    if not stripped_core:
        return escape_typst_markup(raw)

    lead_len = len(raw) - len(raw.lstrip(" "))
    trail_len = len(raw) - len(raw.rstrip(" "))
    lead_ws = " " * lead_len
    trail_ws = " " * trail_len

    is_mono = is_monospace_font(run.font_name)
    if is_mono:
        if "`" not in stripped_core:
            core = f"`{stripped_core}`"
        else:
            core = f"`` {stripped_core} ``"
    else:
        core = escape_typst_markup(stripped_core)

    use_bold = run.is_bold and not suppress_bold
    use_italic = run.is_italic

    # Use idiomatic *...* and _..._ when core has no newlines; otherwise function syntax
    has_newline = "\n" in stripped_core
    if use_bold and use_italic:
        core = f"#strong[#emph[{core}]]" if has_newline else f"*_{core}_*"
    elif use_bold:
        core = f"#strong[{core}]" if has_newline else f"*{core}*"
    elif use_italic:
        core = f"#emph[{core}]" if has_newline else f"_{core}_"

    if run.is_underline:
        core = f"#underline[{core}]"
    if run.is_strikethrough:
        core = f"#strike[{core}]"
    if run.baseline_offset > 0.5:
        core = f"#super[{core}]"
    elif run.baseline_offset < -0.5:
        core = f"#sub[{core}]"

    if run.color and (run.color.r, run.color.g, run.color.b) != (0, 0, 0):
        hex_rgb = color_to_hex(run.color)
        core = f'#text(fill: rgb("#{hex_rgb}"))[{core}]'

    if _URL_RE.match(stripped_core) and not is_mono:
        core = f'#link("{escape_typst_string(stripped_core)}")[{core}]'

    return f"{lead_ws}{core}{trail_ws}"


def is_list_paragraph(p: Paragraph) -> Tuple[bool, str]:
    """Return (is_list, marker_prefix) where marker_prefix is '-' or '+'."""
    if p.heading_level is not None:
        return False, ""
    if p.list_marker:
        marker = p.list_marker.strip()
        if marker.endswith(".") or marker.endswith(")") or marker.isdigit():
            return True, "+"
        return True, "-"
    return False, ""


def render_typst_paragraph(
    p: Paragraph,
    render_run_fn: Optional[Callable[[TextRun, Optional[str], bool], str]] = None,
) -> str:
    """Render a Paragraph into a Typst heading (=, ==), list item (- / +), code block, or prose."""
    run_renderer = render_run_fn or render_typst_run

    if is_code_paragraph(p):
        return render_typst_code_block(p.text)

    is_heading = p.heading_level is not None
    marker = p.list_marker.strip() if p.list_marker else ""
    strip_leading_marker = bool(
        marker and not is_heading and p.runs and p.runs[0].text.lstrip().startswith(marker)
    )

    # Headings in Typst are already bold by default; keep explicit bold if partial, or render cleanly
    all_runs_bold = is_heading and all(
        r.is_bold for r in p.runs if r.text.strip()
    )

    parts: List[str] = []
    for idx, run in enumerate(p.runs):
        override: Optional[str] = None
        if idx == 0 and strip_leading_marker:
            override = run.text.lstrip()[len(marker) :].lstrip()
        parts.append(run_renderer(run, override, all_runs_bold))

    body = "".join(parts).strip()
    if not body:
        return ""

    if is_heading and p.heading_level is not None:
        lvl = max(1, min(6, p.heading_level.value))
        return f"{'=' * lvl} {body}"

    is_list, list_tok = is_list_paragraph(p)
    if is_list:
        indent = "  " * max(0, p.list_level)
        return f"{indent}{list_tok} {body}"

    if p.alignment == Alignment.CENTER:
        return f"#align(center)[{body}]"
    if p.alignment == Alignment.RIGHT:
        return f"#align(right)[{body}]"
    if p.alignment == Alignment.JUSTIFIED:
        return f"#par(justify: true)[{body}]"

    return body


def render_typst_page_blocks(
    blocks: Sequence[BlockNode],
    render_block_fn: Callable[[BlockNode, List[int]], str],
    image_counter: List[int],
) -> str:
    """Render a page's blocks, grouping consecutive code blocks and tightening list spacing."""
    out_chunks: List[str] = []
    n = len(blocks)
    i = 0

    while i < n:
        block = blocks[i]

        # 1. Group consecutive monospace code paragraphs into a single fenced raw block
        if isinstance(block, Paragraph) and is_code_paragraph(block):
            code_lines: List[str] = [block.text]
            i += 1
            while i < n:
                nxt = blocks[i]
                if isinstance(nxt, Paragraph) and is_code_paragraph(nxt):
                    code_lines.append(nxt.text)
                    i += 1
                else:
                    break
            out_chunks.append(render_typst_code_block("\n".join(code_lines)))
            continue

        # 2. Group consecutive list items with single-newline separation
        if isinstance(block, Paragraph) and is_list_paragraph(block)[0]:
            list_lines: List[str] = []
            while i < n:
                nxt = blocks[i]
                if isinstance(nxt, Paragraph) and is_list_paragraph(nxt)[0]:
                    rendered_item = render_block_fn(nxt, image_counter)
                    if rendered_item:
                        list_lines.append(rendered_item)
                    i += 1
                else:
                    break
            if list_lines:
                out_chunks.append("\n".join(list_lines))
            continue

        rendered = render_block_fn(block, image_counter)
        if rendered:
            out_chunks.append(rendered)
        i += 1

    return "\n\n".join(out_chunks)


def _format_cell_body(
    cell: TableCell,
    render_run_fn: Callable[[TextRun], str],
) -> str:
    """Render inner Paragraphs of a TableCell into Typst content."""
    para_strs: List[str] = []
    for sub in cell.content:
        if isinstance(sub, Paragraph):
            txt = "".join(render_run_fn(r) for r in sub.runs).strip()
            if txt:
                para_strs.append(txt)
    return " \\\n    ".join(para_strs)


def _detect_typst_col_alignments(
    table: Table,
    num_cols: int,
) -> List[str]:
    """Resolve Typst column alignments ('left', 'center', 'right') per column."""
    votes: List[List[Alignment]] = [[] for _ in range(num_cols)]
    num_rows = len(table.rows)
    occupied: List[List[bool]] = [[False] * num_cols for _ in range(num_rows)]

    for r_idx, row in enumerate(table.rows):
        c_idx = 0
        for cell in row.cells:
            while c_idx < num_cols and occupied[r_idx][c_idx]:
                c_idx += 1
            if c_idx >= num_cols:
                break
            cspan = max(1, min(cell.col_span, num_cols - c_idx))
            rspan = max(1, min(cell.row_span, num_rows - r_idx))
            for dr in range(rspan):
                for dc in range(cspan):
                    occupied[r_idx + dr][c_idx + dc] = True

            cell_align: Optional[Alignment] = None
            raw_txt = ""
            for b in cell.content:
                if isinstance(b, Paragraph):
                    raw_txt += b.text.strip()
                    if b.alignment != Alignment.LEFT:
                        cell_align = b.alignment
            if cell_align is not None:
                votes[c_idx].append(cell_align)
            elif not row.is_header and r_idx > 0 and _NUMERIC_CELL_RE.match(raw_txt):
                votes[c_idx].append(Alignment.RIGHT)
            elif raw_txt:
                votes[c_idx].append(Alignment.LEFT)
            c_idx += cspan

    has_non_left = any(
        any(v in (Alignment.RIGHT, Alignment.CENTER) for v in col_v)
        for col_v in votes
    )

    align_names = {
        Alignment.LEFT: "left",
        Alignment.CENTER: "center",
        Alignment.RIGHT: "right",
        Alignment.JUSTIFIED: "left",
    }

    if not has_non_left:
        fallback = align_names.get(table.alignment, "left")
        return [fallback] * num_cols

    resolved: List[str] = []
    for c in range(num_cols):
        col_v = votes[c]
        if not col_v:
            resolved.append("left")
            continue
        rights = sum(1 for v in col_v if v == Alignment.RIGHT)
        centers = sum(1 for v in col_v if v == Alignment.CENTER)
        total = len(col_v)
        if rights >= total / 2:
            resolved.append("right")
        elif centers >= total / 2:
            resolved.append("center")
        else:
            resolved.append("left")
    return resolved


def render_typst_table(
    table: Table,
    render_run_fn: Optional[Callable[[TextRun], str]] = None,
) -> str:
    """Translate a Table IR node into an idiomatic Typst #table(...) call."""
    if not table.rows:
        return ""

    run_fn: Callable[[TextRun], str] = render_run_fn or (lambda r: render_typst_run(r))

    # First pass: compute total columns and build 2D occupancy grid for colspan/rowspan
    num_rows = len(table.rows)
    occupancy: List[List[bool]] = [[] for _ in range(num_rows)]
    row_rendered_cells: List[Tuple[bool, List[str]]] = []
    max_cols = len(table.col_widths) if table.col_widths else 0

    for r_idx, row in enumerate(table.rows):
        c_idx = 0
        cells_out: List[str] = []
        for cell in row.cells:
            while c_idx < len(occupancy[r_idx]) and occupancy[r_idx][c_idx]:
                c_idx += 1

            c_span = max(1, int(cell.col_span))
            r_span = max(1, int(cell.row_span))

            for dr in range(r_span):
                tr = r_idx + dr
                while tr >= len(occupancy):
                    occupancy.append([])
                while len(occupancy[tr]) < c_idx + c_span:
                    occupancy[tr].append(False)
                for dc in range(c_span):
                    occupancy[tr][c_idx + dc] = True

            body_str = _format_cell_body(cell, run_fn)
            cell_args: List[str] = []
            if c_span > 1:
                cell_args.append(f"colspan: {c_span}")
            if r_span > 1:
                cell_args.append(f"rowspan: {r_span}")
            if cell.background_color is not None:
                bg_hex = color_to_hex(cell.background_color)
                cell_args.append(f'fill: rgb("#{bg_hex}")')

            if cell_args:
                cells_out.append(f"table.cell({', '.join(cell_args)})[{body_str}]")
            else:
                cells_out.append(f"[{body_str}]")

            c_idx += c_span

        max_cols = max(max_cols, len(occupancy[r_idx]))
        row_rendered_cells.append((row.is_header, cells_out))

    if max_cols == 0:
        return ""

    # Second pass: pad any ragged rows that had fewer occupied slots than max_cols
    for r_idx, (is_hdr, cells_out) in enumerate(row_rendered_cells):
        occ_row = occupancy[r_idx] if r_idx < len(occupancy) else []
        unoccupied_tail = max(0, max_cols - len(occ_row))
        unoccupied_gaps = sum(1 for flag in occ_row if not flag)
        for _ in range(unoccupied_gaps + unoccupied_tail):
            cells_out.append("[]")

    # Format columns specification
    if table.col_widths and len(table.col_widths) == max_cols and all(w > 0 for w in table.col_widths):
        col_spec = "(" + ", ".join(_format_pt(w) for w in table.col_widths) + ")"
    else:
        col_spec = str(max_cols)

    # Format alignment specification
    col_aligns = _detect_typst_col_alignments(table, max_cols)
    unique_aligns = set(col_aligns)
    if len(unique_aligns) == 1:
        only_align = next(iter(unique_aligns))
        align_arg = f"  align: {only_align},\n" if only_align != "left" else ""
    else:
        align_arg = f"  align: ({', '.join(col_aligns)}),\n"

    # Format header and body rows (wrap contiguous leading header rows in table.header)
    lines: List[str] = [
        "#table(",
        f"  columns: {col_spec},",
    ]
    if align_arg:
        lines.append(align_arg.rstrip("\n"))

    header_cells: List[str] = []
    body_start_idx = 0
    for r_idx, (is_hdr, cells_out) in enumerate(row_rendered_cells):
        if is_hdr and r_idx == body_start_idx:
            header_cells.extend(cells_out)
            body_start_idx = r_idx + 1
        else:
            break

    if header_cells:
        lines.append(f"  table.header({', '.join(header_cells)}),")

    for _, cells_out in row_rendered_cells[body_start_idx:]:
        if cells_out:
            lines.append("  " + ", ".join(cells_out) + ",")

    lines.append(")")
    return "\n".join(lines)


__all__ = [
    "is_monospace_font",
    "is_code_paragraph",
    "is_list_paragraph",
    "render_typst_code_block",
    "render_typst_run",
    "render_typst_paragraph",
    "render_typst_page_blocks",
    "render_typst_table",
]
