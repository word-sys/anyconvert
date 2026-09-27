# Contributing to AnyConvert

Thank you for your interest in contributing to **anyconvert**! We welcome contributions from the community, whether you're reporting a bug, proposing new features, improving documentation, or submitting code changes.

Please take a few moments to review these guidelines before getting started.

---

## Code of Conduct

This project and everyone participating in it is governed by our [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code. Please report unacceptable behavior following the enforcement guidelines in that document.

---

## Core Architectural Principles

When writing or modifying code in `anyconvert`, keep the following non-negotiable architectural tenets in mind:

1. **Zero External Runtime Dependencies**:
   - The runtime package MUST rely solely on the Python Standard Library.
   - Do NOT add third-party packages to `dependencies` in `pyproject.toml` (e.g., no `Pillow`, `pdf2docx`, `pypdf`, `reportlab`, or `numpy`).
   - All compression/decompression, cryptography, binary parsing, image handling, and container packaging (OPC, ODF) must remain pure-Python standard library implementations.

2. **100% Strict Type Safety**:
   - The entire codebase is strictly typed (`mypy --strict`).
   - Every function, method, parameter, and return value must have explicit type annotations.
   - Do not use `# type: ignore` unless strictly required for edge cases, and always include a comment explaining why.

3. **Dual-Mode Layout Philosophy**:
   - Features should support or correctly interact with both **Canvas Mode** (1:1 spatial positioning and vector preservation) and **Flow Mode** (semantic reflowable document reconstruction).

4. **Comprehensive Test Coverage**:
   - Every bug fix or new feature must come with unit and/or integration tests under `tests/`.
   - All tests must pass before opening a Pull Request.

---

## Development Setup

### Prerequisites

- Python 3.10, 3.11, 3.12, 3.13, 3.14
- Git

### Getting the Code

1. Fork the repository on GitHub: [https://github.com/word-sys/anyconvert](https://github.com/word-sys/anyconvert)
2. Clone your fork locally:
   ```bash
   git clone https://github.com/<your-username>/anyconvert.git
   cd anyconvert
   ```
3. Add the upstream repository as a remote:
   ```bash
   git remote add upstream https://github.com/word-sys/anyconvert.git
   ```

### Creating a Virtual Environment

It is recommended to use a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Installing Development Dependencies

Install the project in editable mode along with testing and type-checking tools:

```bash
pip install --upgrade pip
pip install -e .
pip install pytest mypy build twine
```

---

## Codebase Architecture

Here is a quick overview of the directory structure to help you navigate:

```text
src/anyconvert/
├── api.py                  # High-level Python API (convert, convert_bytes, pdf_to_document_ir)
├── cli.py                  # Standalone CLI entry point
├── common/                 # Core geometry primitives, colors, and binary stream readers
│   ├── geometry.py         # BoundingBox, Point
│   ├── color.py            # RGB/RGBA color models
│   └── reader.py           # ByteReader for zero-copy memory/file streams
├── pdf/                    # Low-level PDF parser & interpreter
│   ├── parser.py           # Lexer, token stream, COS object models
│   ├── xref.py             # ASCII xref tables, xref streams, object streams (ObjStm)
│   ├── filters/            # FlateDecode (PNG/TIFF predictors), LZW, ASCII85, etc.
│   ├── crypto/             # Standard PDF Security Handler (RC4, AES-128, AES-256)
│   ├── typography/         # TrueType/OpenType SFNT, CFF/Type 2, Type 1, CMaps, encodings
│   └── content/            # PDF content stream evaluator & graphics state machine
├── layout/                 # Layout analysis & semantic structure detection
│   ├── cluster.py          # Character-to-word & word-to-line clustering
│   ├── xycut.py            # Recursive XY-cut spatial reading-order tree
│   ├── table.py            # Bordered & borderless table detection
│   └── semantic.py         # Heading classification & list detection
├── ir/                     # Document Intermediate Representation (DIR)
│   ├── model.py            # DocumentIR, DocumentPage, Paragraph, Table, ImageBlock, VectorBlock
│   ├── builder.py          # Synthesizes layout elements into validated DocumentIR
│   └── validator.py        # Strict AST invariant validation
├── packaging/              # Archive builders conforming to ISO standards
│   ├── opc.py              # ISO/IEC 29500-2 Open Packaging Conventions (DOCX, PPTX)
│   └── odf.py              # ISO/IEC 26300 OpenDocument Format (ODT, ODP)
└── emitters/               # Target format serialization engines
    ├── docx/               # WordprocessingML & DrawingML emitter
    ├── pptx/               # PresentationML emitter
    ├── odt/                # OpenDocument Text emitter
    ├── odp/                # OpenDocument Presentation emitter
    └── txt/                # Markdown / Plaintext emitter
```

---

## Development Workflow

### Creating a Branch

Always create a dedicated feature or bugfix branch from the latest `main`:

```bash
git checkout main
git pull upstream main
git checkout -b feature/your-feature-name
# or: git checkout -b fix/issue-description
```

### Running the Test Suite

Run the full test suite with `pytest`:

```bash
python3 -m pytest tests/
```

To run a specific test file or test case:

```bash
python3 -m pytest tests/test_emitters_docx_pptx.py -k "test_docx"
```

### Running Static Type Checking

Ensure 100% strict type safety compliance across all source files and tests:

```bash
python3 -m mypy --strict src/ tests/
```

Your contribution will not be merged if `mypy --strict` fails.

---

## Coding Standards

- **PEP 8 Compliance**: Follow standard Python styling conventions (4 spaces indentation, 100-character line limit where sensible).
- **Docstrings & Comments**: Add descriptive docstrings to all public functions, classes, and methods conforming to the Google or Sphinx docstring style.
- **Error Handling**: Use custom exceptions defined in `anyconvert.exceptions` (e.g., `PDFParseError`, `DecryptionError`, `SerializationError`) rather than bare `Exception`.
- **Determinism**: Avoid non-deterministic behavior (e.g. iterating over un-sorted dictionaries or sets when building binary packages).

---

## Submitting a Pull Request

1. **Commit your changes**:
   Write clear, concise commit messages summarizing what changed and why:
   ```bash
   git add <modified-files>
   git commit -m "Fix gutter bridging in two-column line clustering"
   ```

2. **Push to your fork**:
   ```bash
   git push origin feature/your-feature-name
   ```

3. **Open a Pull Request**:
   - Go to [https://github.com/word-sys/anyconvert](https://github.com/word-sys/anyconvert) and click **New Pull Request**.
   - Select your fork and branch.
   - Provide a clear PR title and description:
     - Explain the problem you are solving.
     - Describe the changes made.
     - Reference any associated issue (e.g., `Fixes #12`).
     - Mention test coverage and verification results.

---

## Questions or Need Help?

If you have questions or encounter any issues, feel free to open a [GitHub Issue](https://github.com/word-sys/anyconvert/issues) or start a discussion. We are excited to collaborate with you!
