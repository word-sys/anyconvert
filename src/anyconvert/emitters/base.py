"""Base abstractions and coordinate conversion primitives for document emitters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
import io
from os import PathLike
from typing import BinaryIO, Union

from anyconvert.common.color import Color
from anyconvert.ir.model import DocumentIR


class ConversionMode(str, Enum):
    """Layout emission operational mode."""

    FLOW = "flow"
    CANVAS = "canvas"


# ==============================================================================
# Unit and Coordinate Conversion Helpers
# ==============================================================================

def pt_to_dxa(pt: float) -> int:
    """Convert typographic points (1/72 inch) to WordprocessingML twips/dxa (1/1440 inch)."""
    return int(round(pt * 20.0))


def pt_to_half_pt(pt: float) -> int:
    """Convert typographic points to WordprocessingML font size half-points (1/144 inch)."""
    return int(round(pt * 2.0))


def pt_to_emu(pt: float) -> int:
    """Convert typographic points to English Metric Units (EMU). 1 pt = 12,700 EMUs."""
    return int(round(pt * 12700.0))


def pt_to_hundredth_pt(pt: float) -> int:
    """Convert typographic points to PresentationML font size hundredths of a point (1/7200 inch)."""
    return int(round(pt * 100.0))


def color_to_hex(color: Color) -> str:
    """Convert a Color instance to a 6-character uppercase RGB hex string (e.g., '003366')."""
    return f"{color.r:02X}{color.g:02X}{color.b:02X}"


def xml_escape(text: str) -> str:
    """Escape text content for standard XML serialization."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


# ==============================================================================
# Base Emitter Class
# ==============================================================================

class BaseEmitter(ABC):
    """Abstract base class for all target document serialization engines."""

    @abstractmethod
    def emit(
        self,
        doc_ir: DocumentIR,
        mode: ConversionMode = ConversionMode.FLOW,
    ) -> bytes:
        """Serialize a DocumentIR container into the target document format bytes.

        Args:
            doc_ir: Validated DocumentIR object tree.
            mode: Layout mode ('flow' or 'canvas').

        Returns:
            Raw bytes of the emitted document package.
        """
        raise NotImplementedError

    def emit_to_file(
        self,
        doc_ir: DocumentIR,
        dest: Union[str, PathLike[str], BinaryIO],
        mode: ConversionMode = ConversionMode.FLOW,
    ) -> None:
        """Serialize DocumentIR directly to a file path or binary stream.

        Args:
            doc_ir: Validated DocumentIR object tree.
            dest: Target file path or open binary file-like stream.
            mode: Layout mode ('flow' or 'canvas').
        """
        payload = self.emit(doc_ir, mode=mode)
        if isinstance(dest, (str, PathLike)):
            with open(dest, "wb") as f:
                f.write(payload)
        else:
            dest.write(payload)


__all__ = [
    "ConversionMode",
    "BaseEmitter",
    "pt_to_dxa",
    "pt_to_half_pt",
    "pt_to_emu",
    "pt_to_hundredth_pt",
    "color_to_hex",
    "xml_escape",
]
