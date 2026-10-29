"""Native DrawingML vector graphics translation for PPTX (PresentationML).

Adheres to ISO/IEC 29500-1 §19.3 (PresentationML Shapes) and §20.1 (DrawingML):
- Maps VectorBlock SVG path primitives (M, L, C, Z) into PowerPoint shape tree <p:sp>.
- Preserves fill colors, stroke colors, stroke width, alpha transparency, line caps, line joins,
  miter limits, and dash patterns.
- Generates valid <a:custGeom> custom geometries with scalable <a:pathLst>.
"""

from __future__ import annotations

from typing import List

from anyconvert.emitters.base import (
    color_to_hex,
    pt_to_emu,
)
from anyconvert.emitters.docx.drawing import svg_path_to_drawingml
from anyconvert.ir.model import VectorBlock


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


def render_vector_shape(
    vec: VectorBlock,
    shape_id: int,
    slide_width: float = 720.0,
    slide_height: float = 540.0,
) -> str:
    """Render a VectorBlock into a PresentationML shape tree element (<p:sp>).

    Args:
        vec: Intermediate representation VectorBlock.
        shape_id: Unique numerical identifier for the shape in the slide tree.
        slide_width: Presentation slide width in points.
        slide_height: Presentation slide height in points.

    Returns:
        PresentationML <p:sp> XML string.
    """
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
        w_pt = slide_width
        h_pt = slide_height

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

    return f"""      <p:sp>
        <p:nvSpPr>
          <p:cNvPr id="{shape_id}" name="Vector_{shape_id}"/>
          <p:cNvSpPr/>
          <p:nvPr/>
        </p:nvSpPr>
        <p:spPr>
          <a:xfrm>
            <a:off x="{off_x_emu}" y="{off_y_emu}"/>
            <a:ext cx="{cx_emu}" cy="{cy_emu}"/>
          </a:xfrm>
          <a:custGeom>
            <a:avLst/><a:gdLst/><a:ahLst/><a:cxnLst/>
            <a:rect l="0" t="0" r="{w_units}" b="{h_units}"/>
            <a:pathLst>
              <a:path w="{w_units}" h="{h_units}" fill="{fill_mode}" stroke="{has_stroke}">
                {dml_path}
              </a:path>
            </a:pathLst>
          </a:custGeom>
          {fill_xml}
          {ln_xml}
        </p:spPr>
        <p:txBody>
          <a:bodyPr rtlCol="0"/>
          <a:lstStyle/>
          <a:p><a:endParaRPr/></a:p>
        </p:txBody>
      </p:sp>"""


__all__ = ["render_vector_shape"]
