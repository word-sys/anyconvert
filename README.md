# anyconvert

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/license-GPLv3+-blue.svg)](LICENSE)
[![Downloads](https://static.pepy.tech/badge/anyconvert)](https://pepy.tech/projects/anyconvert)

**Python document conversion engine**

`anyconvert` converts PDF documents into **DOCX**, **PPTX**, **ODT**, **ODP**, and **TXT** using only the Python standard library.

---

## Highlights

- **Dual Layout Engines**:
  - **Canvas Mode (`--mode canvas`)**: 1:1 pixel-accurate positioning. Renders exact coordinates, font families, embedded images, and vector artwork (native DrawingML custom geometries in DOCX, SVG paths in ODT). Ideal for flyers, forms, annotated PDFs, and presentation slides.
  - **Flow Mode (`--mode flow`)**: Semantic reflowable document reconstruction. Automatically detects headings (`H1`–`H6`), bullet/numbered lists, tables, and reflowable paragraphs.
- **Comprehensive PDF Coverage**:
  - Classic ASCII xref tables, xref streams (`/Type /XRef`), and object streams (`/Type /ObjStm`).
  - Standard PDF Security Revisions 2–6 (RC4 40–128 bit, AES-128, and AES-256 CBC).
  - Decompression filters (`FlateDecode` with PNG/TIFF predictors, `LZWDecode`, `ASCII85Decode`, `ASCIIHexDecode`, `RunLengthDecode`).
  - Full typography engine: Type 1, TrueType/OpenType SFNT tables, CFF/Type 2 CharStrings, CIDFonts, ToUnicode CMaps, Adobe Glyph List, and dynamic `/Differences` encodings.
  - In-memory PNG raster extraction and serializer (ISO/IEC 15948).
- **Standards-Compliant Packaging**:
  - **OPC (ISO/IEC 29500-2)**: Generates valid WordprocessingML (`.docx`) and PresentationML (`.pptx`) packages with complete `[Content_Types].xml` and `.rels` hierarchies.
  - **ODF (ISO/IEC 26300)**: Generates compliant OpenDocument Text (`.odt`) and Presentation (`.odp`) archives with uncompressed `mimetype` headers at byte offset 0.

---

## Supported Format Matrix

| Target Format | Extension | Flow Mode | Canvas Mode | Container Standard |
| :--- | :--- | :--- | :--- | :--- |
| **Microsoft Word** | `.docx` | Semantic `<w:p>`, `<w:tbl>` | DrawingML `<wps:wsp>`, `<w:framePr>` | ISO/IEC 29500-2 (OPC) |
| **Microsoft PowerPoint** | `.pptx` | Reflowable slide text | Exact coordinate shapes & text | ISO/IEC 29500-2 (OPC) |
| **OpenDocument Text** | `.odt` | Semantic `<text:p>`, `<table:table>` | Positioned `<draw:frame>`, `<draw:path>` | ISO/IEC 26300 (ODF) |
| **OpenDocument Presentation** | `.odp` | Slide content boxes | Coordinate `<draw:frame>` | ISO/IEC 26300 (ODF) |
| **Plaintext / Markdown** | `.txt` | Formatted Markdown text | 2D character-grid layout | UTF-8 Plaintext |

---

## Known Issues
- **ODT & PPTX Export Issues**:
  - **PDF Original Position**: If PDF itself is vertical, ODP & PPTX export will be broken due to horizontal size of slides.
  - **Known Bug**: Shapes or pen markups aren't supported, it will not shown on your presentation.
  - **Beta Stage**: Project now at v0.1.0 Beta stage, only DOCX and ODT seems to be fully function as wanted.
  - **Design Flaw**: Project designed to be a PDF to XXX document convert library for [word-sys's PDF Editor](https://github.com/word-sys/word-sys-pdf-editor) and mainly designed for DOCX & ODT export, expecting a fully 1:1 export to PPTX & ODP is not possible, for now.

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
| `-f`, `--format` | `docx\|pptx\|odt\|odp\|txt` | Target document format | `docx` |
| `-o`, `--output` | `PATH` | Output destination file path | `{input_basename}.{format}` |
| `-m`, `--mode` | `flow\|canvas` | Layout reconstruction mode (`canvas` for 1:1 visual match) | `flow` |
| `-p`, `--password` | `STRING` | Decryption password for encrypted PDFs | `""` |
| `-v`, `--verbose` | | Enable diagnostic logging | `False` |
| `--version` | | Print version and exit | |
| `-h`, `--help` | | Show help message and exit | |

### CLI Examples

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

**Convert PDF Slides to PowerPoint (PPTX):**
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
       ┌────────────────────────────┼────────────────────────────┐
       ▼                            ▼                            ▼
[ DOCX Emitter ]             [ PPTX Emitter ]             [ ODT / ODP / TXT ]
  (DrawingML)                  (DrawingML)                  (ISO/IEC 26300)
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

## License

GPL-3.0-or-later. See [LICENSE](LICENSE) for details.
