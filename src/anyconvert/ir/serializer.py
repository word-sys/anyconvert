"""Pure-Python JSON AST serialization, deserialization, and schema validation for DocumentIR.

Converts validated DocumentIR hierarchies into clean, RFC 8259-compliant JSON AST
documents containing page geometry, margins, headers/footers, bounding boxes, fonts,
colors, text runs, nested tables, vector paths, and Base64-encoded images, and
losslessly reconstructs DocumentIR objects from JSON AST payloads.
"""

from __future__ import annotations

import base64
import binascii
import json
import math
from typing import Any, Dict, List, Mapping, Optional, Union

from anyconvert.common.color import Color
from anyconvert.common.geometry import BoundingBox
from anyconvert.exceptions import SerializationError
from anyconvert.ir.model import (
    Alignment,
    BlockNode,
    Border,
    DocumentIR,
    DocumentPage,
    HeadingLevel,
    ImageBlock,
    PageHeaderFooter,
    Paragraph,
    Table,
    TableCell,
    TableRow,
    TextRun,
    VectorBlock,
)
from anyconvert.ir.validator import validate_document_ir

JSON_AST_SCHEMA_VERSION = "1.0"
SUPPORTED_SCHEMA_VERSIONS = frozenset({JSON_AST_SCHEMA_VERSION})

_MAX_NESTING_DEPTH = 32

_ALIGNMENT_TO_STR: Dict[Alignment, str] = {
    Alignment.LEFT: "left",
    Alignment.CENTER: "center",
    Alignment.RIGHT: "right",
    Alignment.JUSTIFIED: "justified",
}
_STR_TO_ALIGNMENT: Dict[str, Alignment] = {v: k for k, v in _ALIGNMENT_TO_STR.items()}

_VALID_BORDER_STYLES = frozenset({"solid", "dashed", "dotted", "none"})
_VALID_FILL_RULES = frozenset({"nonzero", "evenodd"})


def _is_int(val: Any) -> bool:
    """Return True if val is an int and not a bool."""
    return isinstance(val, int) and not isinstance(val, bool)


def _is_number(val: Any) -> bool:
    """Return True if val is a finite int/float and not a bool."""
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        return False
    return math.isfinite(float(val))


def _require_mapping(val: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(val, Mapping):
        raise SerializationError(f"Schema violation at '{path}': expected object, got {type(val).__name__}")
    return val


def _require_list(val: Any, path: str) -> List[Any]:
    if not isinstance(val, list):
        raise SerializationError(f"Schema violation at '{path}': expected list, got {type(val).__name__}")
    return val


def _require_str(val: Any, path: str) -> str:
    if not isinstance(val, str):
        raise SerializationError(f"Schema violation at '{path}': expected str, got {type(val).__name__}")
    return val


def _require_bool(val: Any, path: str) -> bool:
    if not isinstance(val, bool):
        raise SerializationError(f"Schema violation at '{path}': expected bool, got {type(val).__name__}")
    return val


def _require_int(val: Any, path: str, *, min_val: Optional[int] = None, max_val: Optional[int] = None) -> int:
    if not _is_int(val):
        raise SerializationError(f"Schema violation at '{path}': expected int, got {type(val).__name__}")
    ival = int(val)
    if min_val is not None and ival < min_val:
        raise SerializationError(f"Schema violation at '{path}': expected >= {min_val}, got {ival}")
    if max_val is not None and ival > max_val:
        raise SerializationError(f"Schema violation at '{path}': expected <= {max_val}, got {ival}")
    return ival


def _require_float(val: Any, path: str, *, min_val: Optional[float] = None, max_val: Optional[float] = None) -> float:
    if not _is_number(val):
        raise SerializationError(f"Schema violation at '{path}': expected finite number, got {val!r}")
    fval = float(val)
    if min_val is not None and fval < min_val:
        raise SerializationError(f"Schema violation at '{path}': expected >= {min_val}, got {fval}")
    if max_val is not None and fval > max_val:
        raise SerializationError(f"Schema violation at '{path}': expected <= {max_val}, got {fval}")
    return fval


# =====================================================================
# Primitive Serialization / Deserialization
# =====================================================================


def _bbox_to_dict(bbox: Optional[BoundingBox]) -> Optional[Dict[str, float]]:
    if bbox is None:
        return None
    return {
        "x0": float(bbox.x0),
        "y0": float(bbox.y0),
        "x1": float(bbox.x1),
        "y1": float(bbox.y1),
    }


def _bbox_from_dict(data: Any, path: str, *, required: bool = False) -> Optional[BoundingBox]:
    if data is None:
        if required:
            raise SerializationError(f"Schema violation at '{path}': bbox is required")
        return None
    obj = _require_mapping(data, path)
    x0 = _require_float(obj.get("x0"), f"{path}.x0")
    y0 = _require_float(obj.get("y0"), f"{path}.y0")
    x1 = _require_float(obj.get("x1"), f"{path}.x1")
    y1 = _require_float(obj.get("y1"), f"{path}.y1")
    if x1 < x0 or y1 < y0:
        raise SerializationError(
            f"Schema violation at '{path}': invalid bbox bounds ({x0}, {y0}, {x1}, {y1})"
        )
    return BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1)


