"""Tests for EPUB 3.3 package generation, OPF, navigation, and content emission."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest

from anyconvert.emitters.epub.opf import (
    DC_NS,
    OPF_NS,
    OPFMetadata,
    PackageDocument,
    build_content_opf,
    normalize_opf_href,
    sanitize_manifest_id,
)
from anyconvert.exceptions import PackagingError, SerializationError
from anyconvert.packaging.epub import (
    MEDIA_TYPE_CSS,
    MEDIA_TYPE_JPEG,
    MEDIA_TYPE_NCX,
    MEDIA_TYPE_OPF,
    MEDIA_TYPE_PNG,
    MEDIA_TYPE_XHTML,
    EPUBPackage,
)


def test_opf_path_and_id_helpers() -> None:
    """Verify OPF href relative normalization and XML NCName sanitization."""
    assert normalize_opf_href("OEBPS/Text/chapter_1.xhtml") == "Text/chapter_1.xhtml"
    assert normalize_opf_href("/OEBPS\\Images\\pic.png") == "Images/pic.png"
    assert normalize_opf_href("Styles/style.css") == "Styles/style.css"

    for bad in ("", ".", "..", "../escape.xhtml", "OEBPS/"):
        with pytest.raises(PackagingError):
            normalize_opf_href(bad)

    assert sanitize_manifest_id("01-chapter") == "item_01-chapter"
    assert sanitize_manifest_id("my chapter!") == "my_chapter_"
    assert sanitize_manifest_id("   ") == "item"


def test_opf_metadata_from_ir_and_defaults() -> None:
    """Verify Dublin Core mapping from DocumentIR metadata and EPUB 3 defaults."""
    default_meta = OPFMetadata.from_ir_metadata({})
    assert default_meta.title == "Untitled Document"
    assert default_meta.language == "en"
    assert default_meta.identifier.startswith("urn:uuid:")
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", default_meta.modified)

    raw_meta = {
        "Title": "Pure-Python EPUB: Architecture & Spec",
        "Author": "Alice Author; Bob Coauthor",
        "Subject": "Zero-dependency EPUB 3.3 generation",
        "Keywords": "epub, python; ebook, EPUB",
        "CreationDate": "D:20261118100000+03'00'",
        "ModDate": "D:20261118153045+03'00'",
        "Producer": "AnyConvert Press",
        "Language": "en_US",
        "Identifier": "978-0-12-345678-9",
    }
    meta = OPFMetadata.from_ir_metadata(raw_meta)
    assert meta.title == "Pure-Python EPUB: Architecture & Spec"
    assert meta.creators == ["Alice Author", "Bob Coauthor"]
    assert meta.description == "Zero-dependency EPUB 3.3 generation"
    assert meta.subjects == ["epub", "python", "ebook"]
    assert meta.date == "2026-11-18T10:00:00+03:00"
    assert meta.modified == "2026-11-18T12:30:45Z"  # Converted to UTC
    assert meta.publisher == "AnyConvert Press"
    assert meta.language == "en-US"
    assert meta.identifier == "urn:anyconvert:978-0-12-345678-9"


def test_package_document_xml_and_epub_container_integration() -> None:
    """Generate content.opf, verify EPUB 3.3 schema structure, and round-trip inside EPUBPackage."""
    meta = OPFMetadata(
        title='Annual Report & Summary <2026>\x00',
        creators=["Jane Doe"],
        language="en",
        identifier="urn:uuid:12345678-1234-5678-1234-567812345678",
        description="Financial overview",
        subjects=["Finance", "Annual"],
        date="2026-11-18",
        modified="2026-11-18T14:00:00Z",
    )
    opf = PackageDocument(metadata=meta)
    opf.add_navigation(href="nav.xhtml")
    opf.add_ncx(href="toc.ncx")
    opf.add_stylesheet(href="Styles/style.css")
    opf.add_image(href="Images/cover.png", item_id="cover-img", is_cover=True)
    opf.add_image(href="OEBPS/Images/chart.jpg")
    opf.add_xhtml(item_id="cover", href="Text/cover.xhtml", in_spine=True, linear=False)
    opf.add_xhtml(item_id="ch1", href="OEBPS/Text/chapter_1.xhtml", in_spine=True, linear=True)
    opf.add_xhtml(item_id="ch2", href="Text/chapter_2.xhtml", in_spine=True, linear=True)

    opf_xml = opf.to_xml(require_nav=True)
    root = ET.fromstring(opf_xml)

    assert root.tag == f"{{{OPF_NS}}}package"
    assert root.get("version") == "3.0"
    assert root.get("unique-identifier") == "pub-id"

    # Metadata verification
    meta_elem = root.find(f"{{{OPF_NS}}}metadata")
    assert meta_elem is not None
    dc_id = meta_elem.find(f"{{{DC_NS}}}identifier")
    assert dc_id is not None and dc_id.get("id") == "pub-id"
    assert dc_id.text == "urn:uuid:12345678-1234-5678-1234-567812345678"

    dc_title = meta_elem.find(f"{{{DC_NS}}}title")
    assert dc_title is not None and dc_title.text == "Annual Report & Summary <2026>"

    dc_lang = meta_elem.find(f"{{{DC_NS}}}language")
    assert dc_lang is not None and dc_lang.text == "en"

    creators = [el.text for el in meta_elem.findall(f"{{{DC_NS}}}creator")]
    assert creators == ["Jane Doe"]

    subjects = [el.text for el in meta_elem.findall(f"{{{DC_NS}}}subject")]
    assert subjects == ["Finance", "Annual"]

    mod_meta = [
        el for el in meta_elem.findall(f"{{{OPF_NS}}}meta")
        if el.get("property") == "dcterms:modified"
    ]
    assert len(mod_meta) == 1
    assert mod_meta[0].text == "2026-11-18T14:00:00Z"

    # Manifest verification
    manifest_elem = root.find(f"{{{OPF_NS}}}manifest")
    assert manifest_elem is not None
    items = {el.get("id"): el for el in manifest_elem.findall(f"{{{OPF_NS}}}item")}
    assert items["nav"].get("properties") == "nav"
    assert items["nav"].get("media-type") == MEDIA_TYPE_XHTML
    assert items["ncx"].get("media-type") == MEDIA_TYPE_NCX
    assert items["css"].get("media-type") == MEDIA_TYPE_CSS
    assert items["cover-img"].get("properties") == "cover-image"
    assert items["cover-img"].get("media-type") == MEDIA_TYPE_PNG
    assert items["img"].get("href") == "Images/chart.jpg"
    assert items["img"].get("media-type") == MEDIA_TYPE_JPEG
    assert items["ch1"].get("href") == "Text/chapter_1.xhtml"

    # Spine verification
    spine_elem = root.find(f"{{{OPF_NS}}}spine")
    assert spine_elem is not None
    assert spine_elem.get("toc") == "ncx"
    itemrefs = [
        (el.get("idref"), el.get("linear"))
        for el in spine_elem.findall(f"{{{OPF_NS}}}itemref")
    ]
    assert itemrefs == [("cover", "no"), ("ch1", "yes"), ("ch2", "yes")]

    # Container integration with EPUBPackage
    pkg = EPUBPackage()
    pkg.add_oebps_part("content.opf", opf.to_bytes(require_nav=True), media_type=MEDIA_TYPE_OPF)
    pkg.add_oebps_part("nav.xhtml", "<html/>", media_type=MEDIA_TYPE_XHTML)
    pkg.add_oebps_part("toc.ncx", "<ncx/>", media_type=MEDIA_TYPE_NCX)
    pkg.add_oebps_part("Styles/style.css", "body{}", media_type=MEDIA_TYPE_CSS)
    pkg.add_oebps_part("Images/cover.png", b"\x89PNG\r\n\x1a\n", media_type=MEDIA_TYPE_PNG)
    pkg.add_oebps_part("Images/chart.jpg", b"\xff\xd8\xff\xd9", media_type=MEDIA_TYPE_JPEG)
    pkg.add_oebps_part("Text/cover.xhtml", "<html/>", media_type=MEDIA_TYPE_XHTML)
    pkg.add_oebps_part("Text/chapter_1.xhtml", "<html/>", media_type=MEDIA_TYPE_XHTML)
    pkg.add_oebps_part("Text/chapter_2.xhtml", "<html/>", media_type=MEDIA_TYPE_XHTML)

    parsed = EPUBPackage.parse(pkg.to_bytes())
    assert parsed.get_part("OEBPS/Images/chart.jpg").media_type == MEDIA_TYPE_JPEG
    assert parsed.get_part("OEBPS/toc.ncx").media_type == MEDIA_TYPE_NCX


def test_build_content_opf_helper() -> None:
    """Verify functional build_content_opf helper constructs valid OPF XML."""
    opf_bytes = build_content_opf(
        metadata={"Title": "Handbook", "Author": "Editorial Team"},
        chapters=[("ch1", "Text/ch1.xhtml"), ("ch2", "Text/ch2.xhtml")],
        assets=[("img1", "Images/fig1.png", MEDIA_TYPE_PNG)],
    )
    root = ET.fromstring(opf_bytes)
    assert root.tag == f"{{{OPF_NS}}}package"
    spine = root.find(f"{{{OPF_NS}}}spine")
    assert spine is not None
    refs = [el.get("idref") for el in spine.findall(f"{{{OPF_NS}}}itemref")]
    assert refs == ["ch1", "ch2"]


def test_opf_validation_errors() -> None:
    """Verify OPF PackageDocument strictly rejects invalid IDs, duplicate entries, and dangling spine refs."""
    with pytest.raises(SerializationError):
        PackageDocument(unique_identifier_id="1invalid")

    opf = PackageDocument()
    # Empty manifest/spine cannot serialize
    with pytest.raises(SerializationError):
        opf.to_xml()

    opf.add_xhtml("ch1", "Text/ch1.xhtml", in_spine=False)
    # Missing spine itemref
    with pytest.raises(SerializationError):
        opf.to_xml()

    # Dangling spine idref
    with pytest.raises(SerializationError):
        opf.add_spine_item("nonexistent")

    # Duplicate ID
    with pytest.raises(SerializationError):
        opf.add_xhtml("ch1", "Text/ch1_dup.xhtml")

    # Duplicate href
    with pytest.raises(SerializationError):
        opf.add_xhtml("ch1_dup", "Text/ch1.xhtml")

    # Invalid NCName ID
    with pytest.raises(SerializationError):
        opf.add_manifest_item("9bad", "Text/other.xhtml", MEDIA_TYPE_XHTML)

    opf.add_spine_item("ch1")
    # Strict nav requirement fails when no nav item is registered
    with pytest.raises(SerializationError):
        opf.to_xml(require_nav=True)
