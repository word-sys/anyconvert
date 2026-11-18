"""EPUB 3 Open Container Format (OCF 3.3) packager.

Implements zero-dependency EPUB 3 ZIP container generation and parsing
adhering strictly to W3C EPUB 3.3 Open Container Format invariants:
- Stores 'mimetype' uncompressed (ZIP_STORED) at byte offset 0.
- Guarantees zero extra header fields (extra=b"") on 'mimetype' so magic
  offset detection finds 'application/epub+zip' directly in the local header.
- Generates compliant META-INF/container.xml linking the OEBPS rootfile.
- Organizes package assets under OEBPS/ directory structure.
"""

from __future__ import annotations

import io
from os import PathLike
import posixpath
from typing import BinaryIO, Dict, List, Optional, Union
import xml.etree.ElementTree as ET
import zipfile

from anyconvert.exceptions import PackagingError

MIMETYPE_PART_NAME = "mimetype"
CONTAINER_PART_NAME = "META-INF/container.xml"
OEBPS_DIR = "OEBPS"
DEFAULT_ROOTFILE_PATH = "OEBPS/content.opf"

CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"
CONTAINER_VERSION = "1.0"

MIMETYPE_EPUB = "application/epub+zip"
MEDIA_TYPE_OPF = "application/oebps-package+xml"
MEDIA_TYPE_XHTML = "application/xhtml+xml"
MEDIA_TYPE_CSS = "text/css"
MEDIA_TYPE_NCX = "application/x-dtbncx+xml"
MEDIA_TYPE_SVG = "image/svg+xml"
MEDIA_TYPE_PNG = "image/png"
MEDIA_TYPE_JPEG = "image/jpeg"
MEDIA_TYPE_GIF = "image/gif"
MEDIA_TYPE_WEBP = "image/webp"
MEDIA_TYPE_WOFF2 = "font/woff2"
MEDIA_TYPE_XML = "application/xml"

_EXT_MEDIA_TYPES: Dict[str, str] = {
    ".opf": MEDIA_TYPE_OPF,
    ".xhtml": MEDIA_TYPE_XHTML,
    ".html": MEDIA_TYPE_XHTML,
    ".htm": MEDIA_TYPE_XHTML,
    ".css": MEDIA_TYPE_CSS,
    ".ncx": MEDIA_TYPE_NCX,
    ".svg": MEDIA_TYPE_SVG,
    ".png": MEDIA_TYPE_PNG,
    ".jpg": MEDIA_TYPE_JPEG,
    ".jpeg": MEDIA_TYPE_JPEG,
    ".gif": MEDIA_TYPE_GIF,
    ".webp": MEDIA_TYPE_WEBP,
    ".woff2": MEDIA_TYPE_WOFF2,
    ".xml": MEDIA_TYPE_XML,
}





def normalize_epub_part_name(part_name: str) -> str:
    """Normalize an EPUB container path to a clean relative POSIX path."""
    cleaned = posixpath.normpath(part_name.replace("\\", "/")).lstrip("/")
    if not cleaned or cleaned in (".", "..") or cleaned.startswith("../"):
        raise PackagingError(f"Invalid EPUB part name: {part_name!r}")
    return cleaned


def infer_epub_media_type(part_name: str) -> str:
    """Infer standard EPUB media type from file extension."""
    _, ext = posixpath.splitext(part_name.lower())
    return _EXT_MEDIA_TYPES.get(ext, "application/octet-stream")


def _xml_escape_attr(value: str) -> str:
    """Escape XML attribute value."""
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


class EPUBPart:
    """A single file resource stored inside an EPUB 3 OCF container."""

    __slots__ = ("part_name", "content", "media_type")

    def __init__(
        self,
        part_name: str,
        content: Union[str, bytes, bytearray, memoryview],
        media_type: Optional[str] = None,
    ) -> None:
        self.part_name: str = normalize_epub_part_name(part_name)
        if isinstance(content, str):
            self.content: bytes = content.encode("utf-8")
        elif isinstance(content, (bytes, bytearray, memoryview)):
            self.content = bytes(content)
        else:
            raise PackagingError(
                f"EPUB part content must be str or bytes, got {type(content).__name__}"
            )
        self.media_type: str = media_type or infer_epub_media_type(self.part_name)

    def __repr__(self) -> str:
        return (
            f"EPUBPart(part_name={self.part_name!r}, size={len(self.content)}, "
            f"media_type={self.media_type!r})"
        )


