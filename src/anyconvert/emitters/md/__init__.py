"""Markdown document emitter package supporting CommonMark and GitHub Flavored Markdown (GFM)."""

from __future__ import annotations

from anyconvert.emitters.md.emitter import (
    MarkdownDialect,
    MarkdownEmitter,
    resolve_dialect,
)
from anyconvert.emitters.md.frontmatter import (
    format_yaml_scalar,
    normalize_frontmatter_metadata,
    parse_keywords,
    render_yaml_frontmatter,
)
from anyconvert.emitters.md.tables import (
    build_delimiter_cells,
    build_table_matrix,
    escape_cell_text,
    format_table_matrix,
)

__all__ = [
    "MarkdownEmitter",
    "MarkdownDialect",
    "resolve_dialect",
    "format_yaml_scalar",
    "normalize_frontmatter_metadata",
    "parse_keywords",
    "render_yaml_frontmatter",
    "build_delimiter_cells",
    "build_table_matrix",
    "escape_cell_text",
    "format_table_matrix",
]
