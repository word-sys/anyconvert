"""CSS stylesheets and variable definitions for HTML5 document generation.

Supports modern CSS variables, responsive flow typography, pixel-accurate canvas
layers, and standard media print styles.
"""

from __future__ import annotations

from anyconvert.emitters.base import ConversionMode

CORE_CSS_VARIABLES = """
:root {
  --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  --font-serif: "Georgia", "Times New Roman", serif;
  --font-mono: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, Courier, monospace;
  --color-bg: #ffffff;
  --color-canvas-bg: #f3f4f6;
  --color-text: #111827;
  --color-muted: #6b7280;
  --color-border: #e5e7eb;
  --color-table-stripe: #f9fafb;
}
"""

BASE_RESET_CSS = """
* {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

body {
  background-color: var(--color-canvas-bg);
  color: var(--color-text);
  font-family: var(--font-sans);
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}
"""

FLOW_MODE_CSS = """
.document-flow {
  max-width: 840px;
  margin: 32px auto;
  background-color: var(--color-bg);
  padding: 48px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  border-radius: 6px;
}

.document-flow header {
  border-bottom: 1px solid var(--color-border);
  padding-bottom: 16px;
  margin-bottom: 24px;
}

.document-flow footer {
  border-top: 1px solid var(--color-border);
  padding-top: 16px;
  margin-top: 32px;
  color: var(--color-muted);
  font-size: 0.875rem;
}

.document-flow article {
  margin-bottom: 24px;
}

.document-flow h1,
.document-flow h2,
.document-flow h3,
.document-flow h4,
.document-flow h5,
.document-flow h6 {
  color: #111827;
  margin-top: 1.4em;
  margin-bottom: 0.5em;
  font-weight: 600;
  line-height: 1.25;
}

.document-flow h1 { font-size: 2rem; }
.document-flow h2 { font-size: 1.5rem; }
.document-flow h3 { font-size: 1.25rem; }
.document-flow h4 { font-size: 1.125rem; }
.document-flow h5 { font-size: 1rem; }
.document-flow h6 { font-size: 0.875rem; color: var(--color-muted); }

.document-flow p {
  margin-bottom: 1em;
}

.document-flow ul,
.document-flow ol {
  margin-left: 1.5em;
  margin-bottom: 1em;
}

.document-flow table.pure-table {
  width: 100%;
  border-collapse: collapse;
  margin: 1.5em 0;
  font-size: 0.9375rem;
}

.document-flow table.pure-table th,
.document-flow table.pure-table td {
  padding: 8px 12px;
  border: 1px solid var(--color-border);
  text-align: left;
}

.document-flow table.pure-table th {
  background-color: var(--color-table-stripe);
  font-weight: 600;
}

.document-flow table.pure-table tr:nth-child(even) td {
  background-color: var(--color-table-stripe);
}

.document-flow img {
  max-width: 100%;
  height: auto;
  display: block;
  margin: 1.5em auto;
}

.document-flow svg {
  max-width: 100%;
  height: auto;
  display: block;
  margin: 1.5em auto;
}
"""

CANVAS_MODE_CSS = """
.canvas-wrapper {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 32px 0;
  gap: 24px;
}

.canvas-page {
  position: relative;
  background-color: var(--color-bg);
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.12);
  overflow: hidden;
}

.canvas-element {
  position: absolute;
  box-sizing: border-box;
}

.canvas-text {
  position: absolute;
  white-space: pre;
  line-height: 1.0;
  transform-origin: 0 0;
}

.canvas-image {
  position: absolute;
  display: block;
}

.canvas-vector {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}
"""

PRINT_MEDIA_CSS = """
@media print {
  body {
    background-color: transparent;
  }
  .document-flow {
    max-width: 100%;
    margin: 0;
    padding: 0;
    box-shadow: none;
    border-radius: 0;
  }
  .canvas-wrapper {
    padding: 0;
    gap: 0;
  }
  .canvas-page {
    margin: 0;
    box-shadow: none;
    page-break-after: always;
    page-break-inside: avoid;
  }
}
"""


def build_default_css(
    mode: ConversionMode = ConversionMode.FLOW,
    include_print: bool = True,
) -> str:
    """Compose the complete CSS stylesheet for the specified HTML conversion mode.

    Args:
        mode: Layout conversion mode (FLOW or CANVAS).
        include_print: If True, appends responsive print stylesheet.

    Returns:
        CSS stylesheet string.
    """
    parts = [
        CORE_CSS_VARIABLES.strip(),
        BASE_RESET_CSS.strip(),
    ]
    if mode == ConversionMode.FLOW:
        parts.append(FLOW_MODE_CSS.strip())
    else:
        parts.append(CANVAS_MODE_CSS.strip())

    if include_print:
        parts.append(PRINT_MEDIA_CSS.strip())

    return "\n\n".join(parts)


__all__ = [
    "build_default_css",
    "CORE_CSS_VARIABLES",
    "BASE_RESET_CSS",
    "FLOW_MODE_CSS",
    "CANVAS_MODE_CSS",
    "PRINT_MEDIA_CSS",
]
