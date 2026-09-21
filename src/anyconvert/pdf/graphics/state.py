"""Graphics state stack and text state tracking for PDF content streams.

Adheres to ISO 32000-1 §8.4 (Graphics State) and §9.3 (Text State):
- GraphicsState: CTM, clipping paths, stroke/fill colors, alpha, blend modes, line attributes.
- TextState: Font, size, character/word spacing, horizontal scaling, leading, rise, Tm, Tlm.
- GraphicsStateStack: State save ('q') and restore ('Q') stack.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from anyconvert.common.color import Color
from anyconvert.common.geometry import BoundingBox, Matrix3x3, Point


@dataclass
class GraphicsState:
    """Represents the device-independent graphics state at a point in execution."""

    ctm: Matrix3x3 = field(default_factory=Matrix3x3.identity)
    stroke_color: Color = field(default_factory=lambda: Color(0, 0, 0, 1.0))
    fill_color: Color = field(default_factory=lambda: Color(0, 0, 0, 1.0))
    stroke_alpha: float = 1.0
    fill_alpha: float = 1.0
    blend_mode: str = "Normal"
    line_width: float = 1.0
    line_cap: int = 0  # 0=butt, 1=round, 2=projecting square
    line_join: int = 0  # 0=miter, 1=round, 2=bevel
    miter_limit: float = 10.0
    dash_array: List[float] = field(default_factory=list)
    dash_phase: float = 0.0
    clipping_bbox: Optional[BoundingBox] = None

    def copy(self) -> GraphicsState:
        """Create a deep copy of this graphics state for the 'q' operator."""
        return GraphicsState(
            ctm=self.ctm,
            stroke_color=self.stroke_color,
            fill_color=self.fill_color,
            stroke_alpha=self.stroke_alpha,
            fill_alpha=self.fill_alpha,
            blend_mode=self.blend_mode,
            line_width=self.line_width,
            line_cap=self.line_cap,
            line_join=self.line_join,
            miter_limit=self.miter_limit,
            dash_array=list(self.dash_array),
            dash_phase=self.dash_phase,
            clipping_bbox=self.clipping_bbox,
        )


@dataclass
class TextState:
    """Tracks active text state variables and text matrices (ISO 32000-1 §9.3)."""

    char_spacing: float = 0.0  # Tc
    word_spacing: float = 0.0  # Tw
    horizontal_scaling: float = 100.0  # Th (percentage)
    leading: float = 0.0  # Tl
    font_name: str = ""  # Tf font identifier
    font_size: float = 10.0  # Tf font size
    render_mode: int = 0  # Tr (0=fill, 1=stroke, etc.)
    rise: float = 0.0  # Ts (text rise)

    matrix: Matrix3x3 = field(default_factory=Matrix3x3.identity)  # Tm
    line_matrix: Matrix3x3 = field(default_factory=Matrix3x3.identity)  # Tlm

    def reset_for_bt(self) -> None:
        """Reset text matrices upon entering a text object ('BT')."""
        self.matrix = Matrix3x3.identity()
        self.line_matrix = Matrix3x3.identity()

    def copy(self) -> TextState:
        """Create a copy of current text state."""
        return TextState(
            char_spacing=self.char_spacing,
            word_spacing=self.word_spacing,
            horizontal_scaling=self.horizontal_scaling,
            leading=self.leading,
            font_name=self.font_name,
            font_size=self.font_size,
            render_mode=self.render_mode,
            rise=self.rise,
            matrix=self.matrix,
            line_matrix=self.line_matrix,
        )


class GraphicsStateStack:
    """Manages the graphics state stack via 'q' (push) and 'Q' (pop) operators."""

    __slots__ = ("_stack",)

    def __init__(self, initial_state: Optional[GraphicsState] = None) -> None:
        self._stack: List[GraphicsState] = [initial_state if initial_state is not None else GraphicsState()]

    @property
    def current(self) -> GraphicsState:
        """Return the active graphics state at the top of the stack."""
        return self._stack[-1]

    def push(self) -> None:
        """Push a copy of the current graphics state ('q')."""
        self._stack.append(self.current.copy())

    def pop(self) -> GraphicsState:
        """Restore the previous graphics state ('Q').

        If the stack contains only one state, it remains in place to prevent underflow.
        """
        if len(self._stack) > 1:
            return self._stack.pop()
        return self.current
