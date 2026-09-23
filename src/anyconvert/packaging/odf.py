"""Pure-Python OASIS OpenDocument Format (ODF) container packager.

Implements ISO/IEC 26300 OpenDocument package archive generation and parsing
for OpenDocument Text (ODT) and Presentation (ODP) document serialization
with zero external dependencies.

Enforces strict ISO/IEC 26300 container invariants:
- Stores 'mimetype' uncompressed (ZIP_STORED) as the first entry at byte offset 0.
- Guarantees zero extra header fields (extra=b"") for the 'mimetype' entry.
- Generates compliant META-INF/manifest.xml linking root and contained parts.
"""

from __future__ import annotations

import io
from os import PathLike
import posixpath
from typing import BinaryIO, Dict, List, Optional, Set, Tuple, Union
import xml.etree.ElementTree as ET
import zipfile

from anyconvert.exceptions import PackagingError


# ==============================================================================
# ODF Constants & Namespaces
# ==============================================================================

MIMETYPE_PART_NAME = "mimetype"
MANIFEST_PART_NAME = "META-INF/manifest.xml"

MANIFEST_NS = "urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"
MANIFEST_VERSION = "1.3"

# Common ODF MIME Types
MIMETYPE_ODT = "application/vnd.oasis.opendocument.text"
MIMETYPE_ODP = "application/vnd.oasis.opendocument.presentation"
MIMETYPE_ODS = "application/vnd.oasis.opendocument.spreadsheet"
MIMETYPE_ODG = "application/vnd.oasis.opendocument.graphics"

# Common Part Media Types
MEDIA_TYPE_TEXT_XML = "text/xml"
MEDIA_TYPE_IMAGE_PNG = "image/png"
MEDIA_TYPE_IMAGE_JPEG = "image/jpeg"
MEDIA_TYPE_IMAGE_GIF = "image/gif"
MEDIA_TYPE_IMAGE_SVG = "image/svg+xml"


# ==============================================================================
# Helper Functions
# ==============================================================================

def normalize_odf_part_name(part_name: str) -> str:
    """Normalize a part path to a clean relative POSIX path without leading slashes."""
    cleaned = posixpath.normpath(part_name.replace("\\", "/")).lstrip("/")
    if not cleaned or cleaned == ".":
        raise PackagingError(f"Invalid part name: {part_name!r}")
    return cleaned


def _xml_escape_attr(value: str) -> str:
    """Escape an attribute value for XML serialization."""
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


# ==============================================================================
# ODF Models
# ==============================================================================

class ODFPart:
    """A distinct byte content part within an ODF container."""

    __slots__ = ("part_name", "content", "media_type")

    def __init__(
        self,
        part_name: str,
        content: Union[str, bytes],
        media_type: str = MEDIA_TYPE_TEXT_XML,
    ) -> None:
        self.part_name: str = normalize_odf_part_name(part_name)
        if isinstance(content, str):
            self.content: bytes = content.encode("utf-8")
        elif isinstance(content, (bytes, bytearray, memoryview)):
            self.content = bytes(content)
        else:
            raise PackagingError(
                f"Part content must be str or bytes, got {type(content).__name__}"
            )
        self.media_type: str = media_type

    def __repr__(self) -> str:
        return (
            f"ODFPart(part_name={self.part_name!r}, size={len(self.content)}, "
            f"media_type={self.media_type!r})"
        )


# ==============================================================================
# ODF Package Engine
# ==============================================================================