def _color_to_dict(color: Optional[Color]) -> Optional[Dict[str, Any]]:
    if color is None:
        return None
    return {
        "r": int(color.r),
        "g": int(color.g),
        "b": int(color.b),
        "a": float(color.a),
        "hex": color.hex_with_hash,
    }


def _color_from_dict(data: Any, path: str, *, required: bool = False) -> Optional[Color]:
    if data is None:
        if required:
            raise SerializationError(f"Schema violation at '{path}': color is required")
        return None
    if isinstance(data, str):
        raw = data.strip().lstrip("#")
        if len(raw) == 6:
            try:
                return Color(int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16), 1.0)
            except ValueError as exc:
                raise SerializationError(f"Schema violation at '{path}': invalid hex color {data!r}") from exc
        if len(raw) == 8:
            try:
                return Color(
                    int(raw[0:2], 16),
                    int(raw[2:4], 16),
                    int(raw[4:6], 16),
                    int(raw[6:8], 16) / 255.0,
                )
            except ValueError as exc:
                raise SerializationError(f"Schema violation at '{path}': invalid hex color {data!r}") from exc
        raise SerializationError(f"Schema violation at '{path}': invalid hex color {data!r}")

    obj = _require_mapping(data, path)
    r = _require_int(obj.get("r"), f"{path}.r", min_val=0, max_val=255)
    g = _require_int(obj.get("g"), f"{path}.g", min_val=0, max_val=255)
    b = _require_int(obj.get("b"), f"{path}.b", min_val=0, max_val=255)
    a = _require_float(obj.get("a", 1.0), f"{path}.a", min_val=0.0, max_val=1.0)
    return Color(r=r, g=g, b=b, a=a)


def _alignment_from_str(val: Any, path: str, default: Alignment = Alignment.LEFT) -> Alignment:
    if val is None:
        return default
    s = _require_str(val, path).lower().strip()
    if s not in _STR_TO_ALIGNMENT:
        raise SerializationError(
            f"Schema violation at '{path}': invalid alignment {val!r}; expected one of {sorted(_STR_TO_ALIGNMENT)}"
        )
    return _STR_TO_ALIGNMENT[s]


def _heading_level_from_val(val: Any, path: str) -> Optional[HeadingLevel]:
    if val is None:
        return None
    lvl = _require_int(val, path, min_val=1, max_val=6)
    return HeadingLevel(lvl)


# =====================================================================
# Node Serialization
# =====================================================================


def _text_run_to_dict(run: TextRun) -> Dict[str, Any]:
    return {
        "text": run.text,
        "font_name": run.font_name,
        "font_size": float(run.font_size),
        "color": _color_to_dict(run.color),
        "is_bold": bool(run.is_bold),
        "is_italic": bool(run.is_italic),
        "is_underline": bool(run.is_underline),
        "is_strikethrough": bool(run.is_strikethrough),
        "tracking": float(run.tracking),
        "baseline_offset": float(run.baseline_offset),
        "bbox": _bbox_to_dict(run.bbox),
    }


