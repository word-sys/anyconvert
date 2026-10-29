"""DrawingML vector graphics translation for DOCX (WordprocessingML).

Adheres to ISO/IEC 29500-1 §20.1 (DrawingML) and §19.3 (WordprocessingML Shapes):
- Maps VectorBlock SVG path primitives (M, L, C, Z) into DrawingML <a:custGeom> geometry.
- Preserves fill colors, stroke colors, stroke width, alpha compositing, line caps, line joins,
  miter limits, and dash patterns.
- Supports both Canvas mode (anchored behindDoc drawings) and Flow mode (inline scalable vector shapes).
"""

from __future__ import annotations

from typing import List

from anyconvert.emitters.base import (
    ConversionMode,
    color_to_hex,
    pt_to_emu,
)
from anyconvert.ir.model import VectorBlock


def svg_path_to_drawingml(
    svg_path: str,
    scale: float = 100.0,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
) -> str:
    """Convert an SVG path into DrawingML path elements (<a:moveTo>, <a:lnTo>, <a:cubicBezTo>, <a:close/>).

    Args:
        svg_path: SVG path string with M, L, C, Z commands.
        scale: Coordinate multiplier for DrawingML path space.
        origin_x: X offset to subtract (local coordinate system).
        origin_y: Y offset to subtract (local coordinate system).

    Returns:
        DrawingML XML fragment.
    """
    cleaned = svg_path.replace(",", " ")
    tokens = cleaned.split()
    dml_cmds: List[str] = []
    i = 0
    n = len(tokens)
    current_cmd = ""

    while i < n:
        tok = tokens[i]
        if tok.isalpha():
            current_cmd = tok
            i += 1
            if current_cmd in ("Z", "z"):
                dml_cmds.append("<a:close/>")
            continue

        cmd = current_cmd.upper()
        if cmd == "M":
            if i + 1 < n:
                try:
                    x = int(round((float(tokens[i]) - origin_x) * scale))
                    y = int(round((float(tokens[i + 1]) - origin_y) * scale))
                    dml_cmds.append(f'<a:moveTo><a:pt x="{x}" y="{y}"/></a:moveTo>')
                except ValueError:
                    pass
                i += 2
            else:
                i += 1
        elif cmd == "L":
            if i + 1 < n:
                try:
                    x = int(round((float(tokens[i]) - origin_x) * scale))
                    y = int(round((float(tokens[i + 1]) - origin_y) * scale))
                    dml_cmds.append(f'<a:lnTo><a:pt x="{x}" y="{y}"/></a:lnTo>')
                except ValueError:
                    pass
                i += 2
            else:
                i += 1
        elif cmd == "C":
            if i + 5 < n:
                try:
                    x1 = int(round((float(tokens[i]) - origin_x) * scale))
                    y1 = int(round((float(tokens[i + 1]) - origin_y) * scale))
                    x2 = int(round((float(tokens[i + 2]) - origin_x) * scale))
                    y2 = int(round((float(tokens[i + 3]) - origin_y) * scale))
                    x3 = int(round((float(tokens[i + 4]) - origin_x) * scale))
                    y3 = int(round((float(tokens[i + 5]) - origin_y) * scale))
                    dml_cmds.append(
                        f'<a:cubicBezTo>'
                        f'<a:pt x="{x1}" y="{y1}"/>'
                        f'<a:pt x="{x2}" y="{y2}"/>'
                        f'<a:pt x="{x3}" y="{y3}"/>'
                        f'</a:cubicBezTo>'
                    )
                except ValueError:
                    pass
                i += 6
            else:
                i += 1
        else:
            i += 1

    return "".join(dml_cmds)


def _build_fill_xml(vec: VectorBlock) -> str:
    """Synthesize DrawingML fill XML (<a:solidFill> or <a:noFill/>)."""
    if vec.fill_color is None:
        return "<a:noFill/>"

    f_hex = color_to_hex(vec.fill_color)
    comb_alpha = vec.fill_color.a * vec.fill_alpha
    if comb_alpha < 1.0:
        alpha = int(round(comb_alpha * 100000))
        return f'<a:solidFill><a:srgbClr val="{f_hex}"><a:alpha val="{alpha}"/></a:srgbClr></a:solidFill>'
    return f'<a:solidFill><a:srgbClr val="{f_hex}"/></a:solidFill>'


