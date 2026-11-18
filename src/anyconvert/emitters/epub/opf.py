"""EPUB 3.3 Package Document (content.opf) generator.

Generates OPF 3.0 XML documents adhering to the W3C EPUB 3.3 specification:
- Dublin Core metadata (<dc:title>, <dc:creator>, <dc:language>, <dc:identifier>, etc.)
  and mandatory <meta property="dcterms:modified"> UTC timestamp.
- <manifest> enumerating XHTML content documents, navigation document, styles,
  images, fonts, and optional NCX fallback.
- <spine> defining linear reading order and optional NCX toc reference.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import datetime
import posixpath
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple
import uuid

from anyconvert.exceptions import PackagingError, SerializationError
from anyconvert.emitters.base import xml_escape
from anyconvert.packaging.epub import (
    MEDIA_TYPE_CSS,
    MEDIA_TYPE_NCX,
    MEDIA_TYPE_XHTML,
    OEBPS_DIR,
    infer_epub_media_type,
)
from anyconvert.pdf.document import parse_pdf_date

OPF_NS = "http://www.idpf.org/2007/opf"
DC_NS = "http://purl.org/dc/elements/1.1/"
DCTERMS_NS = "http://purl.org/dc/terms/"
OPF_VERSION = "3.0"
DEFAULT_UNIQUE_ID = "pub-id"

_NCNAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9._-]*$")
_UTC_MODIFIED_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def normalize_opf_href(href: str, base_dir: str = OEBPS_DIR) -> str:
    """Normalize an OPF manifest href to a clean POSIX path relative to base_dir."""
    raw_posix = href.replace("\\", "/")
    if not raw_posix.strip() or raw_posix.endswith("/"):
        raise PackagingError(f"Invalid OPF href path: {href!r}")
    cleaned = posixpath.normpath(raw_posix).lstrip("/")
    base_clean = base_dir.strip("/")
    if not cleaned or cleaned in (".", "..", base_clean) or cleaned.startswith("../"):
        raise PackagingError(f"Invalid OPF href path: {href!r}")
    prefix = f"{base_clean}/" if base_clean else ""
    if prefix and cleaned.startswith(prefix):
        cleaned = cleaned[len(prefix) :]
    if not cleaned or cleaned == ".":
        raise PackagingError(f"Invalid OPF href path: {href!r}")
    return cleaned


def sanitize_manifest_id(raw_id: str) -> str:
    """Convert an arbitrary string into a valid XML NCName identifier."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_id.strip())
    if not cleaned:
        return "item"
    if not (cleaned[0].isalpha() or cleaned[0] == "_"):
        cleaned = f"item_{cleaned}"
    return cleaned


