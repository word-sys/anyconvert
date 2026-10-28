# Security Policy

## Supported Versions

Security updates are applied to the latest active minor/patch release track and the `main` development branch. Older releases do not receive backported security patches; users are encouraged to upgrade to the latest release on PyPI.

| Version | Supported |
| ------- | --------- |
| 0.1.x (latest) | Yes |
| < 0.1.9 | No |

## Security Scope

`anyconvert` is a 100% pure-Python document conversion engine with zero external runtime dependencies. We treat the following categories as security-relevant vulnerabilities:

- **Archive & Packaging Traversal (Zip Slip):** Path traversal or arbitrary file overwrite vulnerabilities during OPC (`.docx`, `.pptx`, `.xlsx`), ODF (`.odt`, `.odp`), or EPUB container parsing and generation.
- **XML & Markup Injection:** XML External Entity (XXE) processing, entity expansion bombs (Billion Laughs), or malformed namespace injection in document parsers and emitters.
- **Resource Exhaustion & Denial of Service (DoS):** Infinite loops in the PDF lexer/parser, cyclic cross-reference (`xref`) tables, decompression bombs in stream filters (`FlateDecode`, `LZWDecode`, `CCITTFaxDecode`), or unbounded memory allocation on malformed inputs.
- **Cryptographic & Security Handler Flaws:** Weaknesses or bypasses in the PDF security handler implementations (RC4, AES-128, AES-256).

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues, discussions, or pull requests.**

Instead, please report them privately using GitHub's built-in security advisory system:

1. Navigate to the **Security** tab of the repository: `https://github.com/word-sys/anyconvert/security`
2. Click **Report a vulnerability** (`https://github.com/word-sys/anyconvert/security/advisories/new`) to open a private advisory draft.

### What to Include in Your Report

To help us triage and resolve the issue quickly, please include:

- The exact version of `anyconvert` and Python version (`3.10`–`3.14`) used.
- A minimal reproducible test case, sample document (or byte stream), and the exact CLI command or Python API call that triggers the issue.
- A clear explanation of the potential impact (e.g., unhandled memory exhaustion, arbitrary file write, infinite loop).

### Response & Disclosure Timeline

- **Initial Acknowledgment:** Within **48 hours** of submission.
- **Triage & Assessment:** Within **5 business days**, we will confirm whether the report is accepted or declined and determine its severity.
- **Resolution & Release:** For accepted vulnerabilities, we aim to develop a fix, add automated regression tests, and publish a patched release to PyPI within **7 to 14 days**.
- **Coordinated Disclosure:** Once the patched version is live on PyPI, the security advisory will be published and full credit will be given to the reporter (unless anonymity is requested).
