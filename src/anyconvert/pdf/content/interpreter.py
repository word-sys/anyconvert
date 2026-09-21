"""PDF Content Stream Interpreter and Graphics State Evaluator.

Adheres to ISO 32000-1 §8 (Graphics) and §9 (Text):
- Evaluates graphics state operators ('q', 'Q', 'cm', 'w', 'J', 'j', 'M', 'd', 'gs').
- Evaluates color operators ('g', 'G', 'rg', 'RG', 'k', 'K', 'cs', 'CS', 'sc', 'SC', 'scn', 'SCN').
- Evaluates path construction ('m', 'l', 'c', 'v', 'y', 're', 'h') and painting ('S', 's', 'f', 'f*', 'B', 'B*', 'b', 'b*', 'n', 'W', 'W*').
- Evaluates text state and objects ('BT', 'ET', 'Tc', 'Tw', 'Tz', 'TL', 'Tf', 'Tr', 'Ts').
- Evaluates text positioning ('Td', 'TD', 'Tm', 'T*') and text showing ('Tj', ''', '"', 'TJ').
- Evaluates XObject invocations ('Do') for Images and nested Form XObjects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Union

from anyconvert.common.color import Color
from anyconvert.common.geometry import BoundingBox, Matrix3x3, Point
from anyconvert.pdf.graphics.path import VectorPath
from anyconvert.pdf.graphics.state import GraphicsState, GraphicsStateStack, TextState
from anyconvert.pdf.lexer import PDFLexer, Token, TokenType
from anyconvert.pdf.parser import PDFArray, PDFDict, PDFIndirectRef, PDFName, PDFStream
from anyconvert.pdf.typography.cmap import CMap
from anyconvert.pdf.typography.composite import CompositeFont
from anyconvert.pdf.typography.encodings import EncodingResolver
from anyconvert.pdf.typography.font import BaseFont
from anyconvert.pdf.typography.sfnt import SFNTFont
from anyconvert.pdf.typography.type1 import Type1Font
from anyconvert.pdf.xref import XRefResolver


@dataclass(frozen=True, slots=True)
class TextElement:
    """Represents a rendered glyph or character extracted from the content stream."""

    text: str
    bbox: BoundingBox
    origin: Point
    font_name: str
    font_size: float
    color: Color
    char_spacing: float = 0.0
    word_spacing: float = 0.0
    horizontal_scaling: float = 100.0
    is_bold: bool = False
    is_italic: bool = False


@dataclass(frozen=True, slots=True)
class VectorElement:
    """Represents a stroked or filled vector path shape."""

    svg_path: str
    bbox: Optional[BoundingBox]
    fill_color: Optional[Color] = None
    stroke_color: Optional[Color] = None
    stroke_width: float = 1.0
    fill_rule: str = "nonzero"  # "nonzero" or "evenodd"
    fill_alpha: float = 1.0
    stroke_alpha: float = 1.0


@dataclass(frozen=True, slots=True)
class ImageElement:
    """Represents a raster image or XObject placement ('Do')."""

    name: str
    ctm: Matrix3x3
    bbox: BoundingBox


@dataclass
class InterpreterOutput:
    """Aggregated visual elements extracted from a content stream."""

    text_elements: List[TextElement] = field(default_factory=list)
    vector_elements: List[VectorElement] = field(default_factory=list)
    image_elements: List[ImageElement] = field(default_factory=list)


class ContentInterpreter:
    """Evaluates PDF page content streams and extracts text, paths, and images."""

    __slots__ = (
        "_resources",
        "_resolver",
        "_state_stack",
        "_text_state",
        "_current_path",
        "_fonts",
        "_text_elements",
        "_vector_elements",
        "_image_elements",
    )

    def __init__(
        self,
        resources: Optional[PDFDict] = None,
        resolver: Optional[XRefResolver] = None,
    ) -> None:
        """Initialize ContentInterpreter.

        Args:
            resources: Page or Form resource dictionary containing /Font, /XObject, /ExtGState.
            resolver: Optional XRefResolver to dereference indirect objects.
        """
        self._resources: PDFDict = resources if resources is not None else PDFDict()
        self._resolver: Optional[XRefResolver] = resolver
        self._state_stack: GraphicsStateStack = GraphicsStateStack()
        self._text_state: TextState = TextState()
        self._current_path: VectorPath = VectorPath()
        self._fonts: Dict[str, BaseFont] = {}
        self._text_elements: List[TextElement] = []
        self._vector_elements: List[VectorElement] = []
        self._image_elements: List[ImageElement] = []

    def _dereference(self, obj: Any) -> Any:
        """Dereference indirect object if resolver is provided."""
        if self._resolver is not None:
            return self._resolver.dereference(obj)
        return obj

    def interpret(
        self,
        stream_data: Union[bytes, memoryview, str, Sequence[Union[bytes, memoryview, str]]],
    ) -> InterpreterOutput:
        """Parse and evaluate one or more content streams.

        Args:
            stream_data: Content stream bytes, or sequence of multiple streams.

        Returns:
            InterpreterOutput: Aggregated text, vector, and image elements.
        """
        if isinstance(stream_data, (bytes, memoryview, str)):
            self._interpret_single(stream_data)
        else:
            for s in stream_data:
                self._interpret_single(s)

        return InterpreterOutput(
            text_elements=list(self._text_elements),
            vector_elements=list(self._vector_elements),
            image_elements=list(self._image_elements),
        )

    def _interpret_single(self, stream_data: Union[bytes, memoryview, str]) -> None:
        """Execute a single content stream."""
        if isinstance(stream_data, str):
            raw_bytes: Union[bytes, memoryview] = stream_data.encode("latin-1")
        else:
            raw_bytes = stream_data

        lexer = PDFLexer(raw_bytes)
        stack: List[Any] = []

        while True:
            token = lexer.next_token()
            if token.type == TokenType.EOF:
                break

            if token.type in (
                TokenType.NUMBER,
                TokenType.STRING,
                TokenType.HEX_STRING,
                TokenType.NAME,
                TokenType.BOOLEAN,
            ):
                stack.append(token.value)
            elif token.type == TokenType.DELIMITER and token.value == "[":
                arr = self._read_array(lexer)
                stack.append(arr)
            elif token.type == TokenType.KEYWORD:
                op = str(token.value)
                self._dispatch_operator(op, stack)
                stack.clear()

    def _read_array(self, lexer: PDFLexer) -> List[Any]:
        """Read array contents until closing bracket ']'."""
        arr: List[Any] = []
        while True:
            tok = lexer.next_token()
            if tok.type == TokenType.EOF:
                break
            if tok.type == TokenType.DELIMITER and tok.value == "]":
                break
            if tok.type in (
                TokenType.NUMBER,
                TokenType.STRING,
                TokenType.HEX_STRING,
                TokenType.NAME,
                TokenType.BOOLEAN,
            ):
                arr.append(tok.value)
            elif tok.type == TokenType.DELIMITER and tok.value == "[":
                arr.append(self._read_array(lexer))
        return arr

    def _dispatch_operator(self, op: str, stack: List[Any]) -> None:
        """Evaluate operator with collected operands."""
        # 1. Graphics State Operators
        if op == "q":
            self._state_stack.push()
        elif op == "Q":
            self._state_stack.pop()
        elif op == "cm":
            if len(stack) >= 6:
                try:
                    a = float(stack[-6])
                    b = float(stack[-5])
                    c = float(stack[-4])
                    d = float(stack[-3])
                    e = float(stack[-2])
                    f = float(stack[-1])
                    m = Matrix3x3(a, b, c, d, e, f)
                    self._state_stack.current.ctm = m.multiply(self._state_stack.current.ctm)
                except (ValueError, TypeError):
                    pass
        elif op == "w":
            if stack:
                try:
                    self._state_stack.current.line_width = float(stack[-1])
                except (ValueError, TypeError):
                    pass
        elif op == "J":
            if stack:
                try:
                    self._state_stack.current.line_cap = int(stack[-1])
                except (ValueError, TypeError):
                    pass
        elif op == "j":
            if stack:
                try:
                    self._state_stack.current.line_join = int(stack[-1])
                except (ValueError, TypeError):
                    pass
        elif op == "M":
            if stack:
                try:
                    self._state_stack.current.miter_limit = float(stack[-1])
                except (ValueError, TypeError):
                    pass
        elif op == "d":
            if len(stack) >= 2 and isinstance(stack[-2], list):
                try:
                    self._state_stack.current.dash_array = [float(x) for x in stack[-2]]
                    self._state_stack.current.dash_phase = float(stack[-1])
                except (ValueError, TypeError):
                    pass
        elif op == "gs":
            if stack:
                self._apply_ext_gstate(str(stack[-1]))

        # 2. Color Operators
        elif op == "g":
            if stack:
                try:
                    v = float(stack[-1])
                    self._state_stack.current.fill_color = Color.from_gray(
                        v, a=self._state_stack.current.fill_alpha
                    )
                except (ValueError, TypeError):
                    pass
        elif op == "G":
            if stack:
                try:
                    v = float(stack[-1])
                    self._state_stack.current.stroke_color = Color.from_gray(
                        v, a=self._state_stack.current.stroke_alpha
                    )
                except (ValueError, TypeError):
                    pass
        elif op == "rg":
            if len(stack) >= 3:
                try:
                    r, g, b = float(stack[-3]), float(stack[-2]), float(stack[-1])
                    self._state_stack.current.fill_color = Color.from_rgb_float(
                        r, g, b, a=self._state_stack.current.fill_alpha
                    )
                except (ValueError, TypeError):
                    pass
        elif op == "RG":
            if len(stack) >= 3:
                try:
                    r, g, b = float(stack[-3]), float(stack[-2]), float(stack[-1])
                    self._state_stack.current.stroke_color = Color.from_rgb_float(
                        r, g, b, a=self._state_stack.current.stroke_alpha
                    )
                except (ValueError, TypeError):
                    pass
        elif op == "k":
            if len(stack) >= 4:
                try:
                    cyan, mag, yel, blk = (
                        float(stack[-4]),
                        float(stack[-3]),
                        float(stack[-2]),
                        float(stack[-1]),
                    )
                    self._state_stack.current.fill_color = Color.from_cmyk(
                        cyan, mag, yel, blk, a=self._state_stack.current.fill_alpha
                    )
                except (ValueError, TypeError):
                    pass
        elif op == "K":
            if len(stack) >= 4:
                try:
                    cyan, mag, yel, blk = (
                        float(stack[-4]),
                        float(stack[-3]),
                        float(stack[-2]),
                        float(stack[-1]),
                    )
                    self._state_stack.current.stroke_color = Color.from_cmyk(
                        cyan, mag, yel, blk, a=self._state_stack.current.stroke_alpha
                    )
                except (ValueError, TypeError):
                    pass

        # 3. Path Construction Operators
        elif op == "m":
            if len(stack) >= 2:
                try:
                    self._current_path.move_to(float(stack[-2]), float(stack[-1]))
                except (ValueError, TypeError):
                    pass
        elif op == "l":
            if len(stack) >= 2:
                try:
                    self._current_path.line_to(float(stack[-2]), float(stack[-1]))
                except (ValueError, TypeError):
                    pass
        elif op == "c":
            if len(stack) >= 6:
                try:
                    self._current_path.curve_to(
                        float(stack[-6]),
                        float(stack[-5]),
                        float(stack[-4]),
                        float(stack[-3]),
                        float(stack[-2]),
                        float(stack[-1]),
                    )
                except (ValueError, TypeError):
                    pass
        elif op == "v":
            if len(stack) >= 4:
                try:
                    self._current_path.curve_to_v(
                        float(stack[-4]),
                        float(stack[-3]),
                        float(stack[-2]),
                        float(stack[-1]),
                    )
                except (ValueError, TypeError):
                    pass
        elif op == "y":
            if len(stack) >= 4:
                try:
                    self._current_path.curve_to_y(
                        float(stack[-4]),
                        float(stack[-3]),
                        float(stack[-2]),
                        float(stack[-1]),
                    )
                except (ValueError, TypeError):
                    pass
        elif op == "re":
            if len(stack) >= 4:
                try:
                    self._current_path.rectangle(
                        float(stack[-4]),
                        float(stack[-3]),
                        float(stack[-2]),
                        float(stack[-1]),
                    )
                except (ValueError, TypeError):
                    pass
        elif op == "h":
            self._current_path.close_path()

        # 4. Path Painting Operators
        elif op == "S":
            self._emit_vector(stroke=True, fill=False)
        elif op == "s":
            self._current_path.close_path()
            self._emit_vector(stroke=True, fill=False)
        elif op in ("f", "F"):
            self._emit_vector(stroke=False, fill=True, fill_rule="nonzero")
        elif op == "f*":
            self._emit_vector(stroke=False, fill=True, fill_rule="evenodd")
        elif op == "B":
            self._emit_vector(stroke=True, fill=True, fill_rule="nonzero")
        elif op == "B*":
            self._emit_vector(stroke=True, fill=True, fill_rule="evenodd")
        elif op == "b":
            self._current_path.close_path()
            self._emit_vector(stroke=True, fill=True, fill_rule="nonzero")
        elif op == "b*":
            self._current_path.close_path()
            self._emit_vector(stroke=True, fill=True, fill_rule="evenodd")
        elif op == "n":
            self._current_path.clear()
        elif op == "W":
            self._state_stack.current.clipping_bbox = self._current_path.compute_bbox(
                self._state_stack.current.ctm
            )
        elif op == "W*":
            self._state_stack.current.clipping_bbox = self._current_path.compute_bbox(
                self._state_stack.current.ctm
            )

        # 5. Text State & Objects
        elif op == "BT":
            self._text_state.reset_for_bt()
        elif op == "ET":
            pass
        elif op == "Tc":
            if stack:
                try:
                    self._text_state.char_spacing = float(stack[-1])
                except (ValueError, TypeError):
                    pass
        elif op == "Tw":
            if stack:
                try:
                    self._text_state.word_spacing = float(stack[-1])
                except (ValueError, TypeError):
                    pass
        elif op == "Tz":
            if stack:
                try:
                    self._text_state.horizontal_scaling = float(stack[-1])
                except (ValueError, TypeError):
                    pass
        elif op == "TL":
            if stack:
                try:
                    self._text_state.leading = float(stack[-1])
                except (ValueError, TypeError):
                    pass
        elif op == "Tf":
            if len(stack) >= 2:
                try:
                    self._text_state.font_name = str(stack[-2])
                    self._text_state.font_size = float(stack[-1])
                except (ValueError, TypeError):
                    pass
        elif op == "Tr":
            if stack:
                try:
                    self._text_state.render_mode = int(stack[-1])
                except (ValueError, TypeError):
                    pass
        elif op == "Ts":
            if stack:
                try:
                    self._text_state.rise = float(stack[-1])
                except (ValueError, TypeError):
                    pass

        # 6. Text Positioning Operators
        elif op == "Td":
            if len(stack) >= 2:
                try:
                    tx, ty = float(stack[-2]), float(stack[-1])
                    m = Matrix3x3.translation(tx, ty).multiply(self._text_state.line_matrix)
                    self._text_state.line_matrix = m
                    self._text_state.matrix = m
                except (ValueError, TypeError):
                    pass
        elif op == "TD":
            if len(stack) >= 2:
                try:
                    tx, ty = float(stack[-2]), float(stack[-1])
                    self._text_state.leading = -ty
                    m = Matrix3x3.translation(tx, ty).multiply(self._text_state.line_matrix)
                    self._text_state.line_matrix = m
                    self._text_state.matrix = m
                except (ValueError, TypeError):
                    pass
        elif op == "Tm":
            if len(stack) >= 6:
                try:
                    a, b, c, d, e, f = [float(x) for x in stack[-6:]]
                    m = Matrix3x3(a, b, c, d, e, f)
                    self._text_state.matrix = m
                    self._text_state.line_matrix = m
                except (ValueError, TypeError):
                    pass
        elif op == "T*":
            m = Matrix3x3.translation(0.0, -self._text_state.leading).multiply(
                self._text_state.line_matrix
            )
            self._text_state.line_matrix = m
            self._text_state.matrix = m

        # 7. Text Showing Operators
        elif op == "Tj":
            if stack:
                self._show_text(stack[-1])
        elif op == "'":
            if stack:
                self._dispatch_operator("T*", [])
                self._show_text(stack[-1])
        elif op == '"':
            if len(stack) >= 3:
                try:
                    self._text_state.word_spacing = float(stack[-3])
                    self._text_state.char_spacing = float(stack[-2])
                    self._dispatch_operator("T*", [])
                    self._show_text(stack[-1])
                except (ValueError, TypeError):
                    pass
        elif op == "TJ":
            if stack and isinstance(stack[-1], list):
                self._show_text_array(stack[-1])

        # 8. XObject Invocation
        elif op == "Do":
            if stack:
                self._invoke_xobject(str(stack[-1]))

    def _show_text(self, text_arg: Any) -> None:
        """Process text string and emit TextElements for each glyph."""
        raw_bytes: bytes
        if isinstance(text_arg, bytes):
            raw_bytes = text_arg
        elif isinstance(text_arg, str):
            raw_bytes = text_arg.encode("latin-1")
        else:
            return

        if not raw_bytes:
            return

        font = self._resolve_font(self._text_state.font_name)
        font_size = self._text_state.font_size
        char_spacing = self._text_state.char_spacing
        word_spacing = self._text_state.word_spacing
        h_scale = self._text_state.horizontal_scaling / 100.0
        rise = self._text_state.rise
        color = self._state_stack.current.fill_color
        is_bold = font.metrics.is_bold
        is_italic = font.metrics.is_italic
        font_name = font.name

        asc = font.metrics.ascender if font.metrics.ascender != 0.0 else 800.0
        desc = font.metrics.descender if font.metrics.descender != 0.0 else -200.0

        is_composite = isinstance(font, CompositeFont)
        codes: List[int] = []

        if is_composite:
            i = 0
            length = len(raw_bytes)
            while i < length:
                if i + 1 < length:
                    cid = (raw_bytes[i] << 8) | raw_bytes[i + 1]
                    codes.append(cid)
                    i += 2
                else:
                    codes.append(raw_bytes[i])
                    i += 1
        else:
            codes = list(raw_bytes)

        for code in codes:
            u_char = font.to_unicode(code)
            w0 = font.get_width(code)

            is_space = u_char == " " or code == 32
            extra_spacing = char_spacing + (word_spacing if is_space else 0.0)
            tx = (w0 / 1000.0 * font_size + extra_spacing) * h_scale

            # Device-space origin
            pt = Point(0.0, rise)
            dev_origin = pt.transform(self._text_state.matrix).transform(self._state_stack.current.ctm)

            # Glyph bounding box in text space
            x0 = 0.0
            y0 = (desc / 1000.0) * font_size + rise
            x1 = max(1.0, (w0 / 1000.0) * font_size * h_scale)
            y1 = (asc / 1000.0) * font_size + rise

            total_matrix = self._text_state.matrix.multiply(self._state_stack.current.ctm)
            dev_bbox = BoundingBox(x0, y0, x1, y1).transform(total_matrix)

            self._text_elements.append(
                TextElement(
                    text=u_char,
                    bbox=dev_bbox,
                    origin=dev_origin,
                    font_name=font_name,
                    font_size=font_size,
                    color=color,
                    char_spacing=char_spacing,
                    word_spacing=word_spacing,
                    horizontal_scaling=self._text_state.horizontal_scaling,
                    is_bold=is_bold,
                    is_italic=is_italic,
                )
            )

            # Advance text matrix along x-axis
            self._text_state.matrix = Matrix3x3.translation(tx, 0.0).multiply(self._text_state.matrix)

    def _show_text_array(self, items: List[Any]) -> None:
        """Process TJ kerning and text elements."""
        font_size = self._text_state.font_size
        h_scale = self._text_state.horizontal_scaling / 100.0

        for item in items:
            if isinstance(item, (bytes, str)):
                self._show_text(item)
            elif isinstance(item, (int, float)):
                kern = float(item)
                dx = -(kern / 1000.0) * font_size * h_scale
                self._text_state.matrix = Matrix3x3.translation(dx, 0.0).multiply(
                    self._text_state.matrix
                )

    def _emit_vector(self, stroke: bool, fill: bool, fill_rule: str = "nonzero") -> None:
        """Emit current path as a VectorElement."""
        if self._current_path.is_empty:
            return

        svg = self._current_path.to_svg(self._state_stack.current.ctm)
        bbox = self._current_path.compute_bbox(self._state_stack.current.ctm)
        fill_col = self._state_stack.current.fill_color if fill else None
        stroke_col = self._state_stack.current.stroke_color if stroke else None

        self._vector_elements.append(
            VectorElement(
                svg_path=svg,
                bbox=bbox,
                fill_color=fill_col,
                stroke_color=stroke_col,
                stroke_width=self._state_stack.current.line_width,
                fill_rule=fill_rule,
                fill_alpha=self._state_stack.current.fill_alpha,
                stroke_alpha=self._state_stack.current.stroke_alpha,
            )
        )
        self._current_path.clear()

    def _apply_ext_gstate(self, name: str) -> None:
        """Apply parameters from ExtGState resource dictionary ('gs')."""
        ext_gstates = self._resources.get("ExtGState")
        if not isinstance(ext_gstates, PDFDict):
            return

        clean_name = name[1:] if name.startswith("/") else name
        gs_ref = ext_gstates.get(clean_name)
        if gs_ref is None:
            return

        gs_obj = self._dereference(gs_ref)
        if not isinstance(gs_obj, PDFDict):
            return

        # Alpha parameters
        if "ca" in gs_obj:
            try:
                self._state_stack.current.fill_alpha = float(self._dereference(gs_obj["ca"]))
            except (ValueError, TypeError):
                pass
        if "CA" in gs_obj:
            try:
                self._state_stack.current.stroke_alpha = float(self._dereference(gs_obj["CA"]))
            except (ValueError, TypeError):
                pass

        # Line attributes
        if "LW" in gs_obj:
            try:
                self._state_stack.current.line_width = float(self._dereference(gs_obj["LW"]))
            except (ValueError, TypeError):
                pass
        if "LC" in gs_obj:
            try:
                self._state_stack.current.line_cap = int(self._dereference(gs_obj["LC"]))
            except (ValueError, TypeError):
                pass
        if "LJ" in gs_obj:
            try:
                self._state_stack.current.line_join = int(self._dereference(gs_obj["LJ"]))
            except (ValueError, TypeError):
                pass
        if "BM" in gs_obj:
            bm = self._dereference(gs_obj["BM"])
            if isinstance(bm, (str, PDFName)):
                self._state_stack.current.blend_mode = (
                    bm.name if isinstance(bm, PDFName) else bm
                )

    def _invoke_xobject(self, name: str) -> None:
        """Invoke named XObject ('Do')."""
        xobjects = self._resources.get("XObject")
        if not isinstance(xobjects, PDFDict):
            return

        clean_name = name[1:] if name.startswith("/") else name
        xobj_ref = xobjects.get(clean_name)
        if xobj_ref is None:
            return

        xobj = self._dereference(xobj_ref)
        if not isinstance(xobj, PDFStream):
            return

        subtype = self._dereference(xobj.dict.get("Subtype"))
        st_name = subtype.name if isinstance(subtype, PDFName) else str(subtype)

        if st_name == "Image":
            bbox = BoundingBox(0.0, 0.0, 1.0, 1.0).transform(self._state_stack.current.ctm)
            self._image_elements.append(
                ImageElement(
                    name=clean_name,
                    ctm=self._state_stack.current.ctm,
                    bbox=bbox,
                )
            )
        elif st_name == "Form":
            # Nested Form XObject
            self._state_stack.push()
            if "Matrix" in xobj.dict:
                mat_ref = self._dereference(xobj.dict["Matrix"])
                if isinstance(mat_ref, (list, PDFArray)) and len(mat_ref) >= 6:
                    try:
                        m = Matrix3x3.from_pdf_array([float(self._dereference(x)) for x in mat_ref])
                        self._state_stack.current.ctm = m.multiply(self._state_stack.current.ctm)
                    except (ValueError, TypeError):
                        pass

            form_res = self._dereference(xobj.dict.get("Resources", self._resources))
            res_dict = form_res if isinstance(form_res, PDFDict) else self._resources

            sub_interp = ContentInterpreter(resources=res_dict, resolver=self._resolver)
            sub_interp._state_stack.current.ctm = self._state_stack.current.ctm
            sub_out = sub_interp.interpret(xobj.get_raw_bytes())

            self._text_elements.extend(sub_out.text_elements)
            self._vector_elements.extend(sub_out.vector_elements)
            self._image_elements.extend(sub_out.image_elements)

            self._state_stack.pop()

    def _resolve_font(self, font_name: str) -> BaseFont:
        """Resolve font dictionary into a BaseFont instance."""
        clean_name = font_name[1:] if font_name.startswith("/") else font_name
        if clean_name in self._fonts:
            return self._fonts[clean_name]

        fonts_dict = self._resources.get("Font")
        if isinstance(fonts_dict, PDFDict):
            font_ref = fonts_dict.get(clean_name)
            if font_ref is not None:
                font_obj = self._dereference(font_ref)
                if isinstance(font_obj, PDFDict):
                    font = self._build_font(clean_name, font_obj)
                    self._fonts[clean_name] = font
                    return font

        # Default fallback font
        fallback = BaseFont(name=clean_name or "Helvetica")
        self._fonts[clean_name] = fallback
        return fallback

    def _build_font(self, font_name: str, fd: PDFDict) -> BaseFont:
        """Construct BaseFont from font dictionary."""
        subtype_val = self._dereference(fd.get("Subtype"))
        subtype = subtype_val.name if isinstance(subtype_val, PDFName) else str(subtype_val)

        # 1. Type 0 Composite Font
        if subtype == "Type0":
            comp_font = CompositeFont(fd, resolver=self._resolver, name=font_name)
            # Check for /ToUnicode
            tu_val = fd.get("ToUnicode")
            if tu_val is not None:
                tu_obj = self._dereference(tu_val)
                if isinstance(tu_obj, PDFStream):
                    try:
                        cmap = CMap.parse(tu_obj.get_raw_bytes())
                        comp_font.to_unicode_map.update(cmap.mapping)
                    except Exception:
                        pass
            return comp_font

        # 2. FontDescriptor inspection for embedded streams
        font_desc_val = fd.get("FontDescriptor")
        font_desc = self._dereference(font_desc_val) if font_desc_val is not None else None

        if isinstance(font_desc, PDFDict):
            # TrueType / OpenType (/FontFile2)
            if "FontFile2" in font_desc:
                ff2 = self._dereference(font_desc["FontFile2"])
                if isinstance(ff2, PDFStream):
                    try:
                        return SFNTFont(ff2.get_raw_bytes(), name=font_name)
                    except Exception:
                        pass

            # Type 1 (/FontFile)
            if "FontFile" in font_desc:
                ff1 = self._dereference(font_desc["FontFile"])
                if isinstance(ff1, PDFStream):
                    try:
                        return Type1Font(ff1.get_raw_bytes(), name=font_name)
                    except Exception:
                        pass

        # 3. Simple font with Encoding and Widths
        base_font = BaseFont(name=font_name)

        # BaseFont name
        bf_name = self._dereference(fd.get("BaseFont"))
        if isinstance(bf_name, (str, PDFName)):
            base_font.name = bf_name.name if isinstance(bf_name, PDFName) else bf_name
            lowered = base_font.name.lower()
            if "bold" in lowered or "black" in lowered:
                base_font.metrics.is_bold = True
            if "italic" in lowered or "oblique" in lowered:
                base_font.metrics.is_italic = True
            if "courier" in lowered or "mono" in lowered:
                base_font.metrics.is_monospace = True

        # Resolve /Encoding
        enc_val = fd.get("Encoding")
        if enc_val is not None:
            resolver = EncodingResolver(enc_val, resolver=self._resolver)
            base_font.to_unicode_map.update(resolver.mapping)

        # Resolve /Widths, /FirstChar, /LastChar
        if "Widths" in fd and "FirstChar" in fd:
            try:
                first_char = int(self._dereference(fd["FirstChar"]))
                widths_raw = self._dereference(fd["Widths"])
                if isinstance(widths_raw, (list, PDFArray)):
                    for idx, w in enumerate(widths_raw):
                        w_num = float(self._dereference(w))
                        base_font.widths[first_char + idx] = w_num
            except (ValueError, TypeError):
                pass

        # Resolve /ToUnicode
        if "ToUnicode" in fd:
            tu_obj = self._dereference(fd["ToUnicode"])
            if isinstance(tu_obj, PDFStream):
                try:
                    cmap = CMap.parse(tu_obj.get_raw_bytes())
                    base_font.to_unicode_map.update(cmap.mapping)
                except Exception:
                    pass

        return base_font
