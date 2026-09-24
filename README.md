# anyconvert

**Python document conversion engine**

`anyconvert` converts PDF documents into **DOCX**, **PPTX**, **ODT**, **ODP**, and **TXT** with mathematical precision, standards-compliant container packaging, and dual-mode layout reconstruction (Semantic Flow vs. Spatial Canvas).

---

## Key Capabilities

- **Dual Layout Engines**:
  - **Flow Mode** (`flow`): Reconstructs semantic reading order, headings (`H1`–`H6`), hierarchical lists, text alignment, reflowable paragraphs, and tables.
  - **Canvas Mode** (`canvas`): Preserves exact 2D coordinates using DrawingML shapes, anchored frames, and absolute-positioned text frames.
- **Full PDF Feature Coverage**:
  - Classic ASCII xref tables, xref streams (`/Type /XRef`), and compressed object streams (`/Type /ObjStm`).
  - Standard PDF Security Revisions 2–6 (RC4 40–128 bit, AES-128, and AES-256 CBC).
  - Decompression filter pipeline (`FlateDecode` with TIFF/PNG predictors, `LZWDecode`, `ASCII85Decode`, `ASCIIHexDecode`, `RunLengthDecode`).
  - Typography engine (Type 1, TrueType/OpenType SFNT tables, CFF/Type 2 CharStrings, CIDFonts, ToUnicode CMaps, Adobe Glyph List, and dynamic `/Differences` encodings).
  - Vector graphics rasterization & SVG path extraction.
  - In-memory PNG serializer (ISO/IEC 15948).
- **Standards-Compliant Packaging**:
  - **OPC (ISO/IEC 29500-2)**: Builds compliant ZIP archives with `[Content_Types].xml` and `.rels` hierarchies for DOCX and PPTX.
  - **ODF (ISO/IEC 26300)**: Enforces uncompressed `mimetype` at byte offset 0 with `META-INF/manifest.xml` for ODT and ODP.

---

## Supported Format Matrix

| Target Format | Extension | Flow Mode | Canvas Mode | Container Standard |
| :--- | :--- | :--- | :--- | :--- |
| **Microsoft Word** | `.docx` | Semantic `<w:p>`, `<w:tbl>` | Anchored `<wp:anchor>` | ISO/IEC 29500-2 (OPC) |
| **Microsoft PowerPoint** | `.pptx` | Reflowable slide text | Exact EMU coordinates | ISO/IEC 29500-2 (OPC) |
| **OpenDocument Text** | `.odt` | Semantic `<text:p>`, `<table:table>` | Positioned `<draw:frame>` | ISO/IEC 26300 (ODF) |
| **OpenDocument Presentation** | `.odp` | Slide content boxes | Coordinate `<draw:frame>` | ISO/IEC 26300 (ODF) |
| **Plaintext / Markdown** | `.txt` | Formatted Markdown text | 2D character-grid matrix | UTF-8 Plaintext |

---

## Installation

```bash
pip install anyconvert
```

Or install locally in editable mode:

```bash
git clone https://github.com/word-sys/anyconvert.git
cd anyconvert
pip install -e .
```

---

## Command-Line Interface (CLI)

`anyconvert` installs a standalone executable entrypoint:

```bash
anyconvert [OPTIONS] INPUT_PDF
```

### Options

| Flag | Argument | Description | Default |
| :--- | :--- | :--- | :--- |
| `-f`, `--format` | `docx\|pptx\|odt\|odp\|txt` | Target document format | `docx` |
| `-o`, `--output` | `PATH` | Output destination file path | `{input_basename}.{format}` |
| `-m`, `--mode` | `flow\|canvas` | Layout reconstruction mode | `flow` |
| `-p`, `--password` | `STRING` | Decryption password for encrypted PDFs | `""` |
| `-v`, `--verbose` | | Enable diagnostic logging | `False` |
| `--version` | | Print program version and exit | |
| `-h`, `--help` | | Show help message and exit | |