def _format_utc_modified(raw_date: Optional[str] = None) -> str:
    """Format a timestamp string into strict EPUB 3 dcterms:modified CCYY-MM-DDThh:mm:ssZ."""
    if raw_date:
        parsed = parse_pdf_date(raw_date.strip())
        if _UTC_MODIFIED_RE.match(parsed):
            return parsed
        iso_candidate = parsed[:-1] + "+00:00" if parsed.endswith("Z") else parsed
        try:
            dt = datetime.datetime.fromisoformat(iso_candidate)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            else:
                dt = dt.astimezone(datetime.timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            pass
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_language(raw_lang: Optional[str]) -> str:
    """Normalize a language tag to valid BCP 47 syntax (default 'en')."""
    if not raw_lang or not isinstance(raw_lang, str):
        return "en"
    cleaned = raw_lang.strip().replace("_", "-")
    return cleaned or "en"


def _split_keywords(raw_keywords: str) -> List[str]:
    """Split comma/semicolon-separated keywords into clean unique subject tokens."""
    seen: Set[str] = set()
    out: List[str] = []
    for part in re.split(r"[,;]+", raw_keywords):
        tok = part.strip()
        if tok and tok.lower() not in seen:
            seen.add(tok.lower())
            out.append(tok)
    return out


@dataclass(slots=True)
class OPFMetadata:
    """Dublin Core and EPUB 3.3 package metadata container."""

    title: str = "Untitled Document"
    language: str = "en"
    identifier: str = ""
    creators: List[str] = field(default_factory=list)
    description: str = ""
    subjects: List[str] = field(default_factory=list)
    date: str = ""
    modified: str = ""
    publisher: str = ""
    rights: str = ""

    def __post_init__(self) -> None:
        self.title = self.title.strip() or "Untitled Document"
        self.language = _normalize_language(self.language)
        if not self.identifier or not self.identifier.strip():
            self.identifier = f"urn:uuid:{uuid.uuid4()}"
        else:
            self.identifier = self.identifier.strip()
        if not self.modified or not _UTC_MODIFIED_RE.match(self.modified):
            self.modified = _format_utc_modified(self.modified or None)

    @classmethod
    def from_ir_metadata(
        cls,
        metadata: Optional[Mapping[str, Any]],
        default_title: str = "Untitled Document",
        default_language: str = "en",
    ) -> OPFMetadata:
        """Build OPFMetadata from DocumentIR.metadata dictionary."""
        if not metadata:
            return cls(title=default_title, language=default_language)

        lowered: Dict[str, str] = {}
        for k, v in metadata.items():
            if v is None:
                continue
            key_l = str(k).lstrip("/").strip().lower()
            val_s = str(v).strip("\x00").strip()
            if key_l and val_s:
                lowered[key_l] = val_s

        title = lowered.get("title") or default_title
        language = _normalize_language(lowered.get("language") or default_language)

        identifier = (
            lowered.get("identifier")
            or lowered.get("uuid")
            or lowered.get("isbn")
            or ""
        )
        if identifier and not (
            identifier.startswith("urn:") or ":" in identifier
        ):
            identifier = f"urn:anyconvert:{identifier}"

        creators: List[str] = []
        raw_author = lowered.get("author") or lowered.get("creator") or ""
        if raw_author:
            creators = [c.strip() for c in re.split(r"[;]+", raw_author) if c.strip()]

        description = lowered.get("subject") or lowered.get("description") or ""
        subjects = _split_keywords(lowered.get("keywords", ""))
        date_raw = lowered.get("creationdate") or lowered.get("date") or ""
        date_iso = parse_pdf_date(date_raw) if date_raw else ""
        modified_iso = _format_utc_modified(lowered.get("moddate") or lowered.get("modified"))
        publisher = lowered.get("producer") or lowered.get("publisher") or ""
        rights = lowered.get("rights") or ""

        return cls(
            title=title,
            language=language,
            identifier=identifier,
            creators=creators,
            description=description,
            subjects=subjects,
            date=date_iso,
            modified=modified_iso,
            publisher=publisher,
            rights=rights,
        )


@dataclass(frozen=True, slots=True)
class OPFManifestItem:
    """Single resource entry within the OPF <manifest>."""

    id: str
    href: str
    media_type: str
    properties: Optional[str] = None
    fallback: Optional[str] = None


@dataclass(frozen=True, slots=True)
class OPFSpineItem:
    """Single reading-order reference within the OPF <spine>."""

    idref: str
    linear: bool = True
    properties: Optional[str] = None


class PackageDocument:
    """EPUB 3.3 content.opf Package Document builder and validator."""

    __slots__ = (
        "metadata",
        "unique_identifier_id",
        "manifest_items",
        "spine_items",
        "toc_id",
        "_ids",
        "_hrefs",
    )

    def __init__(
        self,
        metadata: Optional[OPFMetadata] = None,
        unique_identifier_id: str = DEFAULT_UNIQUE_ID,
    ) -> None:
        if not _NCNAME_RE.match(unique_identifier_id):
            raise SerializationError(
                f"Invalid unique-identifier NCName: {unique_identifier_id!r}"
            )
        self.metadata: OPFMetadata = metadata if metadata is not None else OPFMetadata()
        self.unique_identifier_id: str = unique_identifier_id
        self.manifest_items: List[OPFManifestItem] = []
        self.spine_items: List[OPFSpineItem] = []
        self.toc_id: Optional[str] = None
        self._ids: Set[str] = set()
        self._hrefs: Set[str] = set()

    def _allocate_unique_id(self, base: str) -> str:
        """Allocate a unique valid NCName identifier starting from base."""
        clean_base = sanitize_manifest_id(base)
        candidate = clean_base
        suffix = 1
        while candidate in self._ids:
            suffix += 1
            candidate = f"{clean_base}_{suffix}"
        return candidate

    def add_manifest_item(
        self,
        item_id: str,
        href: str,
        media_type: Optional[str] = None,
        properties: Optional[str] = None,
        fallback: Optional[str] = None,
    ) -> OPFManifestItem:
        """Add an item to the OPF <manifest>, enforcing unique ID and href."""
        if not _NCNAME_RE.match(item_id):
            raise SerializationError(f"Invalid OPF manifest id NCName: {item_id!r}")
        if item_id in self._ids:
            raise SerializationError(f"Duplicate OPF manifest id: {item_id!r}")

        norm_href = normalize_opf_href(href)
        if norm_href in self._hrefs:
            raise SerializationError(f"Duplicate OPF manifest href: {norm_href!r}")

        resolved_type = media_type or infer_epub_media_type(norm_href)
        if not resolved_type:
            raise SerializationError(f"Missing media-type for OPF manifest item: {norm_href!r}")

        item = OPFManifestItem(
            id=item_id,
            href=norm_href,
            media_type=resolved_type,
            properties=properties.strip() if properties and properties.strip() else None,
            fallback=fallback.strip() if fallback and fallback.strip() else None,
        )
        self.manifest_items.append(item)
        self._ids.add(item_id)
        self._hrefs.add(norm_href)

        if resolved_type == MEDIA_TYPE_NCX and self.toc_id is None:
            self.toc_id = item_id

        return item

    def add_xhtml(
        self,
        item_id: str,
        href: str,
        in_spine: bool = True,
        linear: bool = True,
        properties: Optional[str] = None,
        spine_properties: Optional[str] = None,
    ) -> OPFManifestItem:
        """Add an XHTML content document to manifest and optionally append to spine."""
        item = self.add_manifest_item(
            item_id=item_id,
            href=href,
            media_type=MEDIA_TYPE_XHTML,
            properties=properties,
        )
        if in_spine:
            self.add_spine_item(item.id, linear=linear, properties=spine_properties)
        return item

    def add_navigation(
        self,
        href: str = "nav.xhtml",
        item_id: str = "nav",
        in_spine: bool = False,
        linear: bool = False,
    ) -> OPFManifestItem:
        """Add the EPUB 3 Navigation Document with required properties='nav'."""
        return self.add_xhtml(
            item_id=item_id,
            href=href,
            in_spine=in_spine,
            linear=linear,
            properties="nav",
        )

    def add_ncx(
        self,
        href: str = "toc.ncx",
        item_id: str = "ncx",
    ) -> OPFManifestItem:
        """Add an EPUB 2 NCX table of contents fallback document and bind <spine toc=...>."""
        item = self.add_manifest_item(
            item_id=item_id,
            href=href,
            media_type=MEDIA_TYPE_NCX,
        )
        self.toc_id = item.id
        return item

    def add_stylesheet(
        self,
        href: str = "Styles/style.css",
        item_id: Optional[str] = None,
    ) -> OPFManifestItem:
        """Add a CSS stylesheet to the manifest."""
        resolved_id = item_id or self._allocate_unique_id("css")
        return self.add_manifest_item(
            item_id=resolved_id,
            href=href,
            media_type=MEDIA_TYPE_CSS,
        )

    def add_image(
        self,
        href: str,
        item_id: Optional[str] = None,
        media_type: Optional[str] = None,
        is_cover: bool = False,
    ) -> OPFManifestItem:
        """Add an image asset to the manifest, optionally marked as cover-image."""
        resolved_id = item_id or self._allocate_unique_id("img")
        props = "cover-image" if is_cover else None
        return self.add_manifest_item(
            item_id=resolved_id,
            href=href,
            media_type=media_type or infer_epub_media_type(href),
            properties=props,
        )

    def add_spine_item(
        self,
        idref: str,
        linear: bool = True,
        properties: Optional[str] = None,
    ) -> OPFSpineItem:
        """Append a manifest item reference to the reading order <spine>."""
        if idref not in self._ids:
            raise SerializationError(
                f"Cannot add spine itemref {idref!r}: id does not exist in manifest"
            )
        ref = OPFSpineItem(
            idref=idref,
            linear=linear,
            properties=properties.strip() if properties and properties.strip() else None,
        )
        self.spine_items.append(ref)
        return ref

    def validate(self, require_nav: bool = False) -> None:
        """Validate OPF 3.0 structural and referential integrity invariants."""
        if not self.metadata.title:
            raise SerializationError("OPF package metadata missing required <dc:title>")
        if not self.metadata.language:
            raise SerializationError("OPF package metadata missing required <dc:language>")
        if not self.metadata.identifier:
            raise SerializationError("OPF package metadata missing required <dc:identifier>")
        if not self.manifest_items:
            raise SerializationError("OPF <manifest> must contain at least one item")
        if not self.spine_items:
            raise SerializationError("OPF <spine> must contain at least one <itemref>")

        for sp in self.spine_items:
            if sp.idref not in self._ids:
                raise SerializationError(
                    f"OPF <spine> itemref {sp.idref!r} not found in <manifest>"
                )

        if self.toc_id is not None and self.toc_id not in self._ids:
            raise SerializationError(
                f"OPF <spine toc={self.toc_id!r}> does not match any <manifest> item"
            )

        nav_items = [
            it
            for it in self.manifest_items
            if it.properties and "nav" in it.properties.split()
        ]
        if require_nav and len(nav_items) != 1:
            raise SerializationError(
                f"EPUB 3 OPF requires exactly 1 manifest item with properties='nav', found {len(nav_items)}"
            )

    def _build_metadata_lines(self) -> List[str]:
        """Serialize Dublin Core metadata and dcterms:modified XML elements."""
        meta = self.metadata
        lines: List[str] = [
            f'  <metadata xmlns:dc="{DC_NS}" xmlns:dcterms="{DCTERMS_NS}">',
            f'    <dc:identifier id="{xml_escape(self.unique_identifier_id)}">{xml_escape(meta.identifier)}</dc:identifier>',
            f"    <dc:title>{xml_escape(meta.title)}</dc:title>",
            f"    <dc:language>{xml_escape(meta.language)}</dc:language>",
        ]

        for creator in meta.creators:
            lines.append(f"    <dc:creator>{xml_escape(creator)}</dc:creator>")

        if meta.description:
            lines.append(f"    <dc:description>{xml_escape(meta.description)}</dc:description>")

        for subj in meta.subjects:
            lines.append(f"    <dc:subject>{xml_escape(subj)}</dc:subject>")

        if meta.date:
            lines.append(f"    <dc:date>{xml_escape(meta.date)}</dc:date>")

        if meta.publisher:
            lines.append(f"    <dc:publisher>{xml_escape(meta.publisher)}</dc:publisher>")

        if meta.rights:
            lines.append(f"    <dc:rights>{xml_escape(meta.rights)}</dc:rights>")

        lines.append(
            f'    <meta property="dcterms:modified">{xml_escape(meta.modified)}</meta>'
        )
        lines.append("  </metadata>")
        return lines

    def _build_manifest_lines(self) -> List[str]:
        """Serialize <manifest> and its <item> elements."""
        lines: List[str] = ["  <manifest>"]
        for item in self.manifest_items:
            attrs = [
                f'id="{xml_escape(item.id)}"',
                f'href="{xml_escape(item.href)}"',
                f'media-type="{xml_escape(item.media_type)}"',
            ]
            if item.properties:
                attrs.append(f'properties="{xml_escape(item.properties)}"')
            if item.fallback:
                attrs.append(f'fallback="{xml_escape(item.fallback)}"')
            lines.append(f"    <item {' '.join(attrs)}/>")
        lines.append("  </manifest>")
        return lines

    def _build_spine_lines(self) -> List[str]:
        """Serialize <spine> and its <itemref> elements."""
        toc_attr = f' toc="{xml_escape(self.toc_id)}"' if self.toc_id else ""
        lines: List[str] = [f"  <spine{toc_attr}>"]
        for sp in self.spine_items:
            linear_str = "yes" if sp.linear else "no"
            attrs = [
                f'idref="{xml_escape(sp.idref)}"',
                f'linear="{linear_str}"',
            ]
            if sp.properties:
                attrs.append(f'properties="{xml_escape(sp.properties)}"')
            lines.append(f"    <itemref {' '.join(attrs)}/>")
        lines.append("  </spine>")
        return lines

    def to_xml(self, require_nav: bool = False) -> str:
        """Render the complete content.opf XML document string."""
        self.validate(require_nav=require_nav)
        lines: List[str] = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            (
                f'<package xmlns="{OPF_NS}" version="{OPF_VERSION}" '
                f'unique-identifier="{xml_escape(self.unique_identifier_id)}" '
                f'xml:lang="{xml_escape(self.metadata.language)}">'
            ),
        ]
        lines.extend(self._build_metadata_lines())
        lines.extend(self._build_manifest_lines())
        lines.extend(self._build_spine_lines())
        lines.append("</package>")
        return "\n".join(lines)

    def to_bytes(self, require_nav: bool = False) -> bytes:
        """Serialize content.opf into UTF-8 encoded XML bytes."""
        return self.to_xml(require_nav=require_nav).encode("utf-8")


