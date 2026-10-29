"""ODF content generation and vector path translation for ODP (OpenDocument Presentation).

Adheres to OASIS OpenDocument v1.2 / v1.3 Part 1 §10.3 (Vector Graphics) and §20 (Style Properties):
- Maps VectorBlock SVG paths into ODF <draw:path> elements placed on slide canvases (<draw:page>).
- Generates automatic graphic styles preserving stroke colors, stroke width, alpha opacity,
  line caps, line joins, and fill colors.
- Scales and anchors shapes to slide coordinates with exact bounding boxes and viewBox transformations.
"""

from __future__ import annotations

from typing import List

from anyconvert.common.color import Color
from anyconvert.emitters.base import xml_escape
from anyconvert.ir.model import VectorBlock


def _color_to_odf(color: Color) -> str:
    """Format Color instance as 6-digit hex code with leading hash."""
    return f"#{color.r:02x}{color.g:02x}{color.b:02x}"


def _odf_linecap(line_cap: int) -> str:
    """Map PDF line cap integer to ODF/SVG stroke-linecap string."""
    if line_cap == 1:
        return "round"
    if line_cap == 2:
        return "square"
    return "butt"


def _odf_linejoin(line_join: int) -> str:
    """Map PDF line join integer to ODF/SVG stroke-linejoin string."""
    if line_join == 1:
        return "round"
    if line_join == 2:
        return "bevel"
    return "miter"


def render_vector_path_odp(
    vec: VectorBlock,
    auto_styles: List[str],
    shape_id: int,
    slide_width: float = 720.0,
    slide_height: float = 540.0,
) -> str:
    """Render a VectorBlock into an ODF <draw:path> element for ODP slides.

    Args:
        vec: VectorBlock instance containing SVG path and style attributes.
        auto_styles: Accumulator list for automatic style definitions.
        shape_id: Unique integer identifier for the shape on the slide.
        slide_width: Slide width in points.
        slide_height: Slide height in points.

    Returns:
        ODF <draw:path> XML fragment.
    """
    if not vec.svg_path:
        return ""

    v_style_name = f"V{len(auto_styles) + 1}"
    props: List[str] = []

    # Stroke properties
    if vec.stroke_color is not None and vec.stroke_width > 0:
        stroke_hex = _color_to_odf(vec.stroke_color)
        stroke_type = "dash" if vec.dash_array else "solid"
        props.append(f'draw:stroke="{stroke_type}"')
        props.append(f'svg:stroke-color="{stroke_hex}"')
        props.append(f'svg:stroke-width="{vec.stroke_width:.2f}pt"')
        props.append(f'svg:stroke-linecap="{_odf_linecap(vec.line_cap)}"')
        props.append(f'svg:stroke-linejoin="{_odf_linejoin(vec.line_join)}"')
        if vec.line_join == 0:
            props.append(f'svg:stroke-miterlimit="{vec.miter_limit:.1f}"')

        comb_stroke_alpha = vec.stroke_color.a * vec.stroke_alpha
        if comb_stroke_alpha < 1.0:
            props.append(f'svg:stroke-opacity="{comb_stroke_alpha:.2f}"')
    else:
        props.append('draw:stroke="none"')

    # Fill properties
    if vec.fill_color is not None:
        fill_hex = _color_to_odf(vec.fill_color)
        props.append('draw:fill="solid"')
        props.append(f'draw:fill-color="{fill_hex}"')
        comb_fill_alpha = vec.fill_color.a * vec.fill_alpha
        if comb_fill_alpha < 1.0:
            props.append(f'draw:opacity="{comb_fill_alpha:.2f}"')
    else:
        props.append('draw:fill="none"')

    auto_styles.append(
        f'  <style:style style:name="{v_style_name}" style:family="graphic">\n'
        f'    <style:graphic-properties {" ".join(props)}/>\n'
        f'  </style:style>'
    )

    escaped_d = xml_escape(vec.svg_path)
    sw = max(0.5, vec.stroke_width)

    # Calculate bounding box coordinates
    if vec.bbox.width > 0.0 or vec.bbox.height > 0.0:
        vx0 = vec.bbox.x0
        vy0 = vec.bbox.y0
        vw = max(sw, vec.bbox.width)
        vh = max(sw, vec.bbox.height)
    else:
        vx0 = 0.0
        vy0 = 0.0
        vw = slide_width
        vh = slide_height

    return (
        f'        <draw:path draw:id="Vector_{shape_id}" draw:style-name="{v_style_name}" svg:d="{escaped_d}" '
        f'svg:x="{vx0:.1f}pt" svg:y="{vy0:.1f}pt" svg:width="{vw:.1f}pt" svg:height="{vh:.1f}pt" '
        f'svg:viewBox="{vx0:.1f} {vy0:.1f} {vw:.1f} {vh:.1f}"/>'
    )


__all__ = ["render_vector_path_odp"]
