# anyconvert

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/license-GPLv3+-blue.svg)](LICENSE)
[![Downloads](https://img.shields.io/pepy/dt/anyconvert)](https://pepy.tech/projects/anyconvert)

**Python document conversion engine**

`anyconvert` converts PDF documents into **DOCX**, **PPTX**, **ODT**, **ODP**, **TXT**, **SVG**, **HTML5**, **Markdown (GFM)**, **EPUB 3**, **RTF**, **Typst**, **LaTeX**, **JSON AST**, **CSV**, and **XLSX** using only the Python standard library.

---

## Highlights

- **Dual Layout Engines**:
  - **Canvas Mode (`--mode canvas`)**: 1:1 pixel-accurate positioning. Renders exact coordinates, font families, embedded images, and vector artwork (native DrawingML custom geometries in DOCX and PPTX, SVG paths in ODT, and CSS/SVG canvas in HTML5). Ideal for flyers, forms, annotated PDFs, and presentation slides.
  - **Flow Mode (`--mode flow`)**: Semantic reflowable document reconstruction. Automatically detects headings (`H1`–`H6`), bullet/numbered lists, tables, and reflowable paragraphs.
- **Native Vector Graphics & DrawingML Engine**:
  - High-precision PDF vector path parser decomposing cubic Bézier curves, subpaths, line caps, line joins, miter limits, and dash patterns.
  - Generates native OpenXML DrawingML custom geometries (`<a:custGeom>`) in DOCX and PPTX, native ODF `<draw:path>` in ODT/ODP, and standalone scalable vector graphics (`.svg`).
- **Single-File HTML5**:
  - Semantic reflowable output (`<article>`, `<header>`, `<footer>`, `<table class="pure-table">`, `<ul class="flow-list">`) and pixel-accurate canvas (`position: absolute`, inline `<svg>`, affine matrix transforms).
  - Truly portable single-file packaging with Base64 Data URI image embedding and zero-telemetry offline Content-Security-Policy (`<meta http-equiv="Content-Security-Policy">`).
- **Markdown / GFM & Static Site Ready Output**:
  - Configurable CommonMark and GitHub Flavored Markdown (GFM) dialects with ATX headings, 2D aligned pipe tables (`col_span`/`row_span`, `<br>` multi-line escaping, auto-detected column alignments), fenced code blocks with language hints, and extended GFM task checklists.
  - Pure-Python YAML frontmatter extracted from PDF `/Info` metadata (`title`, `author`, `description`, `keywords`, `date`) for Hugo, Jekyll, Docusaurus, and VitePress.
  - Modular media extraction via `--extract-images [DIR]` writing embedded JPEG/PNG/WebP images to disk with relative Markdown links.
- **EPUB 3.3 E-Book Generation Engine**:
  - Standards-compliant OCF 3.3 container (`mimetype` uncompressed at byte offset 0, `META-INF/container.xml`, `OEBPS/` structure), OPF 3.0 `content.opf` manifest and spine with Dublin Core metadata, hierarchical H1–H3 `nav.xhtml` plus legacy DAISY `toc.ncx` fallback for Kindle/Kobo, and automatic chapter splitting at `H1` or page boundaries.
- **RTF 1.9.1 Rich Text Format Engine**:
  - Universal legacy word-processor compatibility (WordPad, LibreOffice, Microsoft Word, Apple TextEdit) with complete `\fonttbl`, `\colortbl`, and `\stylesheet` tables, multi-script Unicode/ANSI `\uN\'xx` encoding (Turkish, Cyrillic, Greek, Central European, Arabic, Hebrew, CJK), `col_span`/`row_span` tables (`\clvmgf`/`\clvmrg`), and inline PNG/JPEG `\pict` embedding.
- **Academic & Scientific Publishing (Typst & LaTeX + Math Heuristics)**:
  - Generates clean, compilable **Typst** (`.typ`) and **LaTeX** (`.tex`) source with page geometry, typography setup, nested lists, code blocks, native `#table(...)` / `booktabs` tables, and `--extract-images` project-relative figures.
  - Heuristic mathematical formula extraction detects explicit and geometric superscript/subscript baseline shifts and decodes `Symbol`, `CMSY`, `CMMI`, `CMEX`, `MSBM`, and Unicode Greek/math symbols into `$x^2$` / `$\alpha + \beta \le \gamma$` (LaTeX) and `$x^2$` / `$alpha + beta <= gamma$` (Typst).
- **Structured Data & Table Extraction (JSON AST, CSV, XLSX)**:
  - **JSON AST (`-f json`, `DocumentIR.to_json()`)**: Lossless, schema-validated RFC 8259 JSON AST containing page geometry, bounding boxes, fonts, RGBA/hex colors, text runs, nested tables, vector paths, and Base64 images for downstream AI/RAG pipelines.
  - **RFC 4180 CSV (`-f csv`) & Native XLSX (`-f xlsx`)**: 2D occupancy-grid `col_span`/`row_span` normalization, multi-page continuous table merging with repeated-header deduplication, and zero-dependency ISO/IEC 29500-2 SpreadsheetML `.xlsx` workbooks with shared strings, column widths, numeric typing, and `<mergeCell>` ranges.
  - **Targeted Table Tooling**: Extract specific tables via `--table-index N` or strip narrative prose/fallback sheets via `--export-tables-only`.
- **Terminal-Friendly Plaintext Canvas**:
  - 2D character grid renderer (`-f txt -m canvas`) with junction-merging Unicode box-drawing (`┌─┐│└─┘┬┴├┤┼`) for table grids, image frames, and vector lines.
- **Comprehensive PDF Coverage**:
  - Classic ASCII xref tables, xref streams (`/Type /XRef`), and object streams (`/Type /ObjStm`).
  - Standard PDF Security Revisions 2–6 (RC4 40–128 bit, AES-128, and AES-256 CBC).
  - Decompression filters (`FlateDecode` with PNG/TIFF predictors, `LZWDecode`, `ASCII85Decode`, `ASCIIHexDecode`, `RunLengthDecode`, `CCITTFaxDecode`, `JBIG2Decode`, `JPXDecode`).
  - Modern image support: In-memory PNG extraction (ISO/IEC 15948), JPEG, JPEG 2000, and native WebP (RIFF/VP8/VP8L/VP8X).
  - Full typography engine: Type 1, TrueType/OpenType SFNT tables, CFF/Type 2 CharStrings, CIDFonts, ToUnicode CMaps, Adobe Glyph List, and dynamic `/Differences` encodings.
- **Standards-Compliant Packaging**:
  - **OPC (ISO/IEC 29500-2)**: Generates valid WordprocessingML (`.docx`), PresentationML (`.pptx`), and SpreadsheetML (`.xlsx`) packages with complete `[Content_Types].xml` and `.rels` hierarchies.
  - **ODF (ISO/IEC 26300)**: Generates compliant OpenDocument Text (`.odt`) and Presentation (`.odp`) archives with uncompressed `mimetype` headers at byte offset 0.
  - **W3C SVG, HTML5 & EPUB 3.3**: Standards-compliant vector graphics, self-contained HTML5 reports, and validated EPUB 3.3 OCF digital books.

---

## Supported Format Matrix

| Target Format | Extension | Flow Mode | Canvas Mode | Container Standard |
| :--- | :--- | :--- | :--- | :--- |
| **Microsoft Word** | `.docx` | Semantic `<w:p>`, `<w:tbl>` | DrawingML `<wps:wsp>`, `<w:framePr>` | ISO/IEC 29500-2 (OPC) |
| **Microsoft PowerPoint** | `.pptx` | Reflowable slide text | Coordinate shapes & DrawingML `<a:custGeom>` | ISO/IEC 29500-2 (OPC) |
| **OpenDocument Text** | `.odt` | Semantic `<text:p>`, `<table:table>` | Positioned `<draw:frame>`, `<draw:path>` | ISO/IEC 26300 (ODF) |
| **OpenDocument Presentation** | `.odp` | Slide content boxes | Coordinate `<draw:frame>`, `<draw:path>` | ISO/IEC 26300 (ODF) |
| **Plaintext** | `.txt` | Clean reflowable text | Unicode box-drawing (`┌─┐│└─┘`) 2D character grid | UTF-8 Plaintext |
| **Markdown / GFM** | `.md` | GFM tables, code fences, task lists, YAML frontmatter, `--extract-images` | Reflowable GFM / CommonMark | CommonMark / GFM |
| **EPUB 3 E-Book** | `.epub` | Split XHTML chapters, `nav.xhtml` + `toc.ncx`, embedded CSS & images | Reflowable EPUB 3.3 | W3C EPUB 3.3 (OCF) |
| **Rich Text Format** | `.rtf` | Styled paragraphs, Unicode `\uN\'xx`, span tables, hex `\pict` images | Reflowable RTF 1.9.1 | Microsoft RTF 1.9.1 |
| **Typst** | `.typ` | `#set page/text`, `#table`, math heuristics, `--extract-images` | Reflowable Typst source | Typst Markup |
| **LaTeX** | `.tex` | `geometry`, `graphicx`, `booktabs`, `amsmath`, math heuristics | Reflowable LaTeX source | LaTeX2e / TeX Live |
| **JSON AST** | `.json` | Schema-validated AST with boxes, fonts, colors, tables, Base64 images | Canvas-mode AST coordinates | RFC 8259 JSON (Schema v1.0) |
| **CSV Tables** | `.csv` | Multi-page table merging, header dedup, `--table-index` | Extracted 2D table grids | RFC 4180 CSV |
| **Microsoft Excel** | `.xlsx` | Multi-sheet tables, shared strings, `<cols>`, `<mergeCell>` | Native SpreadsheetML workbook | ISO/IEC 29500-2 (OPC) |
| **Scalable Vector Graphics** | `.svg` | Vertically stacked vector view | Individual SVG vector pages with curves & text | W3C SVG 1.1 |
| **Standalone HTML5** | `.html` | Semantic `<article>`, `<p>`, `<table>` | Absolute coordinate `<div>` & `<svg>` canvas | W3C HTML5 (Offline Data URI) |

---

## Known Issues
- **Slide Orientation (ODP & PPTX)**:
  - If input PDF page aspect ratio is vertical/portrait, ODP and PPTX default slide dimensions currently scale to widescreen aspect ratios.

---

## Installation

Install from PyPI:

```bash
pip install anyconvert
```

Or install in editable development mode:

```bash
git clone https://github.com/word-sys/anyconvert.git
cd anyconvert
pip install -e .
```

---

## Command-Line Interface (CLI)

`anyconvert` provides a standalone command-line tool:

```bash
anyconvert [OPTIONS] INPUT_PDF
```

### Options

| Flag | Argument | Description | Default |
| :--- | :--- | :--- | :--- |
| `-f`, `--format` | `docx\|pptx\|odt\|odp\|txt\|svg\|html\|md\|epub\|rtf\|typst\|latex\|json\|csv\|xlsx` | Target document format | `docx` |
| `-o`, `--output` | `PATH` | Output destination file path | `{input_basename}.{ext}` |
| `-m`, `--mode` | `flow\|canvas` | Layout reconstruction mode (`canvas` for 1:1 visual match) | `flow` |
| `-p`, `--password` | `STRING` | Decryption password for encrypted PDFs | `""` |
| `--extract-images` | `[DIR]` | Extract embedded images to `DIR` (defaults to `images/`) and link in Markdown, Typst, and LaTeX | `None` |
| `--table-index` | `INDEX` | Extract only the N-th detected table (0-based index) | `None` |
| `--export-tables-only` | | Export only detected tables (omit non-table prose or fallback text sheets) | `False` |
| `-v`, `--verbose` | | Enable diagnostic logging | `False` |
| `--version` | | Print version and exit | |
| `-h`, `--help` | | Show help message and exit | |

### CLI Examples

**Export Document AST to Structured JSON (AI / RAG Pipelines):**
```bash
anyconvert report.pdf -f json -o ast.json
```

**Extract Tables from Financial Report to Native Excel (.xlsx) or CSV:**
```bash
anyconvert statement.pdf -f xlsx -o statement.xlsx --export-tables-only
anyconvert statement.pdf -f csv --table-index 0 -o table0.csv
```

**Convert Research Paper to Typst (with Extracted Figures & Math):**
```bash
anyconvert paper.pdf -f typst -o paper.typ --extract-images
```

**Convert Research Paper to Compilable LaTeX (`booktabs` + `amsmath`):**
```bash
anyconvert paper.pdf -f latex -o paper.tex --extract-images
```

**Convert PDF to Universal Rich Text Format (RTF 1.9.1):**
```bash
anyconvert contract.pdf -f rtf -o contract.rtf
```

**Convert PDF Book to EPUB 3.3 E-Book (with TOC & Chapters):**
```bash
anyconvert book.pdf -f epub -o book.epub
```

**Export Markdown with YAML Frontmatter & Extracted Images:**
```bash
anyconvert guide.pdf -f md -o guide.md --extract-images ./assets/
```

**Terminal Unicode Box-Drawing Canvas View:**
```bash
anyconvert invoice.pdf -f txt -m canvas -o invoice.txt
```

**Single-File Responsive Web Document (HTML5 Flow):**
```bash
anyconvert article.pdf -f html -m flow -o article.html
```

**1:1 Pixel-Accurate Offline Web Report (HTML5 Canvas):**
```bash
anyconvert flyer.pdf -f html -m canvas -o flyer.html
```

**Standalone Scalable Vector Graphics Page (SVG):**
```bash
anyconvert blueprint.pdf -f svg -o blueprint.svg
```

**1:1 Pixel-Accurate Visual Export (DOCX):**
```bash
anyconvert flyer.pdf -f docx -m canvas -o flyer.docx
```

**1:1 Pixel-Accurate Visual Export (ODT):**
```bash
anyconvert document.pdf -f odt -m canvas -o document.odt
```

**Semantic Reflowable Conversion for Editing (DOCX):**
```bash
anyconvert article.pdf -f docx -m flow -o article.docx
```

**Convert PDF Slides to PowerPoint with Vectors (PPTX):**
```bash
anyconvert presentation.pdf -f pptx -m canvas -o presentation.pptx
```

**Convert Encrypted / Password-Protected PDF:**
```bash
anyconvert secret.pdf -f docx -p "MyPassword123"
```

---

## Python API

### High-Level File Conversion (`convert`)

```python
from anyconvert import convert, ConversionMode

# Accurate visual export to Word or LibreOffice Writer
convert(
    input_path="input.pdf",
    output_format="docx",
    output_path="output.docx",
    mode=ConversionMode.CANVAS,  # or "canvas"
)

# Semantic reflowable export to OpenDocument Text
convert(
    input_path="input.pdf",
    output_format="odt",
    output_path="output.odt",
    mode=ConversionMode.FLOW,  # or "flow"
)

# Markdown export with extracted image assets
convert(
    input_path="guide.pdf",
    output_format="md",
    output_path="guide.md",
    extract_images="./assets",
)

# EPUB 3.3 e-book generation
convert(
    input_path="book.pdf",
    output_format="epub",
    output_path="book.epub",
)

# Academic Typst & LaTeX conversion with math heuristics and extracted figures
convert(
    input_path="paper.pdf",
    output_format="typst",
    output_path="paper.typ",
    extract_images=True,
)
convert(
    input_path="paper.pdf",
    output_format="latex",
    output_path="paper.tex",
    extract_images=True,
)

# Rich Text Format (RTF 1.9.1) export
convert(
    input_path="contract.pdf",
    output_format="rtf",
    output_path="contract.rtf",
)

# Structured data & table export (JSON AST, CSV, native XLSX)
convert(
    input_path="report.pdf",
    output_format="json",
    output_path="ast.json",
)
convert(
    input_path="statement.pdf",
    output_format="xlsx",
    output_path="statement.xlsx",
    export_tables_only=True,
)
convert(
    input_path="statement.pdf",
    output_format="csv",
    output_path="table0.csv",
    table_index=0,
)
```

### In-Memory Byte Conversion (`convert_bytes`)

Ideal for web APIs, AWS Lambda, Cloud Run, and microservices:

```python
from anyconvert import convert_bytes

pdf_bytes = open("document.pdf", "rb").read()

# Convert in-memory without touching disk
docx_bytes = convert_bytes(
    pdf_bytes=pdf_bytes,
    output_format="docx",
    mode="canvas",
)
```

### Document Intermediate Representation (`pdf_to_document_ir`)

Inspect and manipulate document AST nodes before emitting:

```python
from anyconvert import pdf_to_document_ir

doc_ir = pdf_to_document_ir("document.pdf", mode="canvas")

print(f"Total Pages: {len(doc_ir.pages)}")
print(f"Metadata: {doc_ir.metadata}")

for page in doc_ir.pages:
    print(f"Page {page.page_number} ({page.width}x{page.height} pt): {len(page.blocks)} blocks")

# Serialize DocumentIR to schema-validated JSON AST and round-trip back
ast_json = doc_ir.to_json(indent=2)
restored = doc_ir.from_json(ast_json)
```

---

## Architecture

```
[ Raw PDF Bytes / Stream ]
            │
            ▼
[ PDF Lexer & Parser ] ───► [ XRef Resolver & ObjStm Unpacker ]
                                    │
   ┌────────────────────────────────┼────────────────────────────────┐
   ▼                                ▼                                ▼
[ Decryption Engine ]    [ Decompression Filters ]        [ Typography Engine ]
(RC4 / AES-128 / AES-256) (Flate/LZW/ASCII85/PackBits)  (SFNT / CFF / Type 1 / CMap)
   │                                │                                │
   └────────────────────────────────┼────────────────────────────────┘
                                    │
                                    ▼
                    [ Content Stream Interpreter ]
                      (Graphics & Text Evaluator)
                                    │
                                    ▼
                 [ Spatial Indexing & Recursive XY-Cut ]
                                    │
                                    ▼
                      [ Semantic Feature Detectors ]
                     (Headings / Lists / Tables / Flow)
                                    │
                                    ▼
                         [ DocumentIR Builder ]
                                    │
       ┌─────────────────┬──────────┴───────┬──────────────┬─────────────────┬──────────────────┬──────────────────┐
       ▼                 ▼                  ▼              ▼                 ▼                  ▼
[ DOCX / PPTX ]   [ ODT / ODP ]      [ TXT / MD ]   [ HTML5 / SVG / ]  [ RTF 1.9.1 /    ]  [ JSON AST /      ]
  (DrawingML)     (ISO/IEC 26300)    (Canvas / GFM) [   EPUB 3      ]  [ Typst / LaTeX  ]  [ CSV / XLSX      ]
                                                    (W3C Web / OCF)    (Academic & Math)   (Data & Tables)
```

---

## Development & Verification

### Running Tests

```bash
python3 -m pytest tests/
```

### Static Type Checking

The codebase enforces 100% strict type safety (`mypy --strict`):

```bash
python3 -m mypy --strict src/ tests/
```

---

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for details on our architectural principles, development setup, code of conduct, and pull request guidelines.

---

## License

GPL-3.0-or-later. See [LICENSE](LICENSE) for details.
