"""Single-File Self-Contained HTML Packaging Module.

Packages HTML documents into 100% self-contained, offline-portable single-file documents:
- Inlines all raster images as Base64 Data URIs (`data:{mime};base64,...`).
- Inlines SVG vector graphics and CSS styles without external stylesheet references.
- Injects document metadata (<meta name="author">, <meta name="description">, etc.).
- Enforces zero-telemetry offline security via Content-Security-Policy (<meta http-equiv="CSP">).
- Provides asset audit and verification helpers (is_self_contained, extract_embedded_images).
"""

from __future__ import annotations

import base64
import mimetypes
import pathlib
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from anyconvert.emitters.base import ConversionMode, xml_escape
from anyconvert.emitters.html.canvas import render_canvas_body
from anyconvert.emitters.html.css import build_default_css
from anyconvert.emitters.html.flow import render_flow_body
from anyconvert.exceptions import SerializationError
from anyconvert.ir.model import DocumentIR, detect_image_format

PACKAGE_VERSION = "0.1.11"

DATA_URI_PATTERN = re.compile(r'data:(image/[a-zA-Z0-9\+\-\.]+);base64,([A-Za-z0-9+/=]+)')
IMG_SRC_PATTERN = re.compile(r'<img\s+([^>]*?)src=["\']([^"\']+)["\']([^>]*?)>', re.IGNORECASE)
LINK_STYLESHEET_PATTERN = re.compile(
    r'<link\s+[^>]*?rel=["\']stylesheet["\'][^>]*?href=["\']([^"\']+)["\'][^>]*?>',
    re.IGNORECASE,
)
EXTERNAL_URL_PATTERN = re.compile(r'^(https?:)?//', re.IGNORECASE)


