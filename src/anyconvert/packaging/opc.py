"""Pure-Python Open Packaging Conventions (OPC) container packager.

Implements ISO/IEC 29500-2 / ECMA-376 Part 2 Open Packaging Conventions (OPC)
archive generation and parsing for Microsoft Word (DOCX) and PowerPoint (PPTX)
document serialization with zero external dependencies.
"""

from __future__ import annotations

import io
from os import PathLike
import posixpath
import re
from typing import BinaryIO, Dict, Iterable, List, Optional, Set, Tuple, Union
import xml.etree.ElementTree as ET
import zipfile

from anyconvert.exceptions import PackagingError


# ==============================================================================
# OPC Namespaces and Constant Definitions
# ==============================================================================

CONTENT_TYPES_PART_NAME = "[Content_Types].xml"
PACKAGE_RELATIONSHIPS_PART_NAME = "_rels/.rels"

CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
RELATIONSHIPS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

# Common Content Types
CT_RELATIONSHIPS = "application/vnd.openxmlformats-package.relationships+xml"
CT_XML = "application/xml"
CT_PNG = "image/png"
CT_JPEG = "image/jpeg"
CT_GIF = "image/gif"
CT_TIFF = "image/tiff"
CT_SVG = "image/svg+xml"

CT_WORDPROCESSING_DOCUMENT = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
)
CT_WORDPROCESSING_STYLES = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"
)
CT_WORDPROCESSING_NUMBERING = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"
)
CT_WORDPROCESSING_SETTINGS = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"
)
CT_WORDPROCESSING_HEADER = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"
)
CT_WORDPROCESSING_FOOTER = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"
)
CT_WORDPROCESSING_FONTTABLE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.fontTable+xml"
)

CT_PRESENTATION_DOCUMENT = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"
)
CT_PRESENTATION_SLIDE = (
    "application/vnd.openxmlformats-officedocument.presentationml.slide+xml"
)
CT_PRESENTATION_SLIDELAYOUT = (
    "application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"
)
CT_PRESENTATION_SLIDEMASTER = (
    "application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"
)

CT_DRAWINGML_THEME = "application/vnd.openxmlformats-officedocument.theme+xml"
CT_CORE_PROPERTIES = (
    "application/vnd.openxmlformats-package.core-properties+xml"
)
CT_EXTENDED_PROPERTIES = (
    "application/vnd.openxmlformats-officedocument.extended-properties+xml"
)

# Common Relationship Types
RT_OFFICE_DOCUMENT = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
)
RT_STYLES = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles"
)
RT_NUMBERING = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering"
)
RT_SETTINGS = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings"
)
RT_FONTTABLE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/fontTable"
)
RT_HEADER = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/header"
)
RT_FOOTER = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer"
)
RT_IMAGE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
)
RT_HYPERLINK = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
)
RT_SLIDE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
)
RT_SLIDELAYOUT = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout"
)
RT_SLIDEMASTER = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster"
)
RT_THEME = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme"
)
RT_CORE_PROPERTIES = (
    "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties"
)
RT_EXTENDED_PROPERTIES = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties"
)


# ==============================================================================
# Helper Functions
# ==============================================================================

def normalize_part_name(part_name: str) -> str:
    """Normalize a part name to a clean relative POSIX path without leading slashes."""
    cleaned = posixpath.normpath(part_name.replace("\\", "/")).lstrip("/")
    if not cleaned or cleaned == ".":
        raise PackagingError(f"Invalid part name: {part_name!r}")
    return cleaned


def get_relationships_path(part_name: str) -> str:
    """Compute the relationship part path corresponding to a given part.

    Example:
        'word/document.xml' -> 'word/_rels/document.xml.rels'
        'document.xml'      -> '_rels/document.xml.rels'
    """
    normalized = normalize_part_name(part_name)
    dirname, filename = posixpath.split(normalized)
    if dirname:
        return f"{dirname}/_rels/{filename}.rels"
    return f"_rels/{filename}.rels"


def _xml_escape_attr(value: str) -> str:
    """Escape an attribute value for XML serialization."""
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _next_rel_id(existing_ids: Set[str]) -> str:
    """Generate the next unique relationship ID in the sequence rId1, rId2, ..."""
    num = 1
    # Check max existing numeric suffix
    for rid in existing_ids:
        match = re.match(r"^rId(\d+)$", rid)
        if match:
            num = max(num, int(match.group(1)) + 1)
    cand = f"rId{num}"
    while cand in existing_ids:
        num += 1
        cand = f"rId{num}"
    return cand


