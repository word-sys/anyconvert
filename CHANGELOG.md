# Changelog

All notable changes to this project will be documented in this file.

## [0.1.12] - 2026-11-19

### Added
- **EPUB 3.3 E-Book Generation Engine (`-f epub`)**: Added zero-dependency W3C EPUB 3.3 digital book emitter (`EpubEmitter`) with OCF 3.3 ZIP container packaging (`mimetype` uncompressed at byte offset 0, `META-INF/container.xml`, `OEBPS/` directory structure), OPF 3.0 `content.opf` with Dublin Core metadata and UTC `dcterms:modified`, hierarchical H1–H3 `nav.xhtml` plus legacy DAISY `toc.ncx` fallback for Kindle/Kobo, automatic chapter splitting at `H1` or page boundaries, embedded typography, packaged images, and inline SVG support.
- **Markdown / GFM Emitter (`-f md`)**: Dedicated Markdown generation engine supporting CommonMark and GitHub Flavored Markdown dialects, ATX headings (`#`–`######`), inline rich text styling, 2D GFM table matrix formatting (`col_span`/`row_span` normalization, multi-line `<br>` escaping, automatic `:---` / `:---:` / `---:` alignment detection), fenced code blocks with language hints and backtick fence escaping, and extended GFM task lists (Unicode ballot boxes, checkmarks, radio buttons).
- **YAML Frontmatter & PDF Date Normalization**: Added pure-Python YAML frontmatter generator (`title`, `author`, `description`, `keywords`, `date`, `lastmod`, `creator`, `producer`) ready for Hugo, Jekyll, Docusaurus, and VitePress, alongside ISO 8601 PDF date parsing (`parse_pdf_date()`).
- **Image Asset Extraction Mode (`--extract-images [DIR]`)**: Added CLI option and Python API `extract_images` parameter to write embedded JPEG, PNG, and WebP assets to disk and link them cleanly in Markdown (`![alt](images/img_1.jpeg)`).
- **Unicode Box-Drawing Plaintext Canvas (`-f txt -m canvas`)**: Upgraded the 2D character grid emitter with directional junction-merging Unicode box-drawing characters (`┌─┐│└─┘┬┴├┤┼`) for table borders, `col_span` cells, image frames, and vector SVG paths (with optional ASCII fallback).

### Changed
- **CLI & API Format Expansion**: Added `md` and `epub` to supported formats in CLI (`-f md`, `-f epub`) and Python API (`output_format="md"`, `output_format="epub"`), and refactored `TxtFlowEmitter` to subclass `MarkdownEmitter(include_frontmatter=False)`.

### Fixed
- **PDF `/Info` Metadata Extraction**: Enhanced `PDFDocument.get_metadata()` to dereference indirect `/Info` string references (`PDFIndirectRef`), decrypt encrypted metadata strings, strip null bytes, and normalize `CreationDate`/`ModDate` values.

---

## [0.1.11] - 2026-10-29

### Added
- **HTML5 Emitter Module**: Added zero-dependency HTML5 document conversion engine supporting both reflowable semantic documents (`--mode flow`) and pixel-accurate fixed visual canvas layouts (`--mode canvas`).
- **Semantic HTML5 Flow Mode**: Automatic extraction and rendering of semantic HTML5 tags (`<article>`, `<header>`, `<footer>`, `<h1>`–`<h6>`, `<ul class="flow-list">`, `<ol class="flow-list">`, and `<table class="pure-table">`).
- **Pixel-Accurate HTML5 Canvas Mode**: Coordinate-positioned absolute layout engine (`position: absolute; left: ...pt; top: ...pt;`) with layered SVG vector rendering, font styling, tracking, and affine matrix transforms.
- **Single-File Self-Contained HTML Packaging**: Inlining of all raster assets as Base64 Data URIs (`data:{mime};base64,...`), embedded vector paths, metadata meta tags, and zero-telemetry offline Content-Security-Policy (`<meta http-equiv="Content-Security-Policy">`).
- **Standalone SVG Page Exporter**: Implemented native SVG vector exporter (`-f svg`) generating standalone scalable `.svg` pages with vector curves, embedded images, text runs, and table outlines.
- **WebP Image Format Support**: Native detection, decoding, and embedding of RIFF/WebP images across target containers.

### Changed
- **Unified Emitter Test Suite Consolidation**: Streamlined and merged fragmented test suites into cohesive emitter test modules (`test_emitters_html.py`, `test_emitters_docx_pptx.py`, `test_emitters_odt_odp.py`, `test_image_filters.py`).
- **CLI & API Integration**: Added `html` and `svg` to top-level format targets in CLI (`-f html`, `-f svg`) and Python API (`output_format="html"`, `output_format="svg"`).

### Fixed
- **Native PowerPoint Vector Graphics & Shapes (DrawingML)**: Resolved README Known Issue #2 by mapping `VectorBlock` paths to PowerPoint DrawingML custom shapes (`<p:sp><p:spPr><a:custGeom>`). Hand-drawn pen markups, lines, arrows, and shapes now display accurately in PPTX presentations.
- **Native Word & ODF Vector Graphics Translation**: Implemented native DrawingML `<wps:wsp>` shapes for DOCX and native `<draw:path svg:d="..." draw:style-name="...">` for LibreOffice Writer (ODT) and Impress (ODP).
- **PDF Vector Path Parser Overhaul**: Decomposed cubic Bézier curves (`c`, `v`, `y`), subpath moves, rectangles, and closepath operators with full stroke/fill color, line join, line cap, and dash pattern preservation.

---

## [0.1.10] - 2026-10-28

### Added
- **JPXDecode (JPEG 2000) Stream Parser**: Codestream detection, header extraction, JP2 container wrapping, and pass-through transcode support.
- **JBIG2 Decompression Engine**: Support for generic region decoding, MMR arithmetic decoding, and multi-page stream parsing.
- **CCITTFaxDecode Support**: Pure-Python ITU-T Group 3 (1D/2D) and Group 4 (2D) decompression for bi-level raster scans.
- **PDF Typography & ToUnicode CMap Engine**: CIDFont width extraction, dynamic `/Differences` re-encoding, and Type 1/CFF font interpretation.
