"""EPUB 3 e-book emitter package."""

from __future__ import annotations

from anyconvert.emitters.epub.nav import (
    EPUB_OPS_NS,
    NCX_NS,
    NCX_VERSION,
    XHTML_NS,
    NavigationBuilder,
    TocEntry,
    build_toc_tree,
    compute_toc_depth,
    extract_toc_entries_from_ir,
    generate_nav_xhtml,
    generate_toc_ncx,
)
from anyconvert.emitters.epub.opf import (
    DC_NS,
    DCTERMS_NS,
    DEFAULT_UNIQUE_ID,
    OPF_NS,
    OPF_VERSION,
    OPFManifestItem,
    OPFMetadata,
    OPFSpineItem,
    PackageDocument,
    build_content_opf,
    normalize_opf_href,
    sanitize_manifest_id,
)

__all__ = [
    "XHTML_NS",
    "EPUB_OPS_NS",
    "NCX_NS",
    "NCX_VERSION",
    "TocEntry",
    "NavigationBuilder",
    "build_toc_tree",
    "compute_toc_depth",
    "extract_toc_entries_from_ir",
    "generate_nav_xhtml",
    "generate_toc_ncx",
    "OPF_NS",
    "DC_NS",
    "DCTERMS_NS",
    "OPF_VERSION",
    "DEFAULT_UNIQUE_ID",
    "OPFMetadata",
    "OPFManifestItem",
    "OPFSpineItem",
    "PackageDocument",
    "build_content_opf",
    "normalize_opf_href",
    "sanitize_manifest_id",
]