# ==============================================================================
# OPC Models
# ==============================================================================

class OPCRelationship:
    """A directed relationship in an Open Packaging Conventions (OPC) container."""

    __slots__ = ("rel_id", "rel_type", "target", "target_mode")

    def __init__(
        self,
        rel_id: str,
        rel_type: str,
        target: str,
        target_mode: str = "Internal",
    ) -> None:
        if target_mode not in ("Internal", "External"):
            raise PackagingError(
                f"Invalid relationship target_mode: {target_mode!r}. Must be 'Internal' or 'External'."
            )
        self.rel_id: str = rel_id
        self.rel_type: str = rel_type
        self.target: str = target
        self.target_mode: str = target_mode

    def __repr__(self) -> str:
        return (
            f"OPCRelationship(rel_id={self.rel_id!r}, rel_type={self.rel_type!r}, "
            f"target={self.target!r}, target_mode={self.target_mode!r})"
        )


class OPCPart:
    """A distinct byte content part within an OPC package."""

    __slots__ = ("part_name", "content", "content_type", "relationships")

    def __init__(
        self,
        part_name: str,
        content: Union[str, bytes],
        content_type: Optional[str] = None,
    ) -> None:
        self.part_name: str = normalize_part_name(part_name)
        if isinstance(content, str):
            self.content: bytes = content.encode("utf-8")
        elif isinstance(content, (bytes, bytearray, memoryview)):
            self.content = bytes(content)
        else:
            raise PackagingError(
                f"Part content must be str or bytes, got {type(content).__name__}"
            )
        self.content_type: Optional[str] = content_type
        self.relationships: Dict[str, OPCRelationship] = {}

    def add_relationship(
        self,
        rel_type: str,
        target: str,
        target_mode: str = "Internal",
        rel_id: Optional[str] = None,
    ) -> OPCRelationship:
        """Add a relationship targeting another part or external URI.

        Args:
            rel_type: Standard relationship type URI.
            target: Relative target part path or external URL.
            target_mode: 'Internal' or 'External'.
            rel_id: Optional explicit relationship ID ('rIdN'). If None, automatically generated.

        Returns:
            The created OPCRelationship instance.
        """
        if rel_id is None:
            rel_id = _next_rel_id(set(self.relationships.keys()))
        elif rel_id in self.relationships:
            raise PackagingError(
                f"Duplicate relationship ID {rel_id!r} in part {self.part_name!r}"
            )

        rel = OPCRelationship(
            rel_id=rel_id,
            rel_type=rel_type,
            target=target,
            target_mode=target_mode,
        )
        self.relationships[rel_id] = rel
        return rel

    def get_relationship(self, rel_id: str) -> OPCRelationship:
        """Retrieve relationship by ID."""
        if rel_id not in self.relationships:
            raise PackagingError(
                f"Relationship {rel_id!r} not found in part {self.part_name!r}"
            )
        return self.relationships[rel_id]

    def find_relationships_by_type(self, rel_type: str) -> List[OPCRelationship]:
        """Find all relationships matching the specified relationship type URI."""
        return [r for r in self.relationships.values() if r.rel_type == rel_type]

    def __repr__(self) -> str:
        return (
            f"OPCPart(part_name={self.part_name!r}, size={len(self.content)}, "
            f"content_type={self.content_type!r}, relationships={len(self.relationships)})"
        )


# ==============================================================================
# OPC Package Engine
# ==============================================================================

