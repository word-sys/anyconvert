# anyconvert

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/license-GPLv3+-blue.svg)](LICENSE)
[![Downloads](https://img.shields.io/pepy/dt/anyconvert)](https://pepy.tech/projects/anyconvert)

**Python document conversion engine**

`anyconvert` converts PDF documents into **DOCX**, **PPTX**, **ODT**, **ODP**, **TXT**, **SVG**, and **HTML5** using only the Python standard library.

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
- **Comprehensive PDF Coverage**:
  - Classic ASCII xref tables, xref streams (`/Type /XRef`), and object streams (`/Type /ObjStm`).
  - Standard PDF Security Revisions 2–6 (RC4 40–128 bit, AES-128, and AES-256 CBC).
  - Decompression filters (`FlateDecode` with PNG/TIFF predictors, `LZWDecode`, `ASCII85Decode`, `ASCIIHexDecode`, `RunLengthDecode`, `CCITTFaxDecode`, `JBIG2Decode`, `JPXDecode`).
  - Modern image support: In-memory PNG extraction (ISO/IEC 15948), JPEG, JPEG 2000, and native WebP (RIFF/VP8/VP8L/VP8X).
  - Full typography engine: Type 1, TrueType/OpenType SFNT tables, CFF/Type 2 CharStrings, CIDFonts, ToUnicode CMaps, Adobe Glyph List, and dynamic `/Differences` encodings.
- **Standards-Compliant Packaging**:
  - **OPC (ISO/IEC 29500-2)**: Generates valid WordprocessingML (`.docx`) and PresentationML (`.pptx`) packages with complete `[Content_Types].xml` and `.rels` hierarchies.
  - **ODF (ISO/IEC 26300)**: Generates compliant OpenDocument Text (`.odt`) and Presentation (`.odp`) archives with uncompressed `mimetype` headers at byte offset 0.
  - **W3C SVG & HTML5**: Standards-compliant vector graphics and self-contained HTML5 reports.

---

## Supported Format Matrix

| Target Format | Extension | Flow Mode | Canvas Mode | Container Standard |
| :--- | :--- | :--- | :--- | :--- |
| **Microsoft Word** | `.docx` | Semantic `<w:p>`, `<w:tbl>` | DrawingML `<wps:wsp>`, `<w:framePr>` | ISO/IEC 29500-2 (OPC) |
| **Microsoft PowerPoint** | `.pptx` | Reflowable slide text | Coordinate shapes & DrawingML `<a:custGeom>` | ISO/IEC 29500-2 (OPC) |
| **OpenDocument Text** | `.odt` | Semantic `<text:p>`, `<table:table>` | Positioned `<draw:frame>`, `<draw:path>` | ISO/IEC 26300 (ODF) |
| **OpenDocument Presentation** | `.odp` | Slide content boxes | Coordinate `<draw:frame>`, `<draw:path>` | ISO/IEC 26300 (ODF) |
| **Plaintext / Markdown** | `.txt` | Formatted Markdown text | 2D character-grid layout | UTF-8 Plaintext |
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
| `-f`, `--format` | `docx\|pptx\|odt\|odp\|txt\|svg\|html` | Target document format | `docx` |
| `-o`, `--output` | `PATH` | Output destination file path | `{input_basename}.{format}` |
| `-m`, `--mode` | `flow\|canvas` | Layout reconstruction mode (`canvas` for 1:1 visual match) | `flow` |
| `-p`, `--password` | `STRING` | Decryption password for encrypted PDFs | `""` |
| `-v`, `--verbose` | | Enable diagnostic logging | `False` |
| `--version` | | Print version and exit | |
| `-h`, `--help` | | Show help message and exit | |

### CLI Examples

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
       ┌─────────────────────┬──────┴──────────────┬─────────────────────┐
       ▼                     ▼                     ▼                     ▼
[ DOCX Emitter ]      [ PPTX Emitter ]      [ ODT / ODP / TXT ]   [ HTML5 / SVG ]
  (DrawingML)           (DrawingML)           (ISO/IEC 26300)      (Flow & Canvas)
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
