"""YAML frontmatter generator for Markdown static site generators.

Maps PDF /Info metadata dictionaries (Title, Author, Subject, Keywords,
CreationDate, ModDate, Creator, Producer) to standard YAML frontmatter
compatible with Hugo, Jekyll, Docusaurus, and VitePress.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Sequence, Tuple, Union

from anyconvert.pdf.document import parse_pdf_date

# Canonical mapping from lowercase PDF /Info keys to SSG YAML frontmatter keys
_CANONICAL_KEY_ORDER: Tuple[Tuple[str, str], ...] = (
    ("title", "title"),
    ("author", "author"),
    ("subject", "description"),
    ("description", "description"),
    ("keywords", "keywords"),
    ("tags", "keywords"),
    ("creationdate", "date"),
    ("date", "date"),
    ("moddate", "lastmod"),
    ("lastmod", "lastmod"),
    ("creator", "creator"),
    ("producer", "producer"),
)

_CANONICAL_KEY_MAP: Dict[str, str] = dict(_CANONICAL_KEY_ORDER)
_SAFE_KEY_RE = re.compile(r"[^a-zA-Z0-9_-]+")


def format_yaml_scalar(value: str) -> str:
    """Serialize a Python string into a safe double-quoted YAML scalar."""
    cleaned = "".join(
        ch for ch in value if ord(ch) >= 0x20 or ch in ("\t", "\n", "\r")
    )
    escaped = (
        cleaned.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\t", "\\t")
        .replace("\r", "\\r")
        .replace("\n", "\\n")
    )
    return f'"{escaped}"'


def parse_keywords(raw_keywords: Union[str, Sequence[str]]) -> List[str]:
    """Split comma- or semicolon-delimited keyword text into clean unique tokens."""
    items: List[str] = []
    if isinstance(raw_keywords, str):
        parts = re.split(r"[,;]+", raw_keywords)
        items = [p.strip() for p in parts if p.strip()]
    else:
        items = [str(p).strip() for p in raw_keywords if str(p).strip()]

    seen: set[str] = set()
    unique: List[str] = []
    for item in items:
        low = item.lower()
        if low not in seen:
            seen.add(low)
            unique.append(item)
    return unique


def _sanitize_custom_key(raw_key: str) -> str:
    """Normalize arbitrary metadata key names into valid YAML identifier keys."""
    clean = _SAFE_KEY_RE.sub("_", raw_key.lstrip("/")).strip("_").lower()
    return clean


def normalize_frontmatter_metadata(
    metadata: Mapping[str, Any],
) -> Dict[str, Union[str, List[str]]]:
    """Normalize raw DocumentIR metadata into ordered YAML frontmatter fields."""
    if not metadata:
        return {}

    raw_lower_map: Dict[str, Any] = {}
    extra_fields: Dict[str, str] = {}

    for k, v in metadata.items():
        if v is None:
            continue
        key_str = str(k).lstrip("/").strip()
        if not key_str:
            continue
        low_key = key_str.lower()
        if low_key in _CANONICAL_KEY_MAP:
            target_key = _CANONICAL_KEY_MAP[low_key]
            # Prefer primary PDF /Info keys over aliases if both are present
            if target_key not in raw_lower_map or low_key in (
                "title",
                "author",
                "subject",
                "keywords",
                "creationdate",
                "moddate",
                "creator",
                "producer",
            ):
                raw_lower_map[target_key] = v
        else:
            custom_key = _sanitize_custom_key(key_str)
            if custom_key:
                val_str = str(v).strip("\x00").strip()
                if val_str:
                    extra_fields[custom_key] = val_str

    ordered: Dict[str, Union[str, List[str]]] = {}

    # Emit canonical SSG keys in deterministic order
    canonical_sequence = (
        "title",
        "author",
        "description",
        "keywords",
        "date",
        "lastmod",
        "creator",
        "producer",
    )

    for field_name in canonical_sequence:
        if field_name not in raw_lower_map:
            continue
        val = raw_lower_map[field_name]
        if field_name == "keywords":
            if isinstance(val, (list, tuple)):
                kw_list = parse_keywords(val)
            else:
                kw_list = parse_keywords(str(val).strip("\x00"))
            if kw_list:
                ordered["keywords"] = kw_list
        else:
            val_str = str(val).strip("\x00").strip()
            if not val_str:
                continue
            if field_name in ("date", "lastmod"):
                val_str = parse_pdf_date(val_str)
            ordered[field_name] = val_str

    for k in sorted(extra_fields):
        if k not in ordered:
            ordered[k] = extra_fields[k]

    return ordered


def render_yaml_frontmatter(metadata: Mapping[str, Any]) -> str:
    """Render DocumentIR metadata into a valid YAML frontmatter block.

    Returns an empty string when no non-empty metadata fields are present.
    """
    normalized = normalize_frontmatter_metadata(metadata)
    if not normalized:
        return ""

    lines: List[str] = ["---"]
    for key, val in normalized.items():
        if isinstance(val, list):
            lines.append(f"{key}:")
            for item in val:
                lines.append(f"  - {format_yaml_scalar(item)}")
        else:
            lines.append(f"{key}: {format_yaml_scalar(val)}")
    lines.append("---")
    return "\n".join(lines)


__all__ = [
    "format_yaml_scalar",
    "normalize_frontmatter_metadata",
    "parse_keywords",
    "render_yaml_frontmatter",
]
