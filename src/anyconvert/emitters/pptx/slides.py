"""Dynamic slide dimension computation and coordinate scaling for PPTX (PresentationML).

Computes ISO/IEC 29500-1 <p:sldSz> dimensions directly from input PDF page bounding
boxes with full support for portrait/vertical, landscape, square, and widescreen
aspect ratios, PowerPoint EMU limit clamping (1 in to 56 in), and aspect-preserving
coordinate transforms for mixed-dimension multi-page PDFs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from anyconvert.common.geometry import BoundingBox
from anyconvert.emitters.base import pt_to_emu
from anyconvert.ir.model import DocumentPage

# ISO/IEC 29500-1 / Microsoft PowerPoint valid slide dimension bounds
PPTX_MIN_SLIDE_PT: float = 72.0     # 1 inch = 914,400 EMU
PPTX_MAX_SLIDE_PT: float = 4032.0   # 56 inches = 51,206,400 EMU
PPTX_MIN_SLIDE_EMU: int = 914400
PPTX_MAX_SLIDE_EMU: int = 51206400

# Standard notes page size (7.5 in x 10 in)
DEFAULT_NOTES_WIDTH_EMU: int = 6858000
DEFAULT_NOTES_HEIGHT_EMU: int = 9144000


@dataclass(frozen=True, slots=True)
class SlideDimensions:
    """Resolved presentation-wide slide dimensions and orientation metadata."""

    width_pt: float
    height_pt: float
    width_emu: int
    height_emu: int
    orientation: str      # 'portrait', 'landscape', or 'square'
    sld_sz_type: str      # 'screen4x3', 'screen16x9', 'screen16x10', or 'custom'
    notes_width_emu: int = DEFAULT_NOTES_WIDTH_EMU
    notes_height_emu: int = DEFAULT_NOTES_HEIGHT_EMU

    @property
    def aspect_ratio(self) -> float:
        """Return width / height aspect ratio."""
        return self.width_pt / self.height_pt if self.height_pt > 0.0 else 1.0


@dataclass(frozen=True, slots=True)
class SlideTransform:
    """Aspect-preserving affine scale and centering offset mapping a PDF page to a slide."""

    scale: float = 1.0
    offset_x_pt: float = 0.0
    offset_y_pt: float = 0.0

    @property
    def is_identity(self) -> bool:
        """Return True when the transform is a 1:1 identity mapping."""
        return (
            abs(self.scale - 1.0) < 1e-6
            and abs(self.offset_x_pt) < 1e-6
            and abs(self.offset_y_pt) < 1e-6
        )

    def map_pt(self, length_pt: float) -> float:
        """Scale a scalar length or font size in points."""
        return length_pt * self.scale

    def map_bbox(self, bbox: BoundingBox) -> BoundingBox:
        """Map a page-space BoundingBox into presentation slide coordinates."""
        if self.is_identity:
            return bbox
        return BoundingBox(
            x0=bbox.x0 * self.scale + self.offset_x_pt,
            y0=bbox.y0 * self.scale + self.offset_y_pt,
            x1=bbox.x1 * self.scale + self.offset_x_pt,
            y1=bbox.y1 * self.scale + self.offset_y_pt,
        )


def classify_slide_orientation(width_pt: float, height_pt: float) -> str:
    """Classify slide orientation as 'portrait', 'landscape', or 'square'."""
    if height_pt > width_pt + 1.0:
        return "portrait"
    if width_pt > height_pt + 1.0:
        return "landscape"
    return "square"


def infer_sld_sz_type(width_pt: float, height_pt: float, orientation: str) -> str:
    """Infer the ISO/IEC 29500-1 <p:sldSz type="..."/> attribute.

    Portrait and square slides always use 'custom' so PowerPoint preserves exact
    vertical/square cx and cy values instead of coercing to horizontal widescreen.
    """
    if orientation != "landscape":
        return "custom"
    # Standard 4:3 (10 in x 7.5 in = 720 pt x 540 pt)
    if abs(width_pt - 720.0) <= 2.0 and abs(height_pt - 540.0) <= 2.0:
        return "screen4x3"
    # Standard 16:9 widescreen (13.333 in x 7.5 in = 960 pt x 540 pt, or 10 in x 5.625 in = 720 x 405 pt)
    if (
        (abs(width_pt - 960.0) <= 2.0 and abs(height_pt - 540.0) <= 2.0)
        or (abs(width_pt - 720.0) <= 2.0 and abs(height_pt - 405.0) <= 2.0)
    ):
        return "screen16x9"
    # Standard 16:10 (10 in x 6.25 in = 720 pt x 450 pt)
    if abs(width_pt - 720.0) <= 2.0 and abs(height_pt - 450.0) <= 2.0:
        return "screen16x10"
    return "custom"


def compute_slide_dimensions(pages: Sequence[DocumentPage]) -> SlideDimensions:
    """Compute presentation slide dimensions from input DocumentPages.

    Derives the slide canvas from the first page's bounding box and uniformly
    scales only when dimensions fall outside PowerPoint's valid [1 in, 56 in]
    range, preserving the exact PDF aspect ratio and orientation.
    """
    if not pages:
        w_pt, h_pt = 720.0, 540.0
    else:
        w_pt = max(1.0, float(pages[0].width))
        h_pt = max(1.0, float(pages[0].height))

    # Uniformly scale down if exceeding PowerPoint's 56-inch maximum
    max_dim = max(w_pt, h_pt)
    if max_dim > PPTX_MAX_SLIDE_PT:
        factor = PPTX_MAX_SLIDE_PT / max_dim
        w_pt *= factor
        h_pt *= factor

    # Uniformly scale up if below PowerPoint's 1-inch minimum
    min_dim = min(w_pt, h_pt)
    if min_dim < PPTX_MIN_SLIDE_PT:
        factor = PPTX_MIN_SLIDE_PT / min_dim
        # Avoid exceeding max limit for extreme aspect ratios
        if max(w_pt, h_pt) * factor <= PPTX_MAX_SLIDE_PT:
            w_pt *= factor
            h_pt *= factor
        else:
            w_pt = max(PPTX_MIN_SLIDE_PT, min(PPTX_MAX_SLIDE_PT, w_pt))
            h_pt = max(PPTX_MIN_SLIDE_PT, min(PPTX_MAX_SLIDE_PT, h_pt))

    width_emu = max(PPTX_MIN_SLIDE_EMU, min(PPTX_MAX_SLIDE_EMU, pt_to_emu(w_pt)))
    height_emu = max(PPTX_MIN_SLIDE_EMU, min(PPTX_MAX_SLIDE_EMU, pt_to_emu(h_pt)))

    orientation = classify_slide_orientation(w_pt, h_pt)
    sld_sz_type = infer_sld_sz_type(w_pt, h_pt, orientation)

    return SlideDimensions(
        width_pt=w_pt,
        height_pt=h_pt,
        width_emu=width_emu,
        height_emu=height_emu,
        orientation=orientation,
        sld_sz_type=sld_sz_type,
    )


def compute_slide_transform(
    page: DocumentPage,
    slide_dims: SlideDimensions,
) -> SlideTransform:
    """Compute an aspect-preserving scale and centering offset for a page on the slide canvas."""
    pw = max(1.0, float(page.width))
    ph = max(1.0, float(page.height))

    if abs(pw - slide_dims.width_pt) <= 0.5 and abs(ph - slide_dims.height_pt) <= 0.5:
        return SlideTransform(scale=1.0, offset_x_pt=0.0, offset_y_pt=0.0)

    scale = min(slide_dims.width_pt / pw, slide_dims.height_pt / ph)
    scaled_w = pw * scale
    scaled_h = ph * scale
    offset_x = (slide_dims.width_pt - scaled_w) * 0.5
    offset_y = (slide_dims.height_pt - scaled_h) * 0.5
    return SlideTransform(scale=scale, offset_x_pt=offset_x, offset_y_pt=offset_y)


__all__ = [
    "PPTX_MIN_SLIDE_PT",
    "PPTX_MAX_SLIDE_PT",
    "PPTX_MIN_SLIDE_EMU",
    "PPTX_MAX_SLIDE_EMU",
    "SlideDimensions",
    "SlideTransform",
    "classify_slide_orientation",
    "infer_sld_sz_type",
    "compute_slide_dimensions",
    "compute_slide_transform",
]