def _paragraph_to_dict(p: Paragraph) -> Dict[str, Any]:
    return {
        "type": "paragraph",
        "text": p.text,
        "alignment": _ALIGNMENT_TO_STR.get(p.alignment, "left"),
        "heading_level": p.heading_level.value if p.heading_level is not None else None,
        "line_spacing": float(p.line_spacing),
        "space_before": float(p.space_before),
        "space_after": float(p.space_after),
        "indent_left": float(p.indent_left),
        "indent_right": float(p.indent_right),
        "indent_first_line": float(p.indent_first_line),
        "list_marker": p.list_marker,
        "list_level": int(p.list_level),
        "bbox": _bbox_to_dict(p.bbox),
        "runs": [_text_run_to_dict(r) for r in p.runs],
    }


def _border_to_dict(border: Border) -> Dict[str, Any]:
    return {
        "style": border.style,
        "width": float(border.width),
        "color": _color_to_dict(border.color),
    }


def _table_cell_to_dict(cell: TableCell, *, include_images: bool, depth: int) -> Dict[str, Any]:
    return {
        "col_span": int(cell.col_span),
        "row_span": int(cell.row_span),
        "width": float(cell.width),
        "height": float(cell.height),
        "background_color": _color_to_dict(cell.background_color),
        "borders": {side: _border_to_dict(b) for side, b in cell.borders.items()},
        "content": [
            _block_to_dict(blk, include_images=include_images, depth=depth + 1)
            for blk in cell.content
        ],
    }


def _table_to_dict(table: Table, *, include_images: bool, depth: int) -> Dict[str, Any]:
    return {
        "type": "table",
        "col_widths": [float(w) for w in table.col_widths],
        "alignment": _ALIGNMENT_TO_STR.get(table.alignment, "center"),
        "bbox": _bbox_to_dict(table.bbox),
        "rows": [
            {
                "height": float(row.height),
                "is_header": bool(row.is_header),
                "cells": [
                    _table_cell_to_dict(cell, include_images=include_images, depth=depth)
                    for cell in row.cells
                ],
            }
            for row in table.rows
        ],
    }


def _image_to_dict(img: ImageBlock, *, include_images: bool) -> Dict[str, Any]:
    if img.image_bytes:
        img.sync_format()
    encoded: Optional[str] = (
        base64.b64encode(img.image_bytes).decode("ascii")
        if include_images and img.image_bytes
        else None
    )
    return {
        "type": "image",
        "format": img.format,
        "mime_type": img.mime_type,
        "pixel_width": img.pixel_width,
        "pixel_height": img.pixel_height,
        "alt_text": img.alt_text,
        "rotation": float(img.rotation),
        "bbox": _bbox_to_dict(img.bbox),
        "data_base64": encoded,
    }


def _vector_to_dict(vec: VectorBlock) -> Dict[str, Any]:
    return {
        "type": "vector",
        "svg_path": vec.svg_path,
        "bbox": _bbox_to_dict(vec.bbox),
        "fill_color": _color_to_dict(vec.fill_color),
        "stroke_color": _color_to_dict(vec.stroke_color),
        "stroke_width": float(vec.stroke_width),
        "fill_rule": vec.fill_rule,
        "fill_alpha": float(vec.fill_alpha),
        "stroke_alpha": float(vec.stroke_alpha),
        "line_cap": int(vec.line_cap),
        "line_join": int(vec.line_join),
        "miter_limit": float(vec.miter_limit),
        "dash_array": [float(d) for d in vec.dash_array],
        "dash_phase": float(vec.dash_phase),
    }


def _block_to_dict(block: BlockNode, *, include_images: bool, depth: int = 0) -> Dict[str, Any]:
    if depth > _MAX_NESTING_DEPTH:
        raise SerializationError(f"Exceeded maximum block nesting depth ({_MAX_NESTING_DEPTH})")
    if isinstance(block, Paragraph):
        return _paragraph_to_dict(block)
    if isinstance(block, Table):
        return _table_to_dict(block, include_images=include_images, depth=depth)
    if isinstance(block, ImageBlock):
        return _image_to_dict(block, include_images=include_images)
    if isinstance(block, VectorBlock):
        return _vector_to_dict(block)
    raise SerializationError(f"Unsupported BlockNode type: {type(block).__name__}")


