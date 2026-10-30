"""Semantic Flow Mode Plaintext / Markdown emitter."""

from __future__ import annotations

from typing import List

from anyconvert.emitters.md.emitter import MarkdownDialect, MarkdownEmitter
from anyconvert.ir.model import BlockNode, ImageBlock, Paragraph, Table


class TxtFlowEmitter(MarkdownEmitter):
    """Semantic Flow Plaintext / Markdown emitter generating clean reflowable text."""

    def __init__(self) -> None:
        super().__init__(dialect=MarkdownDialect.GFM)

    def _render_block(self, block: BlockNode, image_counter: List[int]) -> str:
        return self.render_block(block, image_counter)

    def _render_paragraph(self, p: Paragraph) -> str:
        return self.render_paragraph(p)

    def _render_table(self, table: Table) -> str:
        return self.render_table(table)

    def _render_image(self, img: ImageBlock, image_counter: List[int]) -> str:
        return self.render_image(img, image_counter)


__all__ = ["TxtFlowEmitter"]