class HTMLPackager:
    """Packager for creating standalone, single-file, zero-dependency HTML documents."""

    def __init__(
        self,
        offline_csp: bool = True,
        generator_tag: str = f"anyconvert {PACKAGE_VERSION}",
    ) -> None:
        self.offline_csp = offline_csp
        self.generator_tag = generator_tag

    def package(
        self,
        doc_ir: DocumentIR,
        mode: ConversionMode = ConversionMode.FLOW,
        title: str = "",
        custom_css: str = "",
    ) -> str:
        """Package a DocumentIR into a single self-contained HTML5 string.

        Args:
            doc_ir: Validated DocumentIR hierarchy.
            mode: Conversion mode (FLOW or CANVAS).
            title: Document title override.
            custom_css: Optional additional CSS rules to append.

        Returns:
            Self-contained HTML5 document string.

        Raises:
            SerializationError: If doc_ir contains no pages.
        """
        if not doc_ir.pages:
            raise SerializationError("Cannot package empty DocumentIR into HTML")

        doc_title = title or doc_ir.metadata.get("Title", "Document")
        escaped_title = xml_escape(doc_title)

        css_parts = [build_default_css(mode=mode)]
        if custom_css.strip():
            css_parts.append(custom_css.strip())
        full_css = "\n\n".join(css_parts)

        # Build head meta elements
        meta_tags = self._build_meta_tags(doc_ir.metadata)

        # Render body content according to mode
        if mode == ConversionMode.CANVAS:
            body_content = render_canvas_body(doc_ir)
        else:
            body_content = render_flow_body(doc_ir)

        head_lines: List[str] = [
            '  <meta charset="UTF-8">',
            '  <meta name="viewport" content="width=device-width, initial-scale=1.0">',
        ]
        head_lines.extend(meta_tags)
        head_lines.append(f'  <title>{escaped_title}</title>')
        head_lines.append('  <style type="text/css">')
        head_lines.append(full_css)
        head_lines.append('  </style>')

        head_block = "\n".join(head_lines)

        return (
            '<!DOCTYPE html>\n'
            '<html lang="en">\n'
            '<head>\n'
            f'{head_block}\n'
            '</head>\n'
            '<body>\n'
            f'{body_content}\n'
            '</body>\n'
            '</html>'
        )

    def _build_meta_tags(self, metadata: Dict[str, Any]) -> List[str]:
        """Construct standard Dublin Core and HTML5 <meta> tags from document metadata."""
        tags: List[str] = [
            f'  <meta name="generator" content="{xml_escape(self.generator_tag)}">',
        ]

        if self.offline_csp:
            # Strict offline CSP: disallow all external network fetches
            csp = (
                "default-src 'none'; "
                "img-src 'self' data:; "
                "style-src 'unsafe-inline'; "
                "font-src 'self' data:;"
            )
            tags.append(f'  <meta http-equiv="Content-Security-Policy" content="{csp}">')

        meta_mapping = {
            "Author": "author",
            "Subject": "description",
            "Keywords": "keywords",
            "CreationDate": "date",
        }

        for ir_key, meta_name in meta_mapping.items():
            val = metadata.get(ir_key)
            if val and isinstance(val, str) and val.strip():
                tags.append(f'  <meta name="{meta_name}" content="{xml_escape(val.strip())}">')

        return tags

    def inline_resources(
        self,
        html_str: str,
        base_dir: Optional[Union[pathlib.Path, str]] = None,
    ) -> str:
        """Replace relative image and stylesheet references with inline Base64 / style tags.

        Args:
            html_str: HTML document content.
            base_dir: Directory against which relative paths are resolved.

        Returns:
            Fully inlined HTML string.
        """
        root = pathlib.Path(base_dir) if base_dir is not None else pathlib.Path.cwd()

        # 1. Inline external stylesheets: <link rel="stylesheet" href="...">
        def _replace_link(match: re.Match[str]) -> str:
            href = match.group(1).strip()
            if EXTERNAL_URL_PATTERN.match(href):
                return match.group(0)  # Cannot resolve remote URL offline
            css_path = root / href
            if css_path.is_file():
                try:
                    css_content = css_path.read_text(encoding="utf-8")
                    return f'<style type="text/css">\n{css_content}\n</style>'
                except Exception:
                    return match.group(0)
            return match.group(0)

        result = LINK_STYLESHEET_PATTERN.sub(_replace_link, html_str)

        # 2. Inline images: <img src="file.png"> -> <img src="data:image/png;base64,...">
        def _replace_img(match: re.Match[str]) -> str:
            prefix = match.group(1)
            src = match.group(2).strip()
            suffix = match.group(3)

            if src.startswith("data:") or EXTERNAL_URL_PATTERN.match(src):
                return match.group(0)

            img_path = root / src
            if img_path.is_file():
                try:
                    raw_data = img_path.read_bytes()
                    fmt = detect_image_format(raw_data)
                    mime = mimetypes.guess_type(img_path.name)[0] or f"image/{fmt}"
                    b64 = base64.b64encode(raw_data).decode("ascii")
                    return f'<img {prefix}src="data:{mime};base64,{b64}"{suffix}>'
                except Exception:
                    return match.group(0)
            return match.group(0)

        result = IMG_SRC_PATTERN.sub(_replace_img, result)
        return result

    def verify_self_contained(self, html_str: str) -> Tuple[bool, List[str]]:
        """Verify whether an HTML string is 100% self-contained without external dependencies.

        Args:
            html_str: HTML document string.

        Returns:
            Tuple of (is_self_contained, list_of_violations).
        """
        violations: List[str] = []

        # Check for remote image references
        for m in IMG_SRC_PATTERN.finditer(html_str):
            src = m.group(2).strip()
            if not src.startswith("data:"):
                violations.append(f"External image reference: {src}")

        # Check for external stylesheets
        for m in LINK_STYLESHEET_PATTERN.finditer(html_str):
            href = m.group(1).strip()
            violations.append(f"External stylesheet link: {href}")

        # Check for external script tags
        for m in re.finditer(r'<script\s+[^>]*?src=["\']([^"\']+)["\']', html_str, re.IGNORECASE):
            src = m.group(1).strip()
            violations.append(f"External script dependency: {src}")

        # Check for remote CSS font or asset imports
        for m in re.finditer(r'@import\s+url\(["\']?([^"\'\)]+)["\']?\)', html_str, re.IGNORECASE):
            url = m.group(1).strip()
            violations.append(f"External CSS @import rule: {url}")

        return (len(violations) == 0, violations)

    def extract_embedded_images(self, html_str: str) -> List[Tuple[str, bytes]]:
        """Extract all Base64 Data URI images embedded in the HTML document.

        Args:
            html_str: Standalone HTML string containing Data URIs.

        Returns:
            List of (mime_type, binary_bytes) tuples.
        """
        results: List[Tuple[str, bytes]] = []
        for m in DATA_URI_PATTERN.finditer(html_str):
            mime_type = m.group(1)
            b64_str = m.group(2)
            try:
                raw_bytes = base64.b64decode(b64_str)
                results.append((mime_type, raw_bytes))
            except Exception:
                continue
        return results


def package_html(
    doc_ir: DocumentIR,
    mode: ConversionMode = ConversionMode.FLOW,
    title: str = "",
    offline_csp: bool = True,
) -> str:
    """Convenience helper to package a DocumentIR into a self-contained HTML5 document."""
    packager = HTMLPackager(offline_csp=offline_csp)
    return packager.package(doc_ir, mode=mode, title=title)


def is_self_contained(html_str: str) -> bool:
    """Check if an HTML document has zero external dependencies."""
    packager = HTMLPackager()
    valid, _ = packager.verify_self_contained(html_str)
    return valid


def extract_embedded_images(html_str: str) -> List[Tuple[str, bytes]]:
    """Extract all Base64 images embedded in an HTML document."""
    packager = HTMLPackager()
    return packager.extract_embedded_images(html_str)


__all__ = [
    "HTMLPackager",
    "package_html",
    "is_self_contained",
    "extract_embedded_images",
]
