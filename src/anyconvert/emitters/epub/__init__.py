"""EPUB 3 e-book emitter package."""

from __future__ import annotations

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