def _build_stroke_xml(vec: VectorBlock) -> str:
    """Synthesize DrawingML stroke XML (<a:ln>)."""
    if vec.stroke_color is None or vec.stroke_width <= 0:
        return "<a:ln><a:noFill/></a:ln>"

    s_hex = color_to_hex(vec.stroke_color)
    w_emu = pt_to_emu(max(0.25, vec.stroke_width))

    # Line cap: 0=butt/flat, 1=round, 2=projecting square
    cap_map = {0: "flat", 1: "rnd", 2: "sq"}
    cap_attr = cap_map.get(vec.line_cap, "flat")

    # Line join: 0=miter, 1=round, 2=bevel
    if vec.line_join == 1:
        join_xml = "<a:round/>"
    elif vec.line_join == 2:
        join_xml = "<a:bevel/>"
    else:
        miter_lim = int(round(vec.miter_limit * 100000))
        join_xml = f'<a:miter lim="{miter_lim}"/>'

    # Dashes
    dash_xml = ""
    if vec.dash_array:
        arr = list(vec.dash_array)
        if len(arr) % 2 == 1:
            arr = arr * 2
        lw = max(0.1, vec.stroke_width)
        d_parts: List[str] = ["<a:custDash>"]
        for i in range(0, len(arr), 2):
            d_val = int(round((arr[i] / lw) * 100000))
            sp_val = int(round((arr[i + 1] / lw) * 100000))
            d_parts.append(f'<a:ds d="{d_val}" sp="{sp_val}"/>')
        d_parts.append("</a:custDash>")
        dash_xml = "".join(d_parts)

    comb_alpha = vec.stroke_color.a * vec.stroke_alpha
    if comb_alpha < 1.0:
        alpha = int(round(comb_alpha * 100000))
        color_xml = f'<a:solidFill><a:srgbClr val="{s_hex}"><a:alpha val="{alpha}"/></a:srgbClr></a:solidFill>'
    else:
        color_xml = f'<a:solidFill><a:srgbClr val="{s_hex}"/></a:solidFill>'

    return f'<a:ln w="{w_emu}" cap="{cap_attr}" cmpd="s">{color_xml}{join_xml}{dash_xml}</a:ln>'


def render_vector_run_canvas(
    vec: VectorBlock,
    shape_id: int,
    page_width: float,
    page_height: float,
) -> str:
    """Render a VectorBlock into an anchored DrawingML run (<w:r><w:drawing>...) for Canvas mode."""
    if not vec.svg_path:
        return ""

    scale = 100.0

    # Determine bounding box
    if vec.bbox.width > 0.0 or vec.bbox.height > 0.0:
        origin_x = vec.bbox.x0
        origin_y = vec.bbox.y0
        w_pt = max(vec.bbox.width, 1.0)
        h_pt = max(vec.bbox.height, 1.0)
    else:
        origin_x = 0.0
        origin_y = 0.0
        w_pt = page_width
        h_pt = page_height

    dml_path = svg_path_to_drawingml(
        vec.svg_path, scale=scale, origin_x=origin_x, origin_y=origin_y
    )
    if not dml_path:
        return ""

    w_units = max(1, int(round(w_pt * scale)))
    h_units = max(1, int(round(h_pt * scale)))
    cx_emu = pt_to_emu(w_pt)
    cy_emu = pt_to_emu(h_pt)
    off_x_emu = pt_to_emu(origin_x)
    off_y_emu = pt_to_emu(origin_y)

    fill_xml = _build_fill_xml(vec)
    ln_xml = _build_stroke_xml(vec)
    fill_mode = "norm" if vec.fill_color is not None else "none"
    has_stroke = "true" if (vec.stroke_color is not None and vec.stroke_width > 0) else "false"

    return (
        '      <w:r>\n'
        '        <w:drawing>\n'
        '          <wp:anchor distT="0" distB="0" distL="0" distR="0" simplePos="0" relativeHeight="1"\n'
        '                     behindDoc="1" locked="0" layoutInCell="0" allowOverlap="1">\n'
        '            <wp:simplePos x="0" y="0"/>\n'
        f'            <wp:positionH relativeFrom="page"><wp:posOffset>{off_x_emu}</wp:posOffset></wp:positionH>\n'
        f'            <wp:positionV relativeFrom="page"><wp:posOffset>{off_y_emu}</wp:posOffset></wp:positionV>\n'
        f'            <wp:extent cx="{cx_emu}" cy="{cy_emu}"/>\n'
        '            <wp:effectExtent l="0" t="0" r="0" b="0"/>\n'
        '            <wp:wrapNone/>\n'
        f'            <wp:docPr id="{shape_id}" name="Vector_{shape_id}"/>\n'
        '            <wp:cNvGraphicFramePr/>\n'
        '            <a:graphic>\n'
        '              <a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">\n'
        '                <wps:wsp>\n'
        '                  <wps:cNvSpPr/>\n'
        '                  <wps:spPr>\n'
        f'                    <a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx_emu}" cy="{cy_emu}"/></a:xfrm>\n'
        '                    <a:custGeom>\n'
        '                      <a:avLst/><a:gdLst/><a:ahLst/><a:cxnLst/>\n'
        f'                      <a:rect l="0" t="0" r="{w_units}" b="{h_units}"/>\n'
        '                      <a:pathLst>\n'
        f'                        <a:path w="{w_units}" h="{h_units}" fill="{fill_mode}" stroke="{has_stroke}">\n'
        f'                          {dml_path}\n'
        '                        </a:path>\n'
        '                      </a:pathLst>\n'
        '                    </a:custGeom>\n'
        f'                    {fill_xml}\n'
        f'                    {ln_xml}\n'
        '                  </wps:spPr>\n'
        '                  <wps:bodyPr/>\n'
        '                </wps:wsp>\n'
        '              </a:graphicData>\n'
        '            </a:graphic>\n'
        '          </wp:anchor>\n'
        '        </w:drawing>\n'
        '      </w:r>\n'
    )