def _header_footer_to_dict(hf: Optional[PageHeaderFooter]) -> Optional[Dict[str, Any]]:
    if hf is None:
        return None
    return {
        "type": "footer" if hf.is_footer else "header",
        "is_footer": bool(hf.is_footer),
        "content": [_paragraph_to_dict(p) for p in hf.content],
    }


def _page_to_dict(page: DocumentPage, *, include_images: bool) -> Dict[str, Any]:
    return {
        "type": "page",
        "page_number": int(page.page_number),
        "width": float(page.width),
        "height": float(page.height),
        "margins": {
            "top": float(page.margin_top),
            "bottom": float(page.margin_bottom),
            "left": float(page.margin_left),
            "right": float(page.margin_right),
        },
        "header": _header_footer_to_dict(page.header),
        "footer": _header_footer_to_dict(page.footer),
        "blocks": [_block_to_dict(blk, include_images=include_images) for blk in page.blocks],
    }


# =====================================================================
# Node Deserialization
# =====================================================================


def _text_run_from_dict(data: Any, path: str) -> TextRun:
    obj = _require_mapping(data, path)
    text = _require_str(obj.get("text"), f"{path}.text")
    font_name = _require_str(obj.get("font_name"), f"{path}.font_name")
    font_size = _require_float(obj.get("font_size"), f"{path}.font_size", min_val=0.0)
    color = _color_from_dict(obj.get("color"), f"{path}.color", required=True)
    assert color is not None
    return TextRun(
        text=text,
        font_name=font_name,
        font_size=font_size,
        color=color,
        is_bold=_require_bool(obj.get("is_bold", False), f"{path}.is_bold"),
        is_italic=_require_bool(obj.get("is_italic", False), f"{path}.is_italic"),
        is_underline=_require_bool(obj.get("is_underline", False), f"{path}.is_underline"),
        is_strikethrough=_require_bool(obj.get("is_strikethrough", False), f"{path}.is_strikethrough"),
        tracking=_require_float(obj.get("tracking", 0.0), f"{path}.tracking"),
        baseline_offset=_require_float(obj.get("baseline_offset", 0.0), f"{path}.baseline_offset"),
        bbox=_bbox_from_dict(obj.get("bbox"), f"{path}.bbox", required=False),
    )


def _paragraph_from_dict(data: Any, path: str) -> Paragraph:
    obj = _require_mapping(data, path)
    btype = obj.get("type", "paragraph")
    if btype != "paragraph":
        raise SerializationError(f"Schema violation at '{path}.type': expected 'paragraph', got {btype!r}")
    raw_runs = _require_list(obj.get("runs", []), f"{path}.runs")
    runs = [_text_run_from_dict(r, f"{path}.runs[{idx}]") for idx, r in enumerate(raw_runs)]
    list_marker_raw = obj.get("list_marker")
    list_marker = _require_str(list_marker_raw, f"{path}.list_marker") if list_marker_raw is not None else None
    return Paragraph(
        runs=runs,
        alignment=_alignment_from_str(obj.get("alignment"), f"{path}.alignment", default=Alignment.LEFT),
        heading_level=_heading_level_from_val(obj.get("heading_level"), f"{path}.heading_level"),
        line_spacing=_require_float(obj.get("line_spacing", 1.15), f"{path}.line_spacing"),
        space_before=_require_float(obj.get("space_before", 0.0), f"{path}.space_before"),
        space_after=_require_float(obj.get("space_after", 0.0), f"{path}.space_after"),
        indent_left=_require_float(obj.get("indent_left", 0.0), f"{path}.indent_left"),
        indent_right=_require_float(obj.get("indent_right", 0.0), f"{path}.indent_right"),
        indent_first_line=_require_float(obj.get("indent_first_line", 0.0), f"{path}.indent_first_line"),
        list_marker=list_marker,
        list_level=_require_int(obj.get("list_level", 0), f"{path}.list_level", min_val=0),
        bbox=_bbox_from_dict(obj.get("bbox"), f"{path}.bbox", required=False),
    )


