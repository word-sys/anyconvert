"""
Converters for PDF to Raster and Vector Images (PNG, JPEG, WebP, TIFF, SVG).
Supports high-DPI rendering, alpha transparency, and multi-page batch output.
"""

import io
from pathlib import Path
from typing import List, Optional

from PIL import Image
import pymupdf

from anyconvert.converters.base import BaseConverter
from anyconvert.core.options import ConversionOptions, ConversionResult
from anyconvert.core.registry import register_converter


class BasePdfToImageConverter(BaseConverter):
    """Base class for rendering PDF pages to image formats."""

    image_format = "png"
    supports_alpha = True

    def _render_page_pixmap(
        self,
        page: pymupdf.Page,
        dpi: int = 300,
        alpha: bool = True,
    ) -> pymupdf.Pixmap:
        """Render a PDF page to a high-DPI Pixmap."""
        zoom = dpi / 72.0
        mat = pymupdf.Matrix(zoom, zoom)
        return page.get_pixmap(matrix=mat, alpha=(alpha and self.supports_alpha))

    def convert_file(
        self,
        source_path: Path,
        target_path: Path,
        options: Optional[ConversionOptions] = None,
    ) -> ConversionResult:
        opts = options or ConversionOptions()
        doc = pymupdf.open(str(source_path))

        try:
            total_pages = doc.page_count
            pages = opts.parse_pages(total_pages)
            if not pages:
                pages = [0]

            target_path.parent.mkdir(parents=True, exist_ok=True)
            rendered_files: List[str] = []

            for idx, p_num in enumerate(pages):
                if opts.cancellation_token:
                    opts.cancellation_token.check_cancelled()

                if opts.progress_callback:
                    opts.progress_callback(idx + 1, len(pages), f"Rendering page {p_num + 1} to {self.image_format.upper()}")

                page = doc[p_num]
                pix = self._render_page_pixmap(page, dpi=opts.dpi, alpha=self.supports_alpha)

                if len(pages) == 1:
                    out_file = target_path
                else:
                    out_file = target_path.parent / f"{target_path.stem}_page_{p_num + 1}{target_path.suffix}"

                self._save_pixmap(pix, out_file)
                rendered_files.append(str(out_file))

            return ConversionResult(
                success=True,
                output_path=rendered_files[0] if rendered_files else str(target_path),
                page_count=len(pages),
                images_count=len(rendered_files),
                metadata={"rendered_files": rendered_files},
            )

        finally:
            doc.close()

    def convert_bytes(
        self,
        data: bytes,
        options: Optional[ConversionOptions] = None,
    ) -> bytes:
        opts = options or ConversionOptions()
        doc = pymupdf.open(stream=data, filetype="pdf")

        try:
            pages = opts.parse_pages(doc.page_count)
            p_num = pages[0] if pages else 0
            page = doc[p_num]
            pix = self._render_page_pixmap(page, dpi=opts.dpi, alpha=self.supports_alpha)
            return self._pixmap_to_bytes(pix)
        finally:
            doc.close()

    def _save_pixmap(self, pix: pymupdf.Pixmap, out_path: Path) -> None:
        """Save a pixmap to the target image format."""
        raw_bytes = self._pixmap_to_bytes(pix)
        out_path.write_bytes(raw_bytes)

    def _pixmap_to_bytes(self, pix: pymupdf.Pixmap) -> bytes:
        """Convert pixmap to target image format bytes."""
        if self.image_format == "png":
            return pix.tobytes("png")

        # Convert via Pillow for advanced formats (WebP, JPEG, TIFF)
        png_data = pix.tobytes("png")
        img = Image.open(io.BytesIO(png_data))

        out_buf = io.BytesIO()
        if self.image_format == "jpeg":
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGB")
            img.save(out_buf, format="JPEG", quality=95)
        elif self.image_format == "webp":
            img.save(out_buf, format="WEBP", quality=90, lossless=False)
        elif self.image_format == "tiff":
            img.save(out_buf, format="TIFF", compression="tiff_lzw")
        else:
            img.save(out_buf, format=self.image_format.upper())

        return out_buf.getvalue()


@register_converter
class PdfToPngConverter(BasePdfToImageConverter):
    """Converts PDF pages to PNG images."""
    source_format = "pdf"
    target_format = "png"
    image_format = "png"
    supports_alpha = True


@register_converter
class PdfToJpegConverter(BasePdfToImageConverter):
    """Converts PDF pages to JPEG images."""
    source_format = "pdf"
    target_format = "jpeg"
    image_format = "jpeg"
    supports_alpha = False


@register_converter
class PdfToWebpConverter(BasePdfToImageConverter):
    """Converts PDF pages to WebP images."""
    source_format = "pdf"
    target_format = "webp"
    image_format = "webp"
    supports_alpha = True


@register_converter
class PdfToTiffConverter(BasePdfToImageConverter):
    """Converts PDF pages to TIFF images."""
    source_format = "pdf"
    target_format = "tiff"
    image_format = "tiff"
    supports_alpha = False


@register_converter
class PdfToSvgConverter(BaseConverter):
    """Converts PDF pages to Scalable Vector Graphics (SVG)."""
    source_format = "pdf"
    target_format = "svg"

    def convert_file(
        self,
        source_path: Path,
        target_path: Path,
        options: Optional[ConversionOptions] = None,
    ) -> ConversionResult:
        opts = options or ConversionOptions()
        doc = pymupdf.open(str(source_path))

        try:
            pages = opts.parse_pages(doc.page_count)
            if not pages:
                pages = [0]

            target_path.parent.mkdir(parents=True, exist_ok=True)
            rendered_files: List[str] = []

            for idx, p_num in enumerate(pages):
                if opts.cancellation_token:
                    opts.cancellation_token.check_cancelled()

                if opts.progress_callback:
                    opts.progress_callback(idx + 1, len(pages), f"Converting page {p_num + 1} to SVG")

                page = doc[p_num]
                svg_text = page.get_svg_image()

                if len(pages) == 1:
                    out_file = target_path
                else:
                    out_file = target_path.parent / f"{target_path.stem}_page_{p_num + 1}.svg"

                out_file.write_text(svg_text, encoding="utf-8")
                rendered_files.append(str(out_file))

            return ConversionResult(
                success=True,
                output_path=rendered_files[0] if rendered_files else str(target_path),
                page_count=len(pages),
                images_count=len(rendered_files),
                metadata={"rendered_files": rendered_files},
            )

        finally:
            doc.close()

    def convert_bytes(
        self,
        data: bytes,
        options: Optional[ConversionOptions] = None,
    ) -> bytes:
        opts = options or ConversionOptions()
        doc = pymupdf.open(stream=data, filetype="pdf")
        try:
            pages = opts.parse_pages(doc.page_count)
            p_num = pages[0] if pages else 0
            svg_text = doc[p_num].get_svg_image()
            return svg_text.encode("utf-8")
        finally:
            doc.close()
