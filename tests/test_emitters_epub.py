"""Tests for EPUB 3.3 package generation, OPF, navigation, and content emission."""

from __future__ import annotations

import re
from typing import List
import xml.etree.ElementTree as ET

import pytest

from anyconvert.common.color import Color
from anyconvert.emitters.epub.nav import (
    EPUB_OPS_NS,
    NCX_NS,
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
    OPF_NS,
    OPFMetadata,
    PackageDocument,
    build_content_opf,
    normalize_opf_href,
    sanitize_manifest_id,
)
from anyconvert.exceptions import PackagingError, SerializationError
from anyconvert.ir.model import (
    BlockNode,
    DocumentIR,
    DocumentPage,
    HeadingLevel,
    Paragraph,
    TextRun,
)
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


# ==============================================================================
# Navigation Document (nav.xhtml & toc.ncx) Tests
# ==============================================================================


def test_toc_tree_hierarchy_and_ir_extraction() -> None:
    """Verify H1-H3 TOC tree nesting, skipped levels, and DocumentIR heading extraction."""
    flat = [
        TocEntry("Part I", "Text/ch1.xhtml", level=1),
        TocEntry("Section 1.1", "Text/ch1.xhtml#s1", level=2),
        TocEntry("Detail 1.1.1", "Text/ch1.xhtml#s1-1", level=3),
        TocEntry("Section 1.2", "Text/ch1.xhtml#s2", level=2),
        TocEntry("Part II", "Text/ch2.xhtml", level=1),
        TocEntry("Skipped H2 Detail", "Text/ch2.xhtml#s2-1", level=3),
    ]
    tree = build_toc_tree(flat)
    assert len(tree) == 2
    assert tree[0].title == "Part I"
    assert len(tree[0].children) == 2
    assert tree[0].children[0].children[0].title == "Detail 1.1.1"
    assert tree[1].children[0].title == "Skipped H2 Detail"
    assert compute_toc_depth(tree) == 3

    # Leading H2 before any H1 stays valid at root
    leading_h2 = build_toc_tree([TocEntry("Preface", "Text/ch1.xhtml#p", level=2)])
    assert len(leading_h2) == 1
    assert leading_h2[0].title == "Preface"

    # Extract only H1-H3 from DocumentIR (ignoring H4 and body paragraphs)
    black = Color.black()
    blocks: List[BlockNode] = [
        Paragraph(runs=[TextRun("Chapter 1", "Helvetica", 20.0, black)], heading_level=HeadingLevel.H1),
        Paragraph(runs=[TextRun("Body prose.", "Helvetica", 12.0, black)]),
        Paragraph(runs=[TextRun("Section A", "Helvetica", 16.0, black)], heading_level=HeadingLevel.H2),
        Paragraph(runs=[TextRun("Subsection A.1", "Helvetica", 14.0, black)], heading_level=HeadingLevel.H3),
        Paragraph(runs=[TextRun("Minor Note", "Helvetica", 12.0, black)], heading_level=HeadingLevel.H4),
    ]
    doc = DocumentIR(pages=[DocumentPage(1, 612.0, 792.0, blocks=blocks)])
    ir_tree = extract_toc_entries_from_ir(doc, default_href="Text/chapter_1.xhtml")
    assert len(ir_tree) == 1
    assert ir_tree[0].title == "Chapter 1"
    assert ir_tree[0].href == "Text/chapter_1.xhtml#heading-1"
    assert len(ir_tree[0].children) == 1
    assert ir_tree[0].children[0].children[0].title == "Subsection A.1"
    assert compute_toc_depth(ir_tree) == 3


def test_generate_nav_xhtml_structure_and_fallback() -> None:
    """Verify EPUB 3.3 nav.xhtml XML namespaces, nested <ol>, landmarks, and empty fallback."""
    tree = build_toc_tree(
        [
            TocEntry("Intro & Setup", "Text/ch1.xhtml", level=1),
            TocEntry("Install <Linux>", "Text/ch1.xhtml#install", level=2),
            TocEntry("Usage", "Text/ch2.xhtml", level=1),
        ]
    )
    nav_bytes = generate_nav_xhtml(
        entries=tree,
        title="Contents",
        language="en-US",
        stylesheet_href="OEBPS/Styles/style.css",
    )
    root = ET.fromstring(nav_bytes)
    assert root.tag == f"{{{XHTML_NS}}}html"

    link = root.find(f".//{{{XHTML_NS}}}link")
    assert link is not None and link.get("href") == "Styles/style.css"

    navs = root.findall(f".//{{{XHTML_NS}}}nav")
    toc_nav = next(
        (n for n in navs if n.get(f"{{{EPUB_OPS_NS}}}type") == "toc"),
        None,
    )
    assert toc_nav is not None
    anchors = [a.text for a in toc_nav.findall(f".//{{{XHTML_NS}}}a")]
    assert anchors == ["Intro & Setup", "Install <Linux>", "Usage"]

    # Nested <ol> exists under first <li>
    nested_ols = toc_nav.findall(f".//{{{XHTML_NS}}}ol/{{{XHTML_NS}}}li/{{{XHTML_NS}}}ol")
    assert len(nested_ols) == 1

    # Landmarks nav exists
    landmarks_nav = next(
        (n for n in navs if n.get(f"{{{EPUB_OPS_NS}}}type") == "landmarks"),
        None,
    )
    assert landmarks_nav is not None

    # Empty TOC falls back to single valid <li>
    empty_nav = ET.fromstring(generate_nav_xhtml(entries=[], default_href="Text/chapter_1.xhtml"))
    empty_links = empty_nav.findall(f".//{{{XHTML_NS}}}nav[@id='toc']//{{{XHTML_NS}}}a")
    assert len(empty_links) == 1
    assert empty_links[0].get("href") == "Text/chapter_1.xhtml"