def _border_from_dict(data: Any, path: str) -> Border:
    obj = _require_mapping(data, path)
    style = _require_str(obj.get("style", "solid"), f"{path}.style").lower().strip()
    if style not in _VALID_BORDER_STYLES:
        raise SerializationError(
            f"Schema violation at '{path}.style': invalid border style {style!r}"
        )
    width = _require_float(obj.get("width", 1.0), f"{path}.width", min_val=0.0)
    color = _color_from_dict(obj.get("color"), f"{path}.color", required=False) or Color.black()
    return Border(style=style, width=width, color=color)


def _table_cell_from_dict(data: Any, path: str, *, depth: int) -> TableCell:
    obj = _require_mapping(data, path)
    raw_content = _require_list(obj.get("content", []), f"{path}.content")
    content = [
        _block_from_dict(blk, f"{path}.content[{idx}]", depth=depth + 1)
        for idx, blk in enumerate(raw_content)
    ]
    raw_borders = obj.get("borders", {})
    borders_map = _require_mapping(raw_borders, f"{path}.borders")
    borders: Dict[str, Border] = {}
    for side, bdata in borders_map.items():
        side_str = _require_str(side, f"{path}.borders.<key>")
        borders[side_str] = _border_from_dict(bdata, f"{path}.borders.{side_str}")
    return TableCell(
        content=content,
        col_span=_require_int(obj.get("col_span", 1), f"{path}.col_span", min_val=1),
        row_span=_require_int(obj.get("row_span", 1), f"{path}.row_span", min_val=1),
        width=_require_float(obj.get("width", 0.0), f"{path}.width", min_val=0.0),
        height=_require_float(obj.get("height", 0.0), f"{path}.height", min_val=0.0),
        background_color=_color_from_dict(obj.get("background_color"), f"{path}.background_color", required=False),
        borders=borders,
    )


def _table_from_dict(data: Any, path: str, *, depth: int) -> Table:
    obj = _require_mapping(data, path)
    raw_widths = _require_list(obj.get("col_widths", []), f"{path}.col_widths")
    col_widths = [_require_float(w, f"{path}.col_widths[{idx}]", min_val=0.0) for idx, w in enumerate(raw_widths)]

    raw_rows = _require_list(obj.get("rows", []), f"{path}.rows")
    rows: List[TableRow] = []
    for r_idx, rdata in enumerate(raw_rows):
        robj = _require_mapping(rdata, f"{path}.rows[{r_idx}]")
        raw_cells = _require_list(robj.get("cells", []), f"{path}.rows[{r_idx}].cells")
        cells = [
            _table_cell_from_dict(cdata, f"{path}.rows[{r_idx}].cells[{c_idx}]", depth=depth)
            for c_idx, cdata in enumerate(raw_cells)
        ]
        rows.append(
            TableRow(
                cells=cells,
                height=_require_float(robj.get("height", 0.0), f"{path}.rows[{r_idx}].height", min_val=0.0),
                is_header=_require_bool(robj.get("is_header", False), f"{path}.rows[{r_idx}].is_header"),
            )
        )

    return Table(
        rows=rows,
        col_widths=col_widths,
        alignment=_alignment_from_str(obj.get("alignment"), f"{path}.alignment", default=Alignment.CENTER),
        bbox=_bbox_from_dict(obj.get("bbox"), f"{path}.bbox", required=False),
    )


