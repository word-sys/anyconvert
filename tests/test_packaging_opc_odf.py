"""Tests for pure-Python Open Packaging Conventions (OPC) and OpenDocument (ODF) packagers."""

import io
import pathlib
import zipfile
import pytest

from anyconvert.exceptions import PackagingError
from anyconvert.packaging.odf import (
    MANIFEST_PART_NAME,
    MEDIA_TYPE_IMAGE_PNG,
    MEDIA_TYPE_TEXT_XML,
    MIMETYPE_ODP,
    MIMETYPE_ODT,
    MIMETYPE_PART_NAME,
    ODFPackage,
    ODFPart,
    normalize_odf_part_name,
)
from anyconvert.packaging.opc import (
    CONTENT_TYPES_PART_NAME,
    CT_PNG,
    CT_WORDPROCESSING_DOCUMENT,
    CT_WORDPROCESSING_STYLES,
    OPCPackage,
    OPCPart,
    OPCRelationship,
    PACKAGE_RELATIONSHIPS_PART_NAME,
    RT_HYPERLINK,
    RT_IMAGE,
    RT_OFFICE_DOCUMENT,
    RT_STYLES,
    get_relationships_path,
    normalize_part_name,
)


# ==============================================================================
# OPC Packager Tests
# ==============================================================================

def test_opc_part_normalization() -> None:
    """Test POSIX part name normalization."""
    assert normalize_part_name("word/document.xml") == "word/document.xml"
    assert normalize_part_name("/word/document.xml") == "word/document.xml"
    assert normalize_part_name("\\word\\document.xml") == "word/document.xml"
    assert normalize_part_name("document.xml") == "document.xml"

    with pytest.raises(PackagingError):
        normalize_part_name("")
    with pytest.raises(PackagingError):
        normalize_part_name("/")
    with pytest.raises(PackagingError):
        normalize_part_name(".")


def test_opc_relationships_path() -> None:
    """Test computing relationship part paths."""
    assert get_relationships_path("word/document.xml") == "word/_rels/document.xml.rels"
    assert get_relationships_path("document.xml") == "_rels/document.xml.rels"
    assert get_relationships_path("ppt/slides/slide1.xml") == "ppt/slides/_rels/slide1.xml.rels"


def test_opc_part_relationships() -> None:
    """Test adding, retrieving, and filtering relationships on an OPCPart."""
    part = OPCPart("word/document.xml", "<document/>", CT_WORDPROCESSING_DOCUMENT)
    assert part.part_name == "word/document.xml"
    assert part.content == b"<document/>"
    assert part.content_type == CT_WORDPROCESSING_DOCUMENT

    # Auto rId sequencing
    rel1 = part.add_relationship(RT_STYLES, "styles.xml")
    assert rel1.rel_id == "rId1"
    assert rel1.rel_type == RT_STYLES
    assert rel1.target == "styles.xml"
    assert rel1.target_mode == "Internal"

    rel2 = part.add_relationship(RT_IMAGE, "media/image1.png")
    assert rel2.rel_id == "rId2"

    # Explicit rId
    rel3 = part.add_relationship(
        RT_HYPERLINK, "https://example.com", target_mode="External", rel_id="rId99"
    )
    assert rel3.rel_id == "rId99"
    assert rel3.target_mode == "External"

    # Next auto rId after rId99 should be rId100
    rel4 = part.add_relationship(RT_STYLES, "styles2.xml")
    assert rel4.rel_id == "rId100"

    assert len(part.relationships) == 4
    assert part.get_relationship("rId1") == rel1
    assert len(part.find_relationships_by_type(RT_STYLES)) == 2

    # Duplicate rId error
    with pytest.raises(PackagingError):
        part.add_relationship(RT_STYLES, "styles3.xml", rel_id="rId1")

    # Invalid target mode
    with pytest.raises(PackagingError):
        part.add_relationship(RT_STYLES, "styles3.xml", target_mode="InvalidMode")