def render_vector_block_flow(
    vec: VectorBlock,
    shape_id: int,
    page_width: float = 612.0,
) -> str:
    """Render a VectorBlock into an inline DrawingML paragraph (<w:p><w:r><w:drawing><wp:inline>...) for Flow mode."""
    if not vec.svg_path:
        return ""

    scale = 100.0

    if vec.bbox.width > 0.0 or vec.bbox.height > 0.0:
        origin_x = vec.bbox.x0
        origin_y = vec.bbox.y0
        w_pt = max(vec.bbox.width, 1.0)
        h_pt = max(vec.bbox.height, 1.0)
    else:
        origin_x = 0.0
        origin_y = 0.0
        w_pt = min(200.0, page_width)
        h_pt = 100.0

    dml_path = svg_path_to_drawingml(
        vec.svg_path, scale=scale, origin_x=origin_x, origin_y=origin_y
    )
    if not dml_path:
        return ""

    w_units = max(1, int(round(w_pt * scale)))
    h_units = max(1, int(round(h_pt * scale)))
    cx_emu = pt_to_emu(w_pt)
    cy_emu = pt_to_emu(h_pt)

    fill_xml = _build_fill_xml(vec)
    ln_xml = _build_stroke_xml(vec)
    fill_mode = "norm" if vec.fill_color is not None else "none"
    has_stroke = "true" if (vec.stroke_color is not None and vec.stroke_width > 0) else "false"

    return (
        '    <w:p>\n'
        '      <w:pPr><w:jc w:val="center"/></w:pPr>\n'
        '      <w:r>\n'
        '        <w:drawing>\n'
        '          <wp:inline distT="0" distB="0" distL="0" distR="0">\n'
        f'            <wp:extent cx="{cx_emu}" cy="{cy_emu}"/>\n'
        '            <wp:effectExtent l="0" t="0" r="0" b="0"/>\n'
        f'            <wp:docPr id="{shape_id}" name="Vector_{shape_id}"/>\n'
        '            <wp:cNvGraphicFramePr/>\n'
        '            <a:graphic>\n'
        '              <a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">\n'
        '                <wps:wsp>\n'
        '                  <wps:cNvSpPr/>\n'
        '                  <wps:spPr>\n'
        f'                    <a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx_emu}" cy="{cy_emu}"/></a:xfrm>\n'
        '                    <a:custGeom>\n'
        '                      <a:avLst/><a:gdLst/><a:ahLst/><a:cxnLst/>\n'
        f'                      <a:rect l="0" t="0" r="{w_units}" b="{h_units}"/>\n'
        '                      <a:pathLst>\n'
        f'                        <a:path w="{w_units}" h="{h_units}" fill="{fill_mode}" stroke="{has_stroke}">\n'
        f'                          {dml_path}\n'
        '                        </a:path>\n'
        '                      </a:pathLst>\n'
        '                    </a:custGeom>\n'
        f'                    {fill_xml}\n'
        f'                    {ln_xml}\n'
        '                  </wps:spPr>\n'
        '                  <wps:bodyPr/>\n'
        '                </wps:wsp>\n'
        '              </a:graphicData>\n'
        '            </a:graphic>\n'
        '          </wp:inline>\n'
        '        </w:drawing>\n'
        '      </w:r>\n'
        '    </w:p>'
    )


__all__ = [
    "svg_path_to_drawingml",
    "render_vector_run_canvas",
    "render_vector_block_flow",
]
