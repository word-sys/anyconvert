"""Markdown document emitter package supporting CommonMark and GitHub Flavored Markdown (GFM)."""

from __future__ import annotations

from anyconvert.emitters.md.emitter import (
    MarkdownDialect,
    MarkdownEmitter,
    resolve_dialect,
)

__all__ = [
    "MarkdownEmitter",
    "MarkdownDialect",
    "resolve_dialect",
]