def test_opc_package_build_and_roundtrip() -> None:
    """Test creating, serializing, and parsing an OPC package roundtrip."""
    pkg = OPCPackage()

    # Add root package relationship
    pkg.add_package_relationship(RT_OFFICE_DOCUMENT, "word/document.xml")

    # Add document part
    doc_part = pkg.add_part(
        "word/document.xml",
        "<w:document><w:body><w:p/></w:body></w:document>",
        content_type=CT_WORDPROCESSING_DOCUMENT,
    )
    doc_part.add_relationship(RT_STYLES, "styles.xml")
    doc_part.add_relationship(RT_IMAGE, "media/image1.png")

    # Add styles part
    pkg.add_part(
        "word/styles.xml",
        "<w:styles/>",
        content_type=CT_WORDPROCESSING_STYLES,
    )

    # Add binary image part
    img_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    pkg.add_part("word/media/image1.png", img_bytes, content_type=CT_PNG)

    # Serialize to ZIP bytes
    zip_bytes = pkg.to_bytes()
    assert len(zip_bytes) > 0

    # Inspect the ZIP structure directly
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        namelist = set(zf.namelist())
        assert CONTENT_TYPES_PART_NAME in namelist
        assert PACKAGE_RELATIONSHIPS_PART_NAME in namelist
        assert "word/document.xml" in namelist
        assert "word/styles.xml" in namelist
        assert "word/media/image1.png" in namelist
        assert "word/_rels/document.xml.rels" in namelist

        ct_xml = zf.read(CONTENT_TYPES_PART_NAME).decode("utf-8")
        assert 'PartName="/word/document.xml"' in ct_xml
        assert 'Extension="png"' in ct_xml

        doc_rels_xml = zf.read("word/_rels/document.xml.rels").decode("utf-8")
        assert 'Target="styles.xml"' in doc_rels_xml
        assert 'Target="media/image1.png"' in doc_rels_xml

    # Parse back from bytes
    parsed_pkg = OPCPackage.parse(zip_bytes)
    assert parsed_pkg.has_part("word/document.xml")
    assert parsed_pkg.has_part("word/styles.xml")
    assert parsed_pkg.has_part("word/media/image1.png")

    parsed_doc = parsed_pkg.get_part("word/document.xml")
    assert parsed_doc.content_type == CT_WORDPROCESSING_DOCUMENT
    assert len(parsed_doc.relationships) == 2
    assert parsed_doc.get_relationship("rId1").target == "styles.xml"
    assert parsed_doc.get_relationship("rId2").target == "media/image1.png"

    parsed_img = parsed_pkg.get_part("word/media/image1.png")
    assert parsed_img.content == img_bytes
    assert parsed_img.content_type == CT_PNG


def test_opc_error_conditions(tmp_path: pathlib.Path) -> None:
    """Test error conditions and exceptions in OPCPackage."""
    pkg = OPCPackage()
    pkg.add_part("test.xml", "<root/>", content_type="application/xml")

    # Duplicate part
    with pytest.raises(PackagingError):
        pkg.add_part("test.xml", "<root/>")

    # Non-existent part
    with pytest.raises(PackagingError):
        pkg.get_part("nonexistent.xml")

    # Non-existent relationship
    part = pkg.get_part("test.xml")
    with pytest.raises(PackagingError):
        part.get_relationship("rId999")

    # Save to file path
    file_path = tmp_path / "test.docx"
    pkg.save(file_path)
    assert file_path.exists()
    assert file_path.stat().st_size > 0

    # Parse from file path
    parsed = OPCPackage.parse(file_path)
    assert parsed.has_part("test.xml")

    # Parse invalid data
    with pytest.raises(PackagingError):
        OPCPackage.parse(b"NOT_A_ZIP_ARCHIVE")

    # Parse zip missing [Content_Types].xml
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("dummy.txt", "hello")
    with pytest.raises(PackagingError):
        OPCPackage.parse(buf.getvalue())


# ==============================================================================
# ODF Packager Tests
# ==============================================================================

def test_odf_part_normalization() -> None:
    """Test POSIX part name normalization in ODF."""
    assert normalize_odf_part_name("content.xml") == "content.xml"
    assert normalize_odf_part_name("/content.xml") == "content.xml"
    assert normalize_odf_part_name("Pictures\\image1.png") == "Pictures/image1.png"

    with pytest.raises(PackagingError):
        normalize_odf_part_name("")
    with pytest.raises(PackagingError):
        normalize_odf_part_name("/")


def test_odf_iso_26300_container_invariants() -> None:
    """Test strict ISO/IEC 26300 container constraints on generated ODF packages."""
    pkg = ODFPackage(mimetype=MIMETYPE_ODT)
    pkg.add_part("content.xml", "<office:document-content/>")
    pkg.add_part("styles.xml", "<office:document-styles/>")
    pkg.add_part("Pictures/img1.png", b"\x89PNG\r\n\x1a\n", media_type=MEDIA_TYPE_IMAGE_PNG)

    zip_bytes = pkg.to_bytes()

    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        # Invariant 1: First file must be 'mimetype'
        assert zf.filelist[0].filename == MIMETYPE_PART_NAME

        # Invariant 2: 'mimetype' must be uncompressed (ZIP_STORED = 0)
        assert zf.filelist[0].compress_type == zipfile.ZIP_STORED

        # Invariant 3: 'mimetype' extra field must be empty
        assert len(zf.filelist[0].extra) == 0

        # Invariant 4: 'mimetype' header offset must be 0
        assert zf.filelist[0].header_offset == 0

        # Invariant 5: 'mimetype' content exact bytes without newlines
        mime_content = zf.read(MIMETYPE_PART_NAME)
        assert mime_content == b"application/vnd.oasis.opendocument.text"
        assert b"\n" not in mime_content
        assert b"\r" not in mime_content

        # Invariant 6: Second entry is META-INF/manifest.xml
        assert zf.filelist[1].filename == MANIFEST_PART_NAME

        # Verify manifest content
        manifest_xml = zf.read(MANIFEST_PART_NAME).decode("utf-8")
        assert 'manifest:full-path="/"' in manifest_xml
        assert f'manifest:media-type="{MIMETYPE_ODT}"' in manifest_xml
        assert 'manifest:full-path="content.xml"' in manifest_xml
        assert 'manifest:full-path="Pictures/img1.png"' in manifest_xml
        assert f'manifest:media-type="{MEDIA_TYPE_IMAGE_PNG}"' in manifest_xml


