"""
Options, results, and cancellation tokens for anyconvert.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional, Union

from anyconvert.core.exceptions import CancelledError, ValidationError


class CancellationToken:
    """Thread-safe cancellation token for cancelling ongoing conversions."""

    def __init__(self) -> None:
        self._is_cancelled = False

    def cancel(self) -> None:
        """Trigger cancellation."""
        self._is_cancelled = True

    @property
    def is_cancelled(self) -> bool:
        """Check if cancellation has been requested."""
        return self._is_cancelled

    def check_cancelled(self) -> None:
        """Raise CancelledError if cancellation has been requested."""
        if self._is_cancelled:
            raise CancelledError("Conversion was cancelled by user or process.")


@dataclass
class ConversionOptions:
    """Configuration options for a document conversion."""

    # Mode: "flow" reconstructs reflowable paragraphs/tables, "precise" uses absolute positioning
    mode: Literal["flow", "precise"] = "flow"

    # Page range specification (e.g. "1-5, 8, 10-12"). None converts all pages.
    page_range: Optional[str] = None

    # Resolution (DPI) for rendering rasterized graphics or pages
    dpi: int = 300

    # Whether to extract and embed embedded images
    extract_images: bool = True

    # Whether to run table detection algorithms
    detect_tables: bool = True

    # Whether to infer heading levels (H1-H6) from font size/weight
    detect_headings: bool = True

    # Whether to preserve hyperlinks
    preserve_hyperlinks: bool = True

    # OCR fallback for scanned pages with no embedded text
    ocr_enabled: bool = False
    ocr_lang: str = "eng"

    # Password for encrypted documents
    password: Optional[str] = None

    # Number of worker threads/processes (1 for single-threaded)
    workers: int = 1

    # Optional callback reporting (current_page, total_pages, stage_description)
    progress_callback: Optional[Callable[[int, int, str], None]] = None

    # Optional cancellation token
    cancellation_token: Optional[CancellationToken] = None

    # Custom format-specific extra parameters
    extras: Dict[str, Any] = field(default_factory=dict)

    def parse_pages(self, total_pages: int) -> List[int]:
        """
        Parse the page_range string into a list of 0-based page indices.
        If page_range is None or empty, returns range(total_pages).
        """
        if total_pages <= 0:
            return []

        if not self.page_range or not self.page_range.strip():
            return list(range(total_pages))

        result_pages: set[int] = set()
        parts = [p.strip() for p in self.page_range.split(",") if p.strip()]

        for part in parts:
            if "-" in part:
                tokens = part.split("-", 1)
                start_str, end_str = tokens[0].strip(), tokens[1].strip()
                try:
                    start = int(start_str) if start_str else 1
                    end = int(end_str) if end_str else total_pages
                except ValueError:
                    raise ValidationError(f"Invalid page range token: '{part}'")

                # Convert 1-based to 0-based
                start_idx = max(0, start - 1)
                end_idx = min(total_pages, end)

                for p in range(start_idx, end_idx):
                    result_pages.add(p)
            else:
                try:
                    page_num = int(part)
                except ValueError:
                    raise ValidationError(f"Invalid page number: '{part}'")

                idx = page_num - 1
                if 0 <= idx < total_pages:
                    result_pages.add(idx)

        sorted_pages = sorted(result_pages)
        if not sorted_pages:
            raise ValidationError(
                f"Page range '{self.page_range}' resulted in no valid pages (total pages: {total_pages})."
            )
        return sorted_pages


@dataclass
class ConversionResult:
    """Result and metadata of a completed conversion."""

    success: bool
    output_path: Optional[str] = None
    output_bytes: Optional[bytes] = None
    source_format: str = ""
    target_format: str = ""
    page_count: int = 0
    tables_count: int = 0
    images_count: int = 0
    fidelity_score: float = 100.0
    warnings: List[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def write_to(self, target_path: Union[str, Path]) -> None:
        """Save in-memory output bytes to a destination file path."""
        if not self.output_bytes:
            raise ValueError("No in-memory output bytes available to write.")
        path = Path(target_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.output_bytes)
        self.output_path = str(path)


@dataclass
class DocumentInfo:
    """Metadata and structural information discovered from inspecting a document."""

    format: str
    page_count: int = 0
    title: Optional[str] = None
    author: Optional[str] = None
    creator: Optional[str] = None
    subject: Optional[str] = None
    keywords: Optional[str] = None
    is_encrypted: bool = False
    has_text: bool = True
    has_images: bool = False
    file_size_bytes: int = 0
    extra: Dict[str, Any] = field(default_factory=dict)