class OPCPackage:
    """In-memory Open Packaging Conventions (OPC) container packager and parser."""

    __slots__ = ("parts", "package_relationships", "default_content_types")

    def __init__(self) -> None:
        self.parts: Dict[str, OPCPart] = {}
        self.package_relationships: Dict[str, OPCRelationship] = {}
        self.default_content_types: Dict[str, str] = {
            "rels": CT_RELATIONSHIPS,
            "xml": CT_XML,
            "png": CT_PNG,
            "jpeg": CT_JPEG,
            "jpg": CT_JPEG,
            "gif": CT_GIF,
            "tif": CT_TIFF,
            "tiff": CT_TIFF,
            "svg": CT_SVG,
        }

    def add_default_content_type(self, extension: str, content_type: str) -> None:
        """Register or override a default content type mapping for a file extension."""
        ext = extension.lstrip(".").lower()
        if not ext:
            raise PackagingError(f"Invalid extension: {extension!r}")
        self.default_content_types[ext] = content_type

    def add_part(
        self,
        part_name: str,
        content: Union[str, bytes],
        content_type: Optional[str] = None,
    ) -> OPCPart:
        """Add a new part to the package.

        Args:
            part_name: Path of the part (e.g., 'word/document.xml').
            content: Text or raw bytes content.
            content_type: Optional MIME content type. If omitted, will be inferred from extension.

        Returns:
            The created OPCPart instance.
        """
        norm_name = normalize_part_name(part_name)
        if norm_name in self.parts:
            raise PackagingError(f"Part {norm_name!r} already exists in package")

        part = OPCPart(norm_name, content, content_type=content_type)
        self.parts[norm_name] = part
        return part

    def get_part(self, part_name: str) -> OPCPart:
        """Retrieve a part by name."""
        norm_name = normalize_part_name(part_name)
        if norm_name not in self.parts:
            raise PackagingError(f"Part {norm_name!r} not found in package")
        return self.parts[norm_name]

    def has_part(self, part_name: str) -> bool:
        """Check if a part exists in the package."""
        try:
            norm_name = normalize_part_name(part_name)
            return norm_name in self.parts
        except PackagingError:
            return False

    def remove_part(self, part_name: str) -> None:
        """Remove a part from the package."""
        norm_name = normalize_part_name(part_name)
        if norm_name in self.parts:
            del self.parts[norm_name]

    def add_package_relationship(
        self,
        rel_type: str,
        target: str,
        target_mode: str = "Internal",
        rel_id: Optional[str] = None,
    ) -> OPCRelationship:
        """Add a root package-level relationship (_rels/.rels)."""
        if rel_id is None:
            rel_id = _next_rel_id(set(self.package_relationships.keys()))
        elif rel_id in self.package_relationships:
            raise PackagingError(
                f"Duplicate root package relationship ID {rel_id!r}"
            )

        rel = OPCRelationship(
            rel_id=rel_id,
            rel_type=rel_type,
            target=target,
            target_mode=target_mode,
        )
        self.package_relationships[rel_id] = rel
        return rel

    def add_part_relationship(
        self,
        part_name: str,
        rel_type: str,
        target: str,
        target_mode: str = "Internal",
        rel_id: Optional[str] = None,
    ) -> OPCRelationship:
        """Add a relationship to a specific part."""
        part = self.get_part(part_name)
        return part.add_relationship(
            rel_type=rel_type,
            target=target,
            target_mode=target_mode,
            rel_id=rel_id,
        )

    def build_content_types_xml(self) -> bytes:
        """Generate compliant [Content_Types].xml content."""
        lines = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            f'<Types xmlns="{CONTENT_TYPES_NS}">',
        ]

        # 1. Defaults sorted by extension
        for ext in sorted(self.default_content_types.keys()):
            ct = self.default_content_types[ext]
            lines.append(
                f'  <Default Extension="{_xml_escape_attr(ext)}" ContentType="{_xml_escape_attr(ct)}"/>'
            )

        # 2. Overrides for parts that have an explicit content_type
        # or whose extension doesn't match default content types
        sorted_parts = sorted(self.parts.values(), key=lambda p: p.part_name)
        for part in sorted_parts:
            part_ct = part.content_type
            ext = posixpath.splitext(part.part_name)[1].lstrip(".").lower()

            if part_ct is not None:
                # If content_type is explicitly specified and differs from default for this ext, or user specified it
                if ext not in self.default_content_types or self.default_content_types[ext] != part_ct:
                    lines.append(
                        f'  <Override PartName="/{_xml_escape_attr(part.part_name)}" ContentType="{_xml_escape_attr(part_ct)}"/>'
                    )
            else:
                if ext not in self.default_content_types:
                    raise PackagingError(
                        f"Part {part.part_name!r} has no content_type and extension {ext!r} is not in default content types"
                    )

        lines.append("</Types>")
        return "\n".join(lines).encode("utf-8")

    @staticmethod
    def build_relationships_xml(rels: Iterable[OPCRelationship]) -> bytes:
        """Generate compliant .rels XML content."""
        lines = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            f'<Relationships xmlns="{RELATIONSHIPS_NS}">',
        ]

        sorted_rels = sorted(
            rels,
            key=lambda r: int(re.sub(r"\D", "", r.rel_id)) if re.sub(r"\D", "", r.rel_id) else r.rel_id,
        )
        for r in sorted_rels:
            tm_attr = ' TargetMode="External"' if r.target_mode == "External" else ""
            lines.append(
                f'  <Relationship Id="{_xml_escape_attr(r.rel_id)}" '
                f'Type="{_xml_escape_attr(r.rel_type)}" '
                f'Target="{_xml_escape_attr(r.target)}"{tm_attr}/>'
            )

        lines.append("</Relationships>")
        return "\n".join(lines).encode("utf-8")

    def to_bytes(self, compression: int = zipfile.ZIP_DEFLATED) -> bytes:
        """Serialize the complete OPC package into an in-memory ZIP archive bytes buffer."""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, mode="w", compression=compression) as zf:
            # 1. Write [Content_Types].xml
            ct_bytes = self.build_content_types_xml()
            zf.writestr(CONTENT_TYPES_PART_NAME, ct_bytes)

            # 2. Write root package relationships (_rels/.rels)
            if self.package_relationships:
                pkg_rels_bytes = self.build_relationships_xml(
                    self.package_relationships.values()
                )
                zf.writestr(PACKAGE_RELATIONSHIPS_PART_NAME, pkg_rels_bytes)

            # 3. Write each part and its relationship tree
            for part in self.parts.values():
                zf.writestr(part.part_name, part.content)
                if part.relationships:
                    rel_path = get_relationships_path(part.part_name)
                    rel_bytes = self.build_relationships_xml(
                        part.relationships.values()
                    )
                    zf.writestr(rel_path, rel_bytes)

        return buffer.getvalue()

    def save(
        self,
        dest: Union[str, PathLike[str], BinaryIO],
        compression: int = zipfile.ZIP_DEFLATED,
    ) -> None:
        """Write the package ZIP archive to a file path or binary stream."""
        pkg_bytes = self.to_bytes(compression=compression)
        if isinstance(dest, (str, PathLike)):
            with open(dest, "wb") as f:
                f.write(pkg_bytes)
        else:
            dest.write(pkg_bytes)

    @classmethod
    def parse(cls, source: Union[bytes, BinaryIO, str, PathLike[str]]) -> OPCPackage:
        """Parse an existing OPC ZIP package archive.

        Args:
            source: Raw bytes, binary file-like object, or file path.

        Returns:
            Populated OPCPackage instance.

        Raises:
            PackagingError: If the package is invalid or missing required OPC components.
        """
        raw_io: BinaryIO
        if isinstance(source, bytes):
            raw_io = io.BytesIO(source)
        elif isinstance(source, (str, PathLike)):
            with open(source, "rb") as f:
                raw_io = io.BytesIO(f.read())
        else:
            raw_io = source

        try:
            zf = zipfile.ZipFile(raw_io, "r")
        except Exception as e:
            raise PackagingError(f"Failed to open source as ZIP archive: {e}") from e

        with zf:
            namelist = set(zf.namelist())
            if CONTENT_TYPES_PART_NAME not in namelist:
                raise PackagingError(
                    f"OPC package missing required {CONTENT_TYPES_PART_NAME}"
                )

            pkg = cls()

            # Parse [Content_Types].xml
            ct_xml = zf.read(CONTENT_TYPES_PART_NAME)
            defaults, overrides = cls._parse_content_types(ct_xml)
            pkg.default_content_types.update(defaults)

            # Parse root package relationships (_rels/.rels)
            if PACKAGE_RELATIONSHIPS_PART_NAME in namelist:
                pkg_rels_xml = zf.read(PACKAGE_RELATIONSHIPS_PART_NAME)
                for rel in cls._parse_relationships(pkg_rels_xml):
                    pkg.package_relationships[rel.rel_id] = rel

            # Identify all part relationship files (*.rels)
            rel_files = {name for name in namelist if name.endswith(".rels")}

            # Identify content parts
            for name in namelist:
                if name == CONTENT_TYPES_PART_NAME or name in rel_files:
                    continue

                content = zf.read(name)
                norm_name = normalize_part_name(name)

                # Determine content type: override first, then default
                lookup_override = f"/{norm_name}"
                ct = overrides.get(lookup_override)
                if ct is None:
                    ext = posixpath.splitext(norm_name)[1].lstrip(".").lower()
                    ct = pkg.default_content_types.get(ext)

                part = pkg.add_part(norm_name, content, content_type=ct)

                # Check if this part has an associated .rels file
                part_rels_path = get_relationships_path(norm_name)
                if part_rels_path in namelist:
                    part_rels_xml = zf.read(part_rels_path)
                    for rel in cls._parse_relationships(part_rels_xml):
                        part.relationships[rel.rel_id] = rel

            return pkg

    @staticmethod
    def _parse_content_types(xml_data: bytes) -> Tuple[Dict[str, str], Dict[str, str]]:
        """Parse Defaults and Overrides from [Content_Types].xml."""
        defaults: Dict[str, str] = {}
        overrides: Dict[str, str] = {}
        try:
            root = ET.fromstring(xml_data)
        except Exception as e:
            raise PackagingError(f"Malformed [Content_Types].xml: {e}") from e

        for elem in root:
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if tag == "Default":
                ext = elem.get("Extension", "").lstrip(".").lower()
                ct = elem.get("ContentType", "")
                if ext and ct:
                    defaults[ext] = ct
            elif tag == "Override":
                pname = elem.get("PartName", "")
                ct = elem.get("ContentType", "")
                if pname and ct:
                    overrides[pname] = ct

        return defaults, overrides

    @staticmethod
    def _parse_relationships(xml_data: bytes) -> List[OPCRelationship]:
        """Parse Relationship elements from a .rels XML payload."""
        relationships: List[OPCRelationship] = []
        try:
            root = ET.fromstring(xml_data)
        except Exception as e:
            raise PackagingError(f"Malformed .rels XML: {e}") from e

        for elem in root:
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if tag == "Relationship":
                rel_id = elem.get("Id", "")
                rel_type = elem.get("Type", "")
                target = elem.get("Target", "")
                target_mode = elem.get("TargetMode", "Internal")
                if rel_id and rel_type and target:
                    relationships.append(
                        OPCRelationship(
                            rel_id=rel_id,
                            rel_type=rel_type,
                            target=target,
                            target_mode=target_mode,
                        )
                    )

        return relationships