class EPUBPackage:
    """Zero-dependency W3C EPUB 3.3 OCF container packager and validator."""

    __slots__ = ("mimetype", "rootfile_path", "parts")

    def __init__(
        self,
        rootfile_path: str = DEFAULT_ROOTFILE_PATH,
        mimetype: str = MIMETYPE_EPUB,
    ) -> None:
        if not isinstance(mimetype, str) or "\n" in mimetype or "\r" in mimetype:
            raise PackagingError(f"Invalid EPUB mimetype: {mimetype!r}")
        cleaned_mime = mimetype.strip()
        if not cleaned_mime:
            raise PackagingError(f"Invalid EPUB mimetype: {mimetype!r}")
        try:
            cleaned_mime.encode("ascii")
        except UnicodeEncodeError as exc:
            raise PackagingError(f"EPUB mimetype must be ASCII: {exc}") from exc

        self.mimetype: str = cleaned_mime
        self.rootfile_path: str = normalize_epub_part_name(rootfile_path)
        self.parts: Dict[str, EPUBPart] = {}

    def add_part(
        self,
        part_name: str,
        content: Union[str, bytes, bytearray, memoryview],
        media_type: Optional[str] = None,
    ) -> EPUBPart:
        """Add a resource part at an explicit container path (e.g. 'OEBPS/content.opf')."""
        norm_name = normalize_epub_part_name(part_name)
        if norm_name == MIMETYPE_PART_NAME:
            raise PackagingError(
                "Cannot add 'mimetype' directly as a regular part; it is generated at byte 0."
            )
        if norm_name == CONTAINER_PART_NAME:
            raise PackagingError(
                f"Cannot add {CONTAINER_PART_NAME!r} directly; it is generated automatically."
            )
        if norm_name in self.parts:
            raise PackagingError(f"Part {norm_name!r} already exists in EPUB container")

        part = EPUBPart(norm_name, content, media_type=media_type)
        self.parts[norm_name] = part
        return part

    def add_oebps_part(
        self,
        relative_name: str,
        content: Union[str, bytes, bytearray, memoryview],
        media_type: Optional[str] = None,
    ) -> EPUBPart:
        """Add a resource part inside the OEBPS/ directory hierarchy."""
        norm_rel = normalize_epub_part_name(relative_name)
        prefix = f"{OEBPS_DIR}/"
        full_name = norm_rel if norm_rel.startswith(prefix) else f"{prefix}{norm_rel}"
        return self.add_part(full_name, content, media_type=media_type)

    def get_part(self, part_name: str) -> EPUBPart:
        """Retrieve a part by container path."""
        norm_name = normalize_epub_part_name(part_name)
        if norm_name not in self.parts:
            raise PackagingError(f"Part {norm_name!r} not found in EPUB container")
        return self.parts[norm_name]

    def has_part(self, part_name: str) -> bool:
        """Check whether a part exists at the given container path."""
        try:
            norm_name = normalize_epub_part_name(part_name)
            return norm_name in self.parts
        except PackagingError:
            return False

    def remove_part(self, part_name: str) -> None:
        """Remove a part from the container if present."""
        norm_name = normalize_epub_part_name(part_name)
        if norm_name in self.parts:
            del self.parts[norm_name]

    def list_parts(self) -> List[str]:
        """Return sorted list of non-OCF resource part paths."""
        return sorted(self.parts.keys())

    def build_container_xml(self) -> bytes:
        """Generate compliant META-INF/container.xml bytes pointing to rootfile."""
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<container version="{CONTAINER_VERSION}" xmlns="{CONTAINER_NS}">',
            "  <rootfiles>",
            (
                f'    <rootfile full-path="{_xml_escape_attr(self.rootfile_path)}" '
                f'media-type="{MEDIA_TYPE_OPF}"/>'
            ),
            "  </rootfiles>",
            "</container>",
        ]
        return "\n".join(lines).encode("utf-8")

    def to_bytes(self, compression: int = zipfile.ZIP_DEFLATED) -> bytes:
        """Serialize into an EPUB 3.3 OCF compliant ZIP archive byte buffer.

        Enforces strict OCF invariants:
        1. 'mimetype' is entry #0 at header byte offset 0.
        2. 'mimetype' uses ZIP_STORED (uncompressed).
        3. 'mimetype' extra field is empty (b"") so payload starts at offset 38.
        4. 'META-INF/container.xml' is present and references rootfile_path.
        """
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, mode="w", compression=compression) as zf:
            zinfo = zipfile.ZipInfo(MIMETYPE_PART_NAME)
            zinfo.compress_type = zipfile.ZIP_STORED
            zinfo.extra = b""
            zinfo.date_time = (2026, 1, 1, 0, 0, 0)
            mimetype_bytes = self.mimetype.encode("ascii")
            zf.writestr(zinfo, mimetype_bytes)

            container_bytes = self.build_container_xml()
            zf.writestr(CONTAINER_PART_NAME, container_bytes)

            for name in sorted(self.parts.keys()):
                zf.writestr(name, self.parts[name].content)

        raw_bytes = buffer.getvalue()
        self._verify_archive_compliance(raw_bytes, expected_mimetype=self.mimetype)
        return raw_bytes

    def save(
        self,
        dest: Union[str, PathLike[str], BinaryIO],
        compression: int = zipfile.ZIP_DEFLATED,
    ) -> None:
        """Write the EPUB archive to a file path or writable binary stream."""
        pkg_bytes = self.to_bytes(compression=compression)
        if isinstance(dest, (str, PathLike)):
            with open(dest, "wb") as f:
                f.write(pkg_bytes)
        else:
            dest.write(pkg_bytes)

    @classmethod
    def parse(cls, source: Union[bytes, BinaryIO, str, PathLike[str]]) -> EPUBPackage:
        """Parse an existing EPUB archive and enforce OCF 3.3 container invariants."""
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
        except Exception as exc:
            raise PackagingError(f"Failed to open EPUB source as ZIP archive: {exc}") from exc

        with zf:
            if not zf.filelist:
                raise PackagingError("EPUB archive is empty")

            first_info = zf.filelist[0]
            if first_info.filename != MIMETYPE_PART_NAME:
                raise PackagingError(
                    f"First file in EPUB container must be {MIMETYPE_PART_NAME!r}, "
                    f"got {first_info.filename!r}"
                )
            if first_info.compress_type != zipfile.ZIP_STORED:
                raise PackagingError(
                    f"EPUB 'mimetype' must be uncompressed (ZIP_STORED=0), "
                    f"got compress_type={first_info.compress_type}"
                )
            if len(first_info.extra) != 0:
                raise PackagingError(
                    f"EPUB 'mimetype' must have zero extra field bytes, "
                    f"got {len(first_info.extra)} bytes"
                )
            if first_info.header_offset != 0:
                raise PackagingError(
                    f"EPUB 'mimetype' must start at byte offset 0, "
                    f"got header_offset={first_info.header_offset}"
                )

            raw_mime = zf.read(MIMETYPE_PART_NAME)
            try:
                mime_str = raw_mime.decode("ascii")
            except UnicodeDecodeError as exc:
                raise PackagingError(f"EPUB 'mimetype' contains non-ASCII bytes: {exc}") from exc

            if mime_str != MIMETYPE_EPUB:
                raise PackagingError(
                    f"Invalid EPUB 'mimetype' payload: expected {MIMETYPE_EPUB!r}, got {mime_str!r}"
                )

            namelist = set(zf.namelist())
            if CONTAINER_PART_NAME not in namelist:
                raise PackagingError(
                    f"EPUB container missing required {CONTAINER_PART_NAME!r}"
                )

            container_xml = zf.read(CONTAINER_PART_NAME)
            rootfile_path = cls._parse_container_rootfile(container_xml)

            pkg = cls(rootfile_path=rootfile_path, mimetype=mime_str)

            # Parse OPF manifest media types if rootfile exists in archive
            opf_media_types: Dict[str, str] = {}
            if rootfile_path in namelist:
                opf_media_types = cls._parse_opf_manifest(
                    zf.read(rootfile_path), rootfile_path
                )

            for name in sorted(namelist):
                if name in (MIMETYPE_PART_NAME, CONTAINER_PART_NAME) or name.endswith("/"):
                    continue
                norm_name = normalize_epub_part_name(name)
                mtype = opf_media_types.get(norm_name, infer_epub_media_type(norm_name))
                pkg.add_part(norm_name, zf.read(name), media_type=mtype)

            return pkg

    @staticmethod
    def _verify_archive_compliance(
        data: bytes, expected_mimetype: str = MIMETYPE_EPUB
    ) -> None:
        """Verify byte-level OCF 3.3 ZIP layout constraints."""
        expected_magic_header = (
            b"PK\x03\x04"
        )
        if not data.startswith(expected_magic_header):
            raise PackagingError("Verification failed: EPUB archive missing ZIP header at byte 0")

        mime_bytes = expected_mimetype.encode("ascii")
        if data[30:38] != b"mimetype" or data[38 : 38 + len(mime_bytes)] != mime_bytes:
            raise PackagingError(
                "Verification failed: uncompressed 'mimetype' payload not aligned at byte 38"
            )

        with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
            if not zf.filelist:
                raise PackagingError("Generated EPUB archive is empty")
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
            if CONTAINER_PART_NAME not in zf.namelist():
                raise PackagingError(f"Verification failed: missing {CONTAINER_PART_NAME!r}")

    @staticmethod
    def _parse_container_rootfile(xml_data: bytes) -> str:
        """Extract the OPF rootfile path from META-INF/container.xml."""
        try:
            root = ET.fromstring(xml_data)
        except Exception as exc:
            raise PackagingError(f"Malformed {CONTAINER_PART_NAME}: {exc}") from exc

        for elem in root.iter():
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if tag == "rootfile":
                full_path = elem.get("full-path", "").strip()
                media_type = elem.get("media-type", "").strip()
                if not full_path:
                    continue
                if media_type and media_type != MEDIA_TYPE_OPF:
                    continue
                return normalize_epub_part_name(full_path)

        raise PackagingError(
            f"{CONTAINER_PART_NAME} missing valid <rootfile> with media-type {MEDIA_TYPE_OPF!r}"
        )

    @staticmethod
    def _parse_opf_manifest(xml_data: bytes, rootfile_path: str) -> Dict[str, str]:
        """Extract href to media-type mappings from an OPF package document."""
        mapping: Dict[str, str] = {}
        try:
            root = ET.fromstring(xml_data)
        except Exception:
            return mapping

        base_dir = posixpath.dirname(rootfile_path)
        for elem in root.iter():
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if tag == "item":
                href = elem.get("href", "").strip()
                media_type = elem.get("media-type", "").strip()
                if href and media_type:
                    joined = posixpath.join(base_dir, href) if base_dir else href
                    try:
                        mapping[normalize_epub_part_name(joined)] = media_type
                    except PackagingError:
                        continue
        return mapping


__all__ = [
    "MIMETYPE_PART_NAME",
    "CONTAINER_PART_NAME",
    "OEBPS_DIR",
    "DEFAULT_ROOTFILE_PATH",
    "CONTAINER_NS",
    "CONTAINER_VERSION",
    "MIMETYPE_EPUB",
    "MEDIA_TYPE_OPF",
    "MEDIA_TYPE_XHTML",
    "MEDIA_TYPE_CSS",
    "MEDIA_TYPE_NCX",
    "MEDIA_TYPE_SVG",
    "MEDIA_TYPE_PNG",
    "MEDIA_TYPE_JPEG",
    "MEDIA_TYPE_GIF",
    "MEDIA_TYPE_WEBP",
    "MEDIA_TYPE_WOFF2",
    "MEDIA_TYPE_XML",
    "normalize_epub_part_name",
    "infer_epub_media_type",
    "EPUBPart",
    "EPUBPackage",
]