### CLI Examples

**Convert PDF to Word document (DOCX):**
```bash
anyconvert report.pdf -f docx
# Outputs: report.docx
```

**Convert PDF to PowerPoint presentation (PPTX) preserving exact coordinates:**
```bash
anyconvert slides.pdf -f pptx -m canvas -o presentation.pptx
```

**Convert PDF to OpenDocument Text (ODT):**
```bash
anyconvert article.pdf -f odt
```

**Convert PDF to structured Markdown / Plaintext:**
```bash
anyconvert document.pdf -f txt -m flow
```

**Convert a password-protected PDF:**
```bash
anyconvert confidential.pdf -f docx -p "MySecretPassword"
```

---

## Python API

### High-Level File Conversion (`convert`)

```python
from anyconvert import convert, ConversionMode

# Convert file on disk and save output
docx_bytes = convert(
    input_path="document.pdf",
    output_format="docx",
    output_path="document.docx",
    mode=ConversionMode.FLOW,
)

# Convert with Canvas mode (exact 2D positioning)
pptx_bytes = convert(
    input_path="slides.pdf",
    output_format="pptx",
    output_path="slides.pptx",
    mode=ConversionMode.CANVAS,
)
```

### In-Memory Byte Conversion (`convert_bytes`)

Ideal for serverless functions, microservices, and web backends:

```python
from anyconvert import convert_bytes

pdf_data = b"%PDF-1.4..."  # Raw PDF bytes

# Convert directly in memory without writing to disk
docx_data = convert_bytes(
    pdf_bytes=pdf_data,
    output_format="docx",
    mode="flow",
)

# Convert to Markdown text
markdown_bytes = convert_bytes(
    pdf_bytes=pdf_data,
    output_format="txt",
    mode="flow",
)
print(markdown_bytes.decode("utf-8"))
```

### Document Intermediate Representation (`pdf_to_document_ir`)

Inspect or manipulate document layout elements before serialization:

```python
from anyconvert import pdf_to_document_ir

doc_ir = pdf_to_document_ir("document.pdf")

print(f"Total pages: {len(doc_ir.pages)}")
print(f"Metadata: {doc_ir.metadata}")

for page in doc_ir.pages:
    print(f"Page {page.page_number} ({page.width}x{page.height} pt):")
    for block in page.blocks:
        print(f"  Block: {type(block).__name__}")
```

---

## Architecture

```
[ Raw PDF Bytes ]
       │
       ▼
 [ PDF Lexer & Parser ] ───► [ XRef Resolver & ObjStm Unpacker ]
                                     │
   ┌─────────────────────────────────┼────────────────────────────────┐
   ▼                                 ▼                                ▼
[ Decryption Engine ]    [ Decompression Filters ]         [ Typography & Fonts ]
(RC4 / AES-128 / AES-256) (Flate/LZW/ASCII85/PackBits)   (SFNT / CFF / Type 1 / CMap)
   │                                 │                                │
   └─────────────────────────────────┼────────────────────────────────┘
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
       ┌─────────────────────────────┼─────────────────────────────┐
       ▼                             ▼                             ▼
[ DOCX Emitter ]              [ PPTX Emitter ]              [ ODT / ODP / TXT ]
  (ISO/IEC 29500)               (DrawingML)                  (ISO/IEC 26300)
```

---

## Development & Verification

### Running the Test Suite

```bash
python3 -m pytest tests/
# 225 passed in <1s
```

### Static Type Checking

The codebase enforces strict type safety:

```bash
python3 -m mypy --strict src/ tests/
# Success: no issues found in 93 source files
```

### Building Distribution Packages

```bash
python3 -m flit_core.wheel
# Builds dist/anyconvert-0.1.0-py3-none-any.whl
```

---

## License

GPL-3.0-or-later. See [LICENSE](LICENSE) for details.