def build_content_opf(
    metadata: Optional[Mapping[str, Any]] = None,
    chapters: Iterable[Tuple[str, str]] = (),
    assets: Iterable[Tuple[str, str, str]] = (),
    nav_href: Optional[str] = "nav.xhtml",
    ncx_href: Optional[str] = "toc.ncx",
    stylesheet_href: Optional[str] = "Styles/style.css",
    language: str = "en",
) -> bytes:
    """Convenience helper to construct a complete content.opf XML payload.

    Args:
        metadata: Raw metadata dictionary (e.g., DocumentIR.metadata).
        chapters: Sequence of (id, href) pairs for linear XHTML spine chapters.
        assets: Sequence of (id, href, media_type) tuples for images/fonts.
        nav_href: Relative href for EPUB 3 navigation document (or None to omit).
        ncx_href: Relative href for legacy NCX TOC (or None to omit).
        stylesheet_href: Relative href for CSS stylesheet (or None to omit).
        language: Default BCP 47 language code.

    Returns:
        UTF-8 encoded bytes of the generated content.opf XML.
    """
    opf_meta = OPFMetadata.from_ir_metadata(metadata, default_language=language)
    doc = PackageDocument(metadata=opf_meta)

    if nav_href:
        doc.add_navigation(href=nav_href)
    if ncx_href:
        doc.add_ncx(href=ncx_href)
    if stylesheet_href:
        doc.add_stylesheet(href=stylesheet_href)

    for ch_id, ch_href in chapters:
        doc.add_xhtml(item_id=ch_id, href=ch_href, in_spine=True, linear=True)

    for asset_id, asset_href, asset_type in assets:
        doc.add_manifest_item(
            item_id=asset_id,
            href=asset_href,
            media_type=asset_type,
        )

    return doc.to_bytes(require_nav=bool(nav_href))


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