def _image_from_dict(data: Any, path: str) -> ImageBlock:
    obj = _require_mapping(data, path)
    bbox = _bbox_from_dict(obj.get("bbox"), f"{path}.bbox", required=True)
    assert bbox is not None

    raw_b64 = obj.get("data_base64")
    if raw_b64 is None:
        image_bytes = b""
    else:
        b64_str = _require_str(raw_b64, f"{path}.data_base64")
        try:
            image_bytes = base64.b64decode(b64_str.encode("ascii"), validate=True)
        except (UnicodeEncodeError, binascii.Error, ValueError) as exc:
            raise SerializationError(f"Schema violation at '{path}.data_base64': invalid Base64 payload") from exc

    pw_raw = obj.get("pixel_width")
    ph_raw = obj.get("pixel_height")
    pixel_width = _require_int(pw_raw, f"{path}.pixel_width", min_val=0) if pw_raw is not None else None
    pixel_height = _require_int(ph_raw, f"{path}.pixel_height", min_val=0) if ph_raw is not None else None

    return ImageBlock(
        image_bytes=image_bytes,
        bbox=bbox,
        alt_text=_require_str(obj.get("alt_text", ""), f"{path}.alt_text"),
        rotation=_require_float(obj.get("rotation", 0.0), f"{path}.rotation"),
        format=_require_str(obj.get("format", "png"), f"{path}.format"),
        pixel_width=pixel_width,
        pixel_height=pixel_height,
    )


def _vector_from_dict(data: Any, path: str) -> VectorBlock:
    obj = _require_mapping(data, path)
    svg_path = _require_str(obj.get("svg_path"), f"{path}.svg_path")
    bbox = _bbox_from_dict(obj.get("bbox"), f"{path}.bbox", required=True)
    assert bbox is not None
    fill_rule = _require_str(obj.get("fill_rule", "nonzero"), f"{path}.fill_rule").lower().strip()
    if fill_rule not in _VALID_FILL_RULES:
        raise SerializationError(f"Schema violation at '{path}.fill_rule': invalid fill_rule {fill_rule!r}")
    raw_dash = _require_list(obj.get("dash_array", []), f"{path}.dash_array")
    dash_array = [
        _require_float(d, f"{path}.dash_array[{idx}]", min_val=0.0)
        for idx, d in enumerate(raw_dash)
    ]
    return VectorBlock(
        svg_path=svg_path,
        bbox=bbox,
        fill_color=_color_from_dict(obj.get("fill_color"), f"{path}.fill_color", required=False),
        stroke_color=_color_from_dict(obj.get("stroke_color"), f"{path}.stroke_color", required=False),
        stroke_width=_require_float(obj.get("stroke_width", 1.0), f"{path}.stroke_width", min_val=0.0),
        fill_rule=fill_rule,
        fill_alpha=_require_float(obj.get("fill_alpha", 1.0), f"{path}.fill_alpha", min_val=0.0, max_val=1.0),
        stroke_alpha=_require_float(obj.get("stroke_alpha", 1.0), f"{path}.stroke_alpha", min_val=0.0, max_val=1.0),
        line_cap=_require_int(obj.get("line_cap", 0), f"{path}.line_cap", min_val=0, max_val=2),
        line_join=_require_int(obj.get("line_join", 0), f"{path}.line_join", min_val=0, max_val=2),
        miter_limit=_require_float(obj.get("miter_limit", 10.0), f"{path}.miter_limit", min_val=0.0),
        dash_array=dash_array,
        dash_phase=_require_float(obj.get("dash_phase", 0.0), f"{path}.dash_phase"),
    )


def _block_from_dict(data: Any, path: str, *, depth: int = 0) -> BlockNode:
    if depth > _MAX_NESTING_DEPTH:
        raise SerializationError(f"Exceeded maximum block nesting depth ({_MAX_NESTING_DEPTH}) at '{path}'")
    obj = _require_mapping(data, path)
    btype = _require_str(obj.get("type"), f"{path}.type")
    if btype == "paragraph":
        return _paragraph_from_dict(obj, path)
    if btype == "table":
        return _table_from_dict(obj, path, depth=depth)
    if btype == "image":
        return _image_from_dict(obj, path)
    if btype == "vector":
        return _vector_from_dict(obj, path)
    raise SerializationError(
        f"Schema violation at '{path}.type': unsupported block type {btype!r}"
    )