def test_generate_toc_ncx_and_navigation_builder_integration() -> None:
    """Verify legacy DAISY NCX playOrder, dtb:uid/dtb:depth, and EPUBPackage round-trip."""
    uid = "urn:uuid:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    tree = build_toc_tree(
        [
            TocEntry("Chapter 1", "Text/ch1.xhtml", level=1),
            TocEntry("Topic 1.1", "Text/ch1.xhtml#t1", level=2),
            TocEntry("Subtopic 1.1.1", "Text/ch1.xhtml#t1-1", level=3),
            TocEntry("Chapter 2", "Text/ch2.xhtml", level=1),
        ]
    )
    builder = NavigationBuilder(
        entries=tree,
        identifier=uid,
        title="Guide & Manual",
        author="Tech Author",
        language="en",
        stylesheet_href="Styles/style.css",
    )
    nav_bytes = builder.build_nav_xhtml()
    ncx_bytes = builder.build_toc_ncx()

    ncx_root = ET.fromstring(ncx_bytes)
    assert ncx_root.tag == f"{{{NCX_NS}}}ncx"
    assert ncx_root.get("version") == "2005-1"

    metas = {
        el.get("name"): el.get("content")
        for el in ncx_root.findall(f".//{{{NCX_NS}}}head/{{{NCX_NS}}}meta")
    }
    assert metas["dtb:uid"] == uid
    assert metas["dtb:depth"] == "3"

    doc_title = ncx_root.find(f"{{{NCX_NS}}}docTitle/{{{NCX_NS}}}text")
    assert doc_title is not None and doc_title.text == "Guide & Manual"

    doc_author = ncx_root.find(f"{{{NCX_NS}}}docAuthor/{{{NCX_NS}}}text")
    assert doc_author is not None and doc_author.text == "Tech Author"

    # Depth-first sequential playOrder 1..4
    nav_points = list(ncx_root.iter(f"{{{NCX_NS}}}navPoint"))
    assert [np.get("playOrder") for np in nav_points] == ["1", "2", "3", "4"]
    assert [np.get("id") for np in nav_points] == [
        "navPoint-1",
        "navPoint-2",
        "navPoint-3",
        "navPoint-4",
    ]

    # Empty TOC fallback in NCX
    empty_ncx = ET.fromstring(generate_toc_ncx(entries=[], identifier=uid, title="Blank"))
    empty_nps = list(empty_ncx.iter(f"{{{NCX_NS}}}navPoint"))
    assert len(empty_nps) == 1
    assert empty_nps[0].get("playOrder") == "1"

    # Full container round-trip with OPF + nav.xhtml + toc.ncx
    opf = PackageDocument(metadata=OPFMetadata(title="Guide & Manual", identifier=uid))
    opf.add_navigation("nav.xhtml")
    opf.add_ncx("toc.ncx")
    opf.add_stylesheet("Styles/style.css")
    opf.add_xhtml("ch1", "Text/ch1.xhtml")
    opf.add_xhtml("ch2", "Text/ch2.xhtml")

    pkg = EPUBPackage()
    pkg.add_oebps_part("content.opf", opf.to_bytes(require_nav=True), media_type=MEDIA_TYPE_OPF)
    pkg.add_oebps_part("nav.xhtml", nav_bytes, media_type=MEDIA_TYPE_XHTML)
    pkg.add_oebps_part("toc.ncx", ncx_bytes, media_type=MEDIA_TYPE_NCX)
    pkg.add_oebps_part("Styles/style.css", "body {}", media_type=MEDIA_TYPE_CSS)
    pkg.add_oebps_part("Text/ch1.xhtml", "<html/>", media_type=MEDIA_TYPE_XHTML)
    pkg.add_oebps_part("Text/ch2.xhtml", "<html/>", media_type=MEDIA_TYPE_XHTML)

    parsed = EPUBPackage.parse(pkg.to_bytes())
    assert ET.fromstring(parsed.get_part("OEBPS/nav.xhtml").content) is not None
    assert ET.fromstring(parsed.get_part("OEBPS/toc.ncx").content) is not None