class ODFPackage:
    """In-memory ISO/IEC 26300 compliant ODF container packager and validator."""

    __slots__ = ("mimetype", "parts")

    def __init__(self, mimetype: str = MIMETYPE_ODT) -> None:
        if not mimetype or "\n" in mimetype or "\r" in mimetype:
            raise PackagingError(f"Invalid ODF mimetype: {mimetype!r}")
        self.mimetype: str = mimetype.strip()
        self.parts: Dict[str, ODFPart] = {}

    def add_part(
        self,
        part_name: str,
        content: Union[str, bytes],
        media_type: str = MEDIA_TYPE_TEXT_XML,
    ) -> ODFPart:
        """Add a part to the ODF container.

        Args:
            part_name: Relative path within package (e.g., 'content.xml', 'Pictures/image1.png').
            content: String or bytes payload.
            media_type: MIME media type of the part.

        Returns:
            The created ODFPart instance.
        """
        norm_name = normalize_odf_part_name(part_name)
        if norm_name == MIMETYPE_PART_NAME:
            raise PackagingError(
                "Cannot add 'mimetype' directly as a regular part; set package.mimetype instead."
            )
        if norm_name == MANIFEST_PART_NAME:
            raise PackagingError(
                f"Cannot add {MANIFEST_PART_NAME!r} directly; it is generated automatically."
            )
        if norm_name in self.parts:
            raise PackagingError(f"Part {norm_name!r} already exists in ODF package")

        part = ODFPart(norm_name, content, media_type=media_type)
        self.parts[norm_name] = part
        return part

    def get_part(self, part_name: str) -> ODFPart:
        """Retrieve a part by name."""
        norm_name = normalize_odf_part_name(part_name)
        if norm_name not in self.parts:
            raise PackagingError(f"Part {norm_name!r} not found in ODF package")
        return self.parts[norm_name]

    def has_part(self, part_name: str) -> bool:
        """Check if a part exists in the package."""
        try:
            norm_name = normalize_odf_part_name(part_name)
            return norm_name in self.parts
        except PackagingError:
            return False

    def remove_part(self, part_name: str) -> None:
        """Remove a part from the package."""
        norm_name = normalize_odf_part_name(part_name)
        if norm_name in self.parts:
            del self.parts[norm_name]

    def build_manifest_xml(self) -> bytes:
        """Generate compliant META-INF/manifest.xml content.

        Specifies the root document entry ('/') with the package MIME type
        and all contained parts and subdirectories.
        """
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<manifest:manifest xmlns:manifest="{MANIFEST_NS}" manifest:version="{MANIFEST_VERSION}">',
            f'  <manifest:file-entry manifest:full-path="/" manifest:version="{MANIFEST_VERSION}" '
            f'manifest:media-type="{_xml_escape_attr(self.mimetype)}"/>',
        ]

        # Extract unique directories
        directories: Set[str] = set()
        for part in self.parts.values():
            dirname = posixpath.dirname(part.part_name)
            while dirname and dirname != ".":
                directories.add(f"{dirname}/")
                dirname = posixpath.dirname(dirname)

        # List subdirectories with empty media-type per ODF spec
        for d in sorted(directories):
            lines.append(
                f'  <manifest:file-entry manifest:full-path="{_xml_escape_attr(d)}" manifest:media-type=""/>'
            )

        # List all parts sorted by path
        sorted_parts = sorted(self.parts.values(), key=lambda p: p.part_name)
        for part in sorted_parts:
            lines.append(
                f'  <manifest:file-entry manifest:full-path="{_xml_escape_attr(part.part_name)}" '
                f'manifest:media-type="{_xml_escape_attr(part.media_type)}"/>'
            )

        lines.append("</manifest:manifest>")
        return "\n".join(lines).encode("utf-8")

    def to_bytes(self, compression: int = zipfile.ZIP_DEFLATED) -> bytes:
        """Serialize into an ISO/IEC 26300 compliant in-memory ZIP archive bytes buffer.

        Strict invariants enforced:
        1. 'mimetype' is entry #0 at byte offset 0.
        2. 'mimetype' is uncompressed (ZIP_STORED).
        3. 'mimetype' local header extra field is empty (extra=b"").
        4. 'mimetype' contains ASCII bytes with no newline or trailing whitespace.
        5. 'META-INF/manifest.xml' is written as entry #1.
        """
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, mode="w", compression=compression) as zf:
            # 1. First entry: mimetype (UNCOMPRESSED, ZERO EXTRA HEADER, BYTE OFFSET 0)
            zinfo = zipfile.ZipInfo(MIMETYPE_PART_NAME)
            zinfo.compress_type = zipfile.ZIP_STORED
            zinfo.extra = b""
            zinfo.date_time = (2026, 1, 1, 0, 0, 0)
            mimetype_bytes = self.mimetype.strip().encode("ascii")
            zf.writestr(zinfo, mimetype_bytes)

            # 2. Second entry: META-INF/manifest.xml
            manifest_bytes = self.build_manifest_xml()
            zf.writestr(MANIFEST_PART_NAME, manifest_bytes)

            # 3. Remaining parts
            sorted_parts = sorted(self.parts.values(), key=lambda p: p.part_name)
            for part in sorted_parts:
                zf.writestr(part.part_name, part.content)

        raw_bytes = buffer.getvalue()

        # Sanity check compliance of the generated archive
        self._verify_archive_compliance(raw_bytes)
        return raw_bytes

    def save(
        self,
        dest: Union[str, PathLike[str], BinaryIO],
        compression: int = zipfile.ZIP_DEFLATED,
    ) -> None:
        """Write the package archive to a file path or binary stream."""
        pkg_bytes = self.to_bytes(compression=compression)
        if isinstance(dest, (str, PathLike)):
            with open(dest, "wb") as f:
                f.write(pkg_bytes)
        else:
            dest.write(pkg_bytes)

    @classmethod
    def parse(cls, source: Union[bytes, BinaryIO, str, PathLike[str]]) -> ODFPackage:
        """Parse an existing ODF ZIP archive and verify ISO/IEC 26300 container constraints.

        Args:
            source: Raw bytes, binary file-like object, or file path.

        Returns:
            Populated and verified ODFPackage instance.

        Raises:
            PackagingError: If the archive violates ISO/IEC 26300 container constraints.
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
            if not zf.filelist:
                raise PackagingError("ODF archive is empty")

            # Invariant 1: First entry must be 'mimetype'
            first_info = zf.filelist[0]
            if first_info.filename != MIMETYPE_PART_NAME:
                raise PackagingError(
                    f"First file in ODF package must be {MIMETYPE_PART_NAME!r}, "
                    f"got {first_info.filename!r}"
                )

            # Invariant 2: 'mimetype' must be uncompressed (ZIP_STORED)
            if first_info.compress_type != zipfile.ZIP_STORED:
                raise PackagingError(
                    f"ODF 'mimetype' must be uncompressed (ZIP_STORED=0), "
                    f"got compress_type={first_info.compress_type}"
                )

            # Invariant 3: 'mimetype' extra field must be empty
            if len(first_info.extra) != 0:
                raise PackagingError(
                    f"ODF 'mimetype' must have zero extra field bytes, "
                    f"got {len(first_info.extra)} bytes"
                )

            # Invariant 4: 'mimetype' header offset must be 0
            if first_info.header_offset != 0:
                raise PackagingError(
                    f"ODF 'mimetype' must start at byte offset 0, "
                    f"got header_offset={first_info.header_offset}"
                )

            # Read mimetype content
            raw_mime = zf.read(MIMETYPE_PART_NAME)
            try:
                mimetype_str = raw_mime.decode("ascii")
            except UnicodeDecodeError as e:
                raise PackagingError(f"ODF 'mimetype' contains non-ASCII bytes: {e}") from e

            if "\n" in mimetype_str or "\r" in mimetype_str:
                raise PackagingError("ODF 'mimetype' must not contain newlines")

            # Invariant 5: META-INF/manifest.xml must exist
            namelist = set(zf.namelist())
            if MANIFEST_PART_NAME not in namelist:
                raise PackagingError(
                    f"ODF package missing required {MANIFEST_PART_NAME!r}"
                )

            pkg = cls(mimetype=mimetype_str)

            # Parse META-INF/manifest.xml to discover part media types
            manifest_xml = zf.read(MANIFEST_PART_NAME)
            media_types = cls._parse_manifest(manifest_xml)

            # Load parts
            for name in namelist:
                if name in (MIMETYPE_PART_NAME, MANIFEST_PART_NAME):
                    continue
                # Skip directory entries ending with '/'
                if name.endswith("/"):
                    continue

                content = zf.read(name)
                norm_name = normalize_odf_part_name(name)
                mtype = media_types.get(norm_name, MEDIA_TYPE_TEXT_XML)
                pkg.add_part(norm_name, content, media_type=mtype)

            return pkg

    @staticmethod
    def _verify_archive_compliance(data: bytes) -> None:
        """Perform byte-level validation of ISO/IEC 26300 container constraints."""
        with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
            if not zf.filelist:
                raise PackagingError("Generated ODF archive is empty")
            first = zf.filelist[0]
            if first.filename != MIMETYPE_PART_NAME:
                raise PackagingError(
                    f"Verification failed: first entry is {first.filename!r}, expected 'mimetype'"
                )
            if first.compress_type != zipfile.ZIP_STORED:
                raise PackagingError("Verification failed: 'mimetype' is not ZIP_STORED")
            if len(first.extra) != 0:
                raise PackagingError("Verification failed: 'mimetype' extra field is not empty")
            if first.header_offset != 0:
                raise PackagingError(
                    f"Verification failed: 'mimetype' offset is {first.header_offset}, expected 0"
                )

    @staticmethod
    def _parse_manifest(xml_data: bytes) -> Dict[str, str]:
        """Parse full-path to media-type mappings from META-INF/manifest.xml."""
        media_types: Dict[str, str] = {}
        try:
            root = ET.fromstring(xml_data)
        except Exception as e:
            raise PackagingError(f"Malformed META-INF/manifest.xml: {e}") from e

        for elem in root:
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if tag == "file-entry":
                full_path = elem.get(f"{{{MANIFEST_NS}}}full-path") or elem.get("full-path") or elem.get("manifest:full-path", "")
                media_type = elem.get(f"{{{MANIFEST_NS}}}media-type") or elem.get("media-type") or elem.get("manifest:media-type", "")
                if full_path and media_type:
                    cleaned_path = normalize_odf_part_name(full_path) if full_path != "/" else "/"
                    media_types[cleaned_path] = media_type

        return media_types


__all__ = [
    "MIMETYPE_PART_NAME",
    "MANIFEST_PART_NAME",
    "MANIFEST_NS",
    "MANIFEST_VERSION",
    "MIMETYPE_ODT",
    "MIMETYPE_ODP",
    "MIMETYPE_ODS",
    "MIMETYPE_ODG",
    "MEDIA_TYPE_TEXT_XML",
    "MEDIA_TYPE_IMAGE_PNG",
    "MEDIA_TYPE_IMAGE_JPEG",
    "MEDIA_TYPE_IMAGE_GIF",
    "MEDIA_TYPE_IMAGE_SVG",
    "normalize_odf_part_name",
    "ODFPart",
    "ODFPackage",
]