def test_odf_roundtrip_parsing(tmp_path: pathlib.Path) -> None:
    """Test ODF package serialization and roundtrip parsing."""
    pkg = ODFPackage(mimetype=MIMETYPE_ODP)
    pkg.add_part("content.xml", "<presentation-content/>", media_type=MEDIA_TYPE_TEXT_XML)
    pkg.add_part("meta.xml", "<meta/>", media_type=MEDIA_TYPE_TEXT_XML)
    pkg.add_part("Pictures/slide_bg.png", b"PNG_DATA", media_type=MEDIA_TYPE_IMAGE_PNG)

    # Save to disk
    out_file = tmp_path / "presentation.odp"
    pkg.save(out_file)
    assert out_file.exists()

    # Parse back from file
    parsed = ODFPackage.parse(out_file)
    assert parsed.mimetype == MIMETYPE_ODP
    assert parsed.has_part("content.xml")
    assert parsed.has_part("meta.xml")
    assert parsed.has_part("Pictures/slide_bg.png")

    assert parsed.get_part("content.xml").content == b"<presentation-content/>"
    assert parsed.get_part("content.xml").media_type == MEDIA_TYPE_TEXT_XML
    assert parsed.get_part("Pictures/slide_bg.png").content == b"PNG_DATA"
    assert parsed.get_part("Pictures/slide_bg.png").media_type == MEDIA_TYPE_IMAGE_PNG


def test_odf_error_conditions() -> None:
    """Test defensive error handling for ODF package operations."""
    pkg = ODFPackage(mimetype=MIMETYPE_ODT)

    # Invalid mimetype strings
    with pytest.raises(PackagingError):
        ODFPackage(mimetype="")
    with pytest.raises(PackagingError):
        ODFPackage(mimetype="text/plain\n")

    # Adding reserved container files directly
    with pytest.raises(PackagingError):
        pkg.add_part("mimetype", "text")
    with pytest.raises(PackagingError):
        pkg.add_part("META-INF/manifest.xml", "<manifest/>")

    # Duplicate part
    pkg.add_part("content.xml", "<content/>")
    with pytest.raises(PackagingError):
        pkg.add_part("content.xml", "<duplicate/>")

    # Non-existent part
    with pytest.raises(PackagingError):
        pkg.get_part("missing.xml")

    # Corrupt zip
    with pytest.raises(PackagingError):
        ODFPackage.parse(b"NOT_A_ZIP")

    # Empty zip
    buf_empty = io.BytesIO()
    with zipfile.ZipFile(buf_empty, "w") as zf:
        pass
    with pytest.raises(PackagingError):
        ODFPackage.parse(buf_empty.getvalue())

    # Zip where first entry is not mimetype
    buf_wrong_first = io.BytesIO()
    with zipfile.ZipFile(buf_wrong_first, "w") as zf:
        zf.writestr("content.xml", "<content/>")
        zf.writestr("mimetype", "application/vnd.oasis.opendocument.text")
    with pytest.raises(PackagingError):
        ODFPackage.parse(buf_wrong_first.getvalue())

    # Zip where mimetype is compressed (DEFLATED)
    buf_compressed_mime = io.BytesIO()
    with zipfile.ZipFile(buf_compressed_mime, "w") as zf:
        zinfo = zipfile.ZipInfo("mimetype")
        zinfo.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(zinfo, b"application/vnd.oasis.opendocument.text")
        zf.writestr("META-INF/manifest.xml", "<manifest/>")
    with pytest.raises(PackagingError):
        ODFPackage.parse(buf_compressed_mime.getvalue())

    # Zip where mimetype has extra field
    buf_extra = io.BytesIO()
    with zipfile.ZipFile(buf_extra, "w") as zf:
        zinfo = zipfile.ZipInfo("mimetype")
        zinfo.compress_type = zipfile.ZIP_STORED
        zinfo.extra = b"\x01\x02\x03\x04"
        zf.writestr(zinfo, b"application/vnd.oasis.opendocument.text")
        zf.writestr("META-INF/manifest.xml", "<manifest/>")
    with pytest.raises(PackagingError):
        ODFPackage.parse(buf_extra.getvalue())

    # Zip missing META-INF/manifest.xml
    buf_no_manifest = io.BytesIO()
    with zipfile.ZipFile(buf_no_manifest, "w") as zf:
        zinfo = zipfile.ZipInfo("mimetype")
        zinfo.compress_type = zipfile.ZIP_STORED
        zinfo.extra = b""
        zf.writestr(zinfo, b"application/vnd.oasis.opendocument.text")
    with pytest.raises(PackagingError):
        ODFPackage.parse(buf_no_manifest.getvalue())