def _header_footer_from_dict(
    data: Any,
    path: str,
    *,
    expected_is_footer: bool,
) -> Optional[PageHeaderFooter]:
    if data is None:
        return None
    obj = _require_mapping(data, path)
    is_footer = _require_bool(obj.get("is_footer", expected_is_footer), f"{path}.is_footer")
    raw_content = _require_list(obj.get("content", []), f"{path}.content")
    content = [_paragraph_from_dict(p, f"{path}.content[{idx}]") for idx, p in enumerate(raw_content)]
    return PageHeaderFooter(content=content, is_footer=is_footer)


def _page_from_dict(data: Any, path: str) -> DocumentPage:
    obj = _require_mapping(data, path)
    ptype = obj.get("type", "page")
    if ptype != "page":
        raise SerializationError(f"Schema violation at '{path}.type': expected 'page', got {ptype!r}")
    page_number = _require_int(obj.get("page_number"), f"{path}.page_number", min_val=1)
    width = _require_float(obj.get("width"), f"{path}.width")
    height = _require_float(obj.get("height"), f"{path}.height")

    margins_raw = obj.get("margins")
    if margins_raw is not None:
        margins = _require_mapping(margins_raw, f"{path}.margins")
        m_top = _require_float(margins.get("top", 72.0), f"{path}.margins.top")
        m_bottom = _require_float(margins.get("bottom", 72.0), f"{path}.margins.bottom")
        m_left = _require_float(margins.get("left", 72.0), f"{path}.margins.left")
        m_right = _require_float(margins.get("right", 72.0), f"{path}.margins.right")
    else:
        m_top = _require_float(obj.get("margin_top", 72.0), f"{path}.margin_top")
        m_bottom = _require_float(obj.get("margin_bottom", 72.0), f"{path}.margin_bottom")
        m_left = _require_float(obj.get("margin_left", 72.0), f"{path}.margin_left")
        m_right = _require_float(obj.get("margin_right", 72.0), f"{path}.margin_right")

    header = _header_footer_from_dict(obj.get("header"), f"{path}.header", expected_is_footer=False)
    footer = _header_footer_from_dict(obj.get("footer"), f"{path}.footer", expected_is_footer=True)

    raw_blocks = _require_list(obj.get("blocks", []), f"{path}.blocks")
    blocks = [_block_from_dict(blk, f"{path}.blocks[{idx}]") for idx, blk in enumerate(raw_blocks)]

    return DocumentPage(
        page_number=page_number,
        width=width,
        height=height,
        margin_top=m_top,
        margin_bottom=m_bottom,
        margin_left=m_left,
        margin_right=m_right,
        blocks=blocks,
        header=header,
        footer=footer,
    )


# =====================================================================
# Public API
# =====================================================================


def validate_json_ast_schema(data: Any) -> None:
    """Validate that a parsed JSON value conforms to the anyconvert DocumentIR AST schema.

    Raises:
        SerializationError: If the JSON structure, types, or schema version are invalid.
    """
    # Full parse without IR semantic validation checks all structural/type/range rules
    document_ir_from_dict(data, validate=False)


def document_ir_to_dict(
    doc_ir: DocumentIR,
    *,
    include_images: bool = True,
    validate: bool = True,
) -> Dict[str, Any]:
    """Convert a DocumentIR instance into a schema-compliant JSON-serializable dictionary.

    Args:
        doc_ir: DocumentIR root object to serialize.
        include_images: When True, embed raster/vector image bytes as Base64 strings.
        validate: When True, run validate_document_ir() prior to serialization.

    Returns:
        Schema-validated dictionary representing the DocumentIR AST.

    Raises:
        IRValidationError: If validate=True and doc_ir violates IR invariants.
        SerializationError: If doc_ir is not a DocumentIR or contains invalid nodes.
    """
    if not isinstance(doc_ir, DocumentIR):
        raise SerializationError(f"Expected DocumentIR instance, got {type(doc_ir).__name__}")
    if validate:
        validate_document_ir(doc_ir)

    metadata = {str(k): str(v) for k, v in doc_ir.metadata.items()}
    return {
        "schema_version": JSON_AST_SCHEMA_VERSION,
        "type": "document",
        "metadata": metadata,
        "pages": [_page_to_dict(p, include_images=include_images) for p in doc_ir.pages],
    }


