"""High-level EPUB 3.3 e-book emitter orchestrating OCF, OPF, Nav/NCX, and XHTML chapters."""

from __future__ import annotations

from typing import List, Optional, Union

from anyconvert.emitters.base import BaseEmitter, ConversionMode
from anyconvert.emitters.epub.content import (
    DEFAULT_EPUB_CSS,
    ChapterRenderer,
    ChapterSplitStrategy,
    RenderedChapter,
    resolve_split_strategy,
    split_document_into_chapters,
)
from anyconvert.emitters.epub.nav import NavigationBuilder, TocEntry, build_toc_tree
from anyconvert.emitters.epub.opf import OPFMetadata, PackageDocument
from anyconvert.exceptions import SerializationError
from anyconvert.ir.model import DocumentIR
from anyconvert.packaging.epub import (
    MEDIA_TYPE_CSS,
    MEDIA_TYPE_NCX,
    MEDIA_TYPE_OPF,
    MEDIA_TYPE_XHTML,
    EPUBPackage,
)


class EpubEmitter(BaseEmitter):
    """Zero-dependency W3C EPUB 3.3 digital book emitter."""

    __slots__ = (
        "language",
        "split_strategy",
        "max_pages_per_chapter",
        "include_ncx",
        "custom_css",
    )

    def __init__(
        self,
        language: str = "en",
        split_strategy: Union[ChapterSplitStrategy, str] = ChapterSplitStrategy.AUTO,
        max_pages_per_chapter: int = 10,
        include_ncx: bool = True,
        custom_css: Optional[str] = None,
    ) -> None:
        self.language: str = language.strip().replace("_", "-") or "en"
        self.split_strategy: ChapterSplitStrategy = resolve_split_strategy(split_strategy)
        self.max_pages_per_chapter: int = max(1, int(max_pages_per_chapter))
        self.include_ncx: bool = include_ncx
        self.custom_css: Optional[str] = custom_css

    def build_package(self, doc_ir: DocumentIR) -> EPUBPackage:
        """Build a validated EPUBPackage from DocumentIR without serializing yet."""
        if not doc_ir.pages:
            raise SerializationError("Cannot emit EPUB from empty DocumentIR")

        opf_meta = OPFMetadata.from_ir_metadata(
            doc_ir.metadata,
            default_language=self.language,
        )

        # 1. Split document into reflowable chapter sections
        chapters = split_document_into_chapters(
            doc_ir,
            strategy=self.split_strategy,
            max_pages_per_chapter=self.max_pages_per_chapter,
        )

        # 2. Render each chapter to strict EPUB 3.3 XHTML and collect images + TOC entries
        renderer = ChapterRenderer(
            language=opf_meta.language,
            stylesheet_href="../Styles/style.css",
        )
        rendered_chapters: List[RenderedChapter] = []
        flat_toc: List[TocEntry] = []

        for chapter in chapters:
            rendered = renderer.render_chapter(chapter)
            rendered_chapters.append(rendered)
            flat_toc.extend(rendered.toc_entries)

        # 3. Build hierarchical TOC tree (fallback to chapter entries when no headings found)
        if flat_toc:
            toc_tree = build_toc_tree(flat_toc)
        else:
            toc_tree = [
                TocEntry(title=ch.title, href=ch.href, level=1)
                for ch in rendered_chapters
            ]

        first_href = rendered_chapters[0].href if rendered_chapters else "Text/chapter_1.xhtml"

        # 4. Generate nav.xhtml and legacy toc.ncx
        author_str = "; ".join(opf_meta.creators)
        nav_builder = NavigationBuilder(
            entries=toc_tree,
            identifier=opf_meta.identifier,
            title=opf_meta.title,
            author=author_str,
            language=opf_meta.language,
            stylesheet_href="Styles/style.css",
            default_href=first_href,
        )
        nav_bytes = nav_builder.build_nav_xhtml()
        ncx_bytes = nav_builder.build_toc_ncx() if self.include_ncx else None

        # 5. Build OPF Package Document (content.opf)
        opf = PackageDocument(metadata=opf_meta)
        opf.add_navigation(href="nav.xhtml", item_id="nav")
        if self.include_ncx:
            opf.add_ncx(href="toc.ncx", item_id="ncx")
        opf.add_stylesheet(href="Styles/style.css", item_id="css")

        for ch in rendered_chapters:
            props = "svg" if ch.has_svg else None
            opf.add_xhtml(
                item_id=ch.chapter_id,
                href=ch.href,
                in_spine=True,
                linear=True,
                properties=props,
            )

        for img_asset in renderer.extracted_images:
            opf.add_image(
                href=img_asset.href,
                item_id=img_asset.item_id,
                media_type=img_asset.media_type,
            )

        # 6. Assemble OCF 3.3 EPUBPackage
        css_payload = self.custom_css if self.custom_css is not None else DEFAULT_EPUB_CSS
        pkg = EPUBPackage()
        pkg.add_oebps_part(
            "content.opf",
            opf.to_bytes(require_nav=True),
            media_type=MEDIA_TYPE_OPF,
        )
        pkg.add_oebps_part("nav.xhtml", nav_bytes, media_type=MEDIA_TYPE_XHTML)
        if ncx_bytes is not None:
            pkg.add_oebps_part("toc.ncx", ncx_bytes, media_type=MEDIA_TYPE_NCX)
        pkg.add_oebps_part("Styles/style.css", css_payload, media_type=MEDIA_TYPE_CSS)

        for ch in rendered_chapters:
            pkg.add_oebps_part(ch.href, ch.xhtml_bytes, media_type=MEDIA_TYPE_XHTML)

        for img_asset in renderer.extracted_images:
            pkg.add_oebps_part(
                img_asset.href,
                img_asset.data,
                media_type=img_asset.media_type,
            )

        return pkg

    def emit(
        self,
        doc_ir: DocumentIR,
        mode: ConversionMode = ConversionMode.FLOW,
    ) -> bytes:
        """Serialize DocumentIR into a validated EPUB 3.3 ZIP container byte payload."""
        pkg = self.build_package(doc_ir)
        return pkg.to_bytes()


__all__ = ["EpubEmitter"]