__all__ = [
    "CONTENT_TYPES_PART_NAME",
    "PACKAGE_RELATIONSHIPS_PART_NAME",
    "CONTENT_TYPES_NS",
    "RELATIONSHIPS_NS",
    "CT_RELATIONSHIPS",
    "CT_XML",
    "CT_PNG",
    "CT_JPEG",
    "CT_GIF",
    "CT_TIFF",
    "CT_SVG",
    "CT_WORDPROCESSING_DOCUMENT",
    "CT_WORDPROCESSING_STYLES",
    "CT_WORDPROCESSING_NUMBERING",
    "CT_WORDPROCESSING_SETTINGS",
    "CT_WORDPROCESSING_HEADER",
    "CT_WORDPROCESSING_FOOTER",
    "CT_WORDPROCESSING_FONTTABLE",
    "CT_PRESENTATION_DOCUMENT",
    "CT_PRESENTATION_SLIDE",
    "CT_PRESENTATION_SLIDELAYOUT",
    "CT_PRESENTATION_SLIDEMASTER",
    "CT_DRAWINGML_THEME",
    "CT_CORE_PROPERTIES",
    "CT_EXTENDED_PROPERTIES",
    "RT_OFFICE_DOCUMENT",
    "RT_STYLES",
    "RT_NUMBERING",
    "RT_SETTINGS",
    "RT_FONTTABLE",
    "RT_HEADER",
    "RT_FOOTER",
    "RT_IMAGE",
    "RT_HYPERLINK",
    "RT_SLIDE",
    "RT_SLIDELAYOUT",
    "RT_SLIDEMASTER",
    "RT_THEME",
    "RT_CORE_PROPERTIES",
    "RT_EXTENDED_PROPERTIES",
    "normalize_part_name",
    "get_relationships_path",
    "OPCRelationship",
    "OPCPart",
    "OPCPackage",
]