def document_ir_from_dict(
    data: Any,
    *,
    validate: bool = True,
) -> DocumentIR:
    """Reconstruct a DocumentIR instance from a parsed JSON AST dictionary.

    Args:
        data: Parsed dictionary conforming to the anyconvert JSON AST schema.
        validate: When True, run validate_document_ir() on the reconstructed DocumentIR.

    Returns:
        Reconstructed DocumentIR instance.

    Raises:
        SerializationError: If the JSON AST schema or field types are invalid.
        IRValidationError: If validate=True and reconstructed IR violates structural invariants.
    """
    root = _require_mapping(data, "$")
    schema_version = _require_str(root.get("schema_version"), "$.schema_version")
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise SerializationError(
            f"Unsupported JSON AST schema_version: {schema_version!r}; "
            f"supported: {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
        )

    doc_type = _require_str(root.get("type"), "$.type")
    if doc_type != "document":
        raise SerializationError(f"Schema violation at '$.type': expected 'document', got {doc_type!r}")

    raw_meta = root.get("metadata", {})
    meta_map = _require_mapping(raw_meta, "$.metadata")
    metadata: Dict[str, str] = {}
    for k, v in meta_map.items():
        k_str = _require_str(k, "$.metadata.<key>")
        v_str = _require_str(v, f"$.metadata.{k_str}")
        metadata[k_str] = v_str

    raw_pages = _require_list(root.get("pages"), "$.pages")
    pages = [_page_from_dict(p, f"$.pages[{idx}]") for idx, p in enumerate(raw_pages)]

    doc_ir = DocumentIR(pages=pages, metadata=metadata)
    if validate:
        validate_document_ir(doc_ir)
    return doc_ir


def serialize_document_ir(
    doc_ir: DocumentIR,
    *,
    indent: Optional[int] = 2,
    include_images: bool = True,
    ensure_ascii: bool = False,
    validate: bool = True,
) -> str:
    """Serialize a DocumentIR instance into a clean RFC 8259 JSON AST string.

    Args:
        doc_ir: DocumentIR root object to serialize.
        indent: Indentation spaces for pretty-printing (None for compact single-line JSON).
        include_images: When True, embed image payloads as Base64 strings.
        ensure_ascii: When True, escape non-ASCII characters as \\uXXXX.
        validate: When True, validate DocumentIR invariants prior to serialization.

    Returns:
        UTF-8 JSON string conforming to the anyconvert JSON AST schema.
    """
    ast_dict = document_ir_to_dict(
        doc_ir,
        include_images=include_images,
        validate=validate,
    )
    try:
        return json.dumps(
            ast_dict,
            indent=indent,
            ensure_ascii=ensure_ascii,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise SerializationError(f"Failed to serialize DocumentIR to JSON: {exc}") from exc


def deserialize_document_ir(
    payload: Union[str, bytes, bytearray],
    *,
    validate: bool = True,
) -> DocumentIR:
    """Deserialize a JSON AST string or UTF-8 bytes back into a validated DocumentIR.

    Args:
        payload: JSON text string or UTF-8 encoded JSON bytes.
        validate: When True, validate reconstructed DocumentIR invariants.

    Returns:
        Reconstructed DocumentIR instance.

    Raises:
        SerializationError: If payload is malformed JSON or violates AST schema.
        IRValidationError: If validate=True and reconstructed IR fails invariant checks.
    """
    if isinstance(payload, (bytes, bytearray)):
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SerializationError(f"Invalid UTF-8 in JSON AST payload: {exc}") from exc
    elif isinstance(payload, str):
        text = payload
    else:
        raise SerializationError(f"Expected str or bytes payload, got {type(payload).__name__}")

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SerializationError(f"Malformed JSON AST payload: {exc}") from exc

    return document_ir_from_dict(parsed, validate=validate)


__all__ = [
    "JSON_AST_SCHEMA_VERSION",
    "SUPPORTED_SCHEMA_VERSIONS",
    "document_ir_to_dict",
    "document_ir_from_dict",
    "serialize_document_ir",
    "deserialize_document_ir",
    "validate_json_ast_schema",
]
