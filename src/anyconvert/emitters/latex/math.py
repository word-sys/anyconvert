r"""Mathematical formula, baseline-shift, and symbol heuristics for LaTeX (.tex).

Detects superscript/subscript baseline shifts (explicit baseline_offset or geometric
bounding-box displacement), decodes legacy Symbol/CMSY/CMMI/CMEX/MSBM math fonts,
and translates Greek/mathematical symbols into clean LaTeX math notation ($x^2$,
$\alpha + \beta = \gamma$, $\sum_{i=1}^{n}$).
"""

from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from anyconvert.ir.model import TextRun

# PDF embedded font subset tag pattern (e.g. "ABCDEF+CMSY10")
_SUBSET_PREFIX_RE = re.compile(r"^[A-Z]{6}\+")

# Known LaTeX math function names allowed inside merged inline math connectors
_MATH_FUNC_NAMES = frozenset(
    {
        "sin",
        "cos",
        "tan",
        "cot",
        "sec",
        "csc",
        "arcsin",
        "arccos",
        "arctan",
        "sinh",
        "cosh",
        "tanh",
        "log",
        "ln",
        "exp",
        "lim",
        "max",
        "min",
        "sup",
        "inf",
        "det",
        "dim",
        "ker",
        "arg",
        "gcd",
        "mod",
        "Pr",
    }
)

_ORDINAL_SUFFIXES = frozenset({"st", "nd", "rd", "th"})

# Adobe Standard Symbol font ASCII/extended byte -> Unicode canonical character
_SYMBOL_FONT_MAP: Dict[str, str] = {
    # Lowercase Greek
    "a": "α",
    "b": "β",
    "g": "γ",
    "d": "δ",
    "e": "ε",
    "z": "ζ",
    "h": "η",
    "q": "θ",
    "i": "ι",
    "k": "κ",
    "l": "λ",
    "m": "μ",
    "n": "ν",
    "x": "ξ",
    "o": "ο",
    "p": "π",
    "r": "ρ",
    "s": "σ",
    "t": "τ",
    "u": "υ",
    "f": "φ",
    "c": "χ",
    "y": "ψ",
    "w": "ω",
    "j": "ϕ",
    "v": "ϖ",
    "V": "ς",
    # Uppercase Greek
    "A": "Α",
    "B": "Β",
    "G": "Γ",
    "D": "Δ",
    "E": "Ε",
    "Z": "Ζ",
    "H": "Η",
    "Q": "Θ",
    "I": "Ι",
    "K": "Κ",
    "L": "Λ",
    "M": "Μ",
    "N": "Ν",
    "X": "Ξ",
    "O": "Ο",
    "P": "Π",
    "R": "Ρ",
    "S": "Σ",
    "T": "Τ",
    "U": "Υ",
    "F": "Φ",
    "C": "Χ",
    "Y": "Ψ",
    "W": "Ω",
    # Symbol operators & relations
    '"': "∀",
    "$": "∃",
    "'": "∋",
    "*": "∗",
    "-": "−",
    "^": "⊥",
    "~": "∼",
    "\xa3": "≤",
    "\xa5": "∞",
    "\xab": "↔",
    "\xac": "←",
    "\xad": "↑",
    "\xae": "→",
    "\xaf": "↓",
    "\xb0": "°",
    "\xb1": "±",
    "\xb3": "≥",
    "\xb4": "×",
    "\xb5": "∝",
    "\xb6": "∂",
    "\xb7": "⋅",
    "\xb8": "÷",
    "\xb9": "≠",
    "\xba": "≡",
    "\xbb": "≈",
    "\xc4": "⊗",
    "\xc5": "⊕",
    "\xc6": "∅",
    "\xc7": "∩",
    "\xc8": "∪",
    "\xc9": "⊃",
    "\xca": "⊇",
    "\xcc": "⊂",
    "\xcd": "⊆",
    "\xce": "∈",
    "\xcf": "∉",
    "\xd0": "∠",
    "\xd1": "∇",
    "\xd5": "∏",
    "\xd6": "√",
    "\xd7": "⋅",
    "\xd8": "¬",
    "\xd9": "∧",
    "\xda": "∨",
    "\xdb": "⇔",
    "\xdc": "⇐",
    "\xde": "⇒",
    "\xe5": "∑",
    "\xf2": "∫",
}

# Knuth OMS (CMSY) legacy encoding -> Unicode canonical character
_CMSY_FONT_MAP: Dict[str, str] = {
    "\x00": "−",
    "\x01": "⋅",
    "\x02": "×",
    "\x03": "∗",
    "\x04": "÷",
    "\x06": "±",
    "\x07": "∓",
    "\x08": "⊕",
    "\x09": "⊖",
    "\x0a": "⊗",
    "\x0e": "∘",
    "\x11": "≡",
    "\x12": "⊆",
    "\x13": "⊇",
    "\x14": "≤",
    "\x15": "≥",
    "\x18": "∼",
    "\x19": "≈",
    "\x1a": "⊂",
    "\x1b": "⊃",
    "\x1c": "≪",
    "\x1d": "≫",
    "\x20": "←",
    "\x21": "→",
    "\x22": "↑",
    "\x23": "↓",
    "\x24": "↔",
    "\x28": "⇐",
    "\x29": "⇒",
    "\x2c": "⇔",
    "\x2f": "∝",
    "\x30": "′",
    "\x31": "∞",
    "\x32": "∈",
    "\x33": "∋",
    "\x38": "∀",
    "\x39": "∃",
    "\x3a": "¬",
    "\x3b": "∅",
    "\x3f": "⊥",
    "\x5b": "∪",
    "\x5c": "∩",
    "\x5e": "∧",
    "\x5f": "∨",
    "\x66": "{",
    "\x67": "}",
    "\x68": "⟨",
    "\x69": "⟩",
    "\x6a": "|",
    "\x6b": "∥",
    "\x6e": "∖",
    "\x70": "√",
    "\x72": "∇",
    "\x73": "∫",
}

# Knuth OML (CMMI) legacy low-codepoint Greek encoding
_CMMI_FONT_MAP: Dict[str, str] = {
    "\x0b": "α",
    "\x0c": "β",
    "\x0d": "γ",
    "\x0e": "δ",
    "\x0f": "ε",
    "\x10": "ζ",
    "\x11": "η",
    "\x12": "θ",
    "\x13": "ι",
    "\x14": "κ",
    "\x15": "λ",
    "\x16": "μ",
    "\x17": "ν",
    "\x18": "ξ",
    "\x19": "π",
    "\x1a": "ρ",
    "\x1b": "σ",
    "\x1c": "τ",
    "\x1d": "υ",
    "\x1e": "φ",
    "\x1f": "χ",
    "\x20": "ψ",
    "\x21": "ω",
    "\x22": "ϵ",
    "\x23": "ϑ",
    "\x27": "ϕ",
    "\x40": "∂",
}

# Knuth OMX (CMEX) legacy big-operator encoding
_CMEX_FONT_MAP: Dict[str, str] = {
    "\x50": "∑",
    "\x51": "∏",
    "\x52": "∫",
    "\x58": "∑",
    "\x59": "∏",
    "\x5a": "∫",
}

# Canonical Unicode Greek & math symbol -> LaTeX math command
UNICODE_TO_LATEX_MATH: Dict[str, str] = {
    # Lowercase Greek
    "α": r"\alpha",
    "β": r"\beta",
    "γ": r"\gamma",
    "δ": r"\delta",
    "ε": r"\varepsilon",
    "ϵ": r"\epsilon",
    "ζ": r"\zeta",
    "η": r"\eta",
    "θ": r"\theta",
    "ϑ": r"\vartheta",
    "ι": r"\iota",
    "κ": r"\kappa",
    "λ": r"\lambda",
    "μ": r"\mu",
    "ν": r"\nu",
    "ξ": r"\xi",
    "π": r"\pi",
    "ϖ": r"\varpi",
    "ρ": r"\rho",
    "ϱ": r"\varrho",
    "σ": r"\sigma",
    "ς": r"\varsigma",
    "τ": r"\tau",
    "υ": r"\upsilon",
    "φ": r"\phi",
    "ϕ": r"\varphi",
    "χ": r"\chi",
    "ψ": r"\psi",
    "ω": r"\omega",
    # Uppercase Greek (distinct from Latin)
    "Γ": r"\Gamma",
    "Δ": r"\Delta",
    "Θ": r"\Theta",
    "Λ": r"\Lambda",
    "Ξ": r"\Xi",
    "Π": r"\Pi",
    "Σ": r"\Sigma",
    "Υ": r"\Upsilon",
    "Φ": r"\Phi",
    "Ψ": r"\Psi",
    "Ω": r"\Omega",
    # Operators, relations, sets, logic, calculus, arrows
    "−": "-",
    "±": r"\pm",
    "∓": r"\mp",
    "×": r"\times",
    "÷": r"\div",
    "⋅": r"\cdot",
    "∗": r"\ast",
    "∘": r"\circ",
    "∞": r"\infty",
    "∂": r"\partial",
    "∇": r"\nabla",
    "√": r"\sqrt{}",
    "∑": r"\sum",
    "∏": r"\prod",
    "∫": r"\int",
    "∮": r"\oint",
    "≈": r"\approx",
    "≠": r"\neq",
    "≡": r"\equiv",
    "≤": r"\le",
    "≥": r"\ge",
    "≪": r"\ll",
    "≫": r"\gg",
    "∝": r"\propto",
    "∼": r"\sim",
    "≃": r"\simeq",
    "≅": r"\cong",
    "∈": r"\in",
    "∉": r"\notin",
    "∋": r"\ni",
    "⊂": r"\subset",
    "⊃": r"\supset",
    "⊆": r"\subseteq",
    "⊇": r"\supseteq",
    "∪": r"\cup",
    "∩": r"\cap",
    "∅": r"\emptyset",
    "∀": r"\forall",
    "∃": r"\exists",
    "¬": r"\neg",
    "∧": r"\wedge",
    "∨": r"\vee",
    "⊥": r"\perp",
    "∥": r"\parallel",
    "∠": r"\angle",
    "←": r"\leftarrow",
    "→": r"\rightarrow",
    "↑": r"\uparrow",
    "↓": r"\downarrow",
    "↔": r"\leftrightarrow",
    "⇐": r"\Leftarrow",
    "⇒": r"\Rightarrow",
    "⇔": r"\Leftrightarrow",
    "↦": r"\mapsto",
    "′": "'",
    "″": "''",
    "⊕": r"\oplus",
    "⊖": r"\ominus",
    "⊗": r"\otimes",
    "∖": r"\setminus",
    "⟨": r"\langle",
    "⟩": r"\rangle",
    "ℕ": r"\mathbb{N}",
    "ℤ": r"\mathbb{Z}",
    "ℚ": r"\mathbb{Q}",
    "ℝ": r"\mathbb{R}",
    "ℂ": r"\mathbb{C}",
}

# Unicode superscript and subscript characters
_UNICODE_SUPERSCRIPTS: Dict[str, str] = {
    "⁰": "0",
    "¹": "1",
    "²": "2",
    "³": "3",
    "⁴": "4",
    "⁵": "5",
    "⁶": "6",
    "⁷": "7",
    "⁸": "8",
    "⁹": "9",
    "⁺": "+",
    "⁻": "-",
    "⁼": "=",
    "⁽": "(",
    "⁾": ")",
    "ⁿ": "n",
    "ⁱ": "i",
}

_UNICODE_SUBSCRIPTS: Dict[str, str] = {
    "₀": "0",
    "₁": "1",
    "₂": "2",
    "₃": "3",
    "₄": "4",
    "₅": "5",
    "₆": "6",
    "₇": "7",
    "₈": "8",
    "₉": "9",
    "₊": "+",
    "₋": "-",
    "₌": "=",
    "₍": "(",
    "₎": ")",
    "ₐ": "a",
    "ₑ": "e",
    "ᵢ": "i",
    "ⱼ": "j",
    "ₖ": "k",
    "ₘ": "m",
    "ₙ": "n",
    "ₒ": "o",
    "ₚ": "p",
    "ᵣ": "r",
    "ₛ": "s",
    "ₜ": "t",
    "ᵤ": "u",
    "ᵥ": "v",
    "ₓ": "x",
}

_MATH_TRIGGER_CHARS = (
    frozenset(UNICODE_TO_LATEX_MATH.keys())
    | frozenset(_UNICODE_SUPERSCRIPTS.keys())
    | frozenset(_UNICODE_SUBSCRIPTS.keys())
)
_TRIGGER_CLASS = re.escape("".join(sorted(_MATH_TRIGGER_CHARS)))

_TRAILING_MATH_BASE_RE = re.compile(
    r"^(?P<prefix>.*\s)?(?P<base>(?:[A-Za-z]|\([^()]{1,20}\)|\d+(?:\.\d+)?))$"
)
_WHOLE_MATH_EXPR_RE = re.compile(r"^[A-Za-z0-9+\-*/=<>()\[\]|,.\s]+$")

# Matches an inline Unicode math expression without absorbing multi-letter prose words
_INLINE_MATH_SPAN_RE = re.compile(
    r"(?:(?<![A-Za-z0-9])(?:[A-Za-z](?![A-Za-z])|\d+(?:\.\d+)?)"
    r"(?:\s*[+\-*/=<>]\s*|\s+))?"
    r"[" + _TRIGGER_CLASS + r"]+"
    r"(?:\s*(?:[" + _TRIGGER_CLASS + r"]+|[+\-*/=<>|]"
    r"|(?<![A-Za-z0-9])[A-Za-z](?![A-Za-z])|\d+(?:\.\d+)?))*"
)


def _normalize_font_tag(font_name: str) -> str:
    """Strip 6-char PDF subset prefix and lowercase font name."""
    if not font_name:
        return ""
    return _SUBSET_PREFIX_RE.sub("", font_name.strip()).lower()


def classify_math_font(font_name: str) -> Optional[str]:
    """Classify a PDF font name into a known math font family or return None."""
    norm = _normalize_font_tag(font_name)
    if not norm:
        return None
    if norm.startswith("cmsy") or "cmsy" in norm:
        return "cmsy"
    if norm.startswith("cmmi") or "cmmi" in norm:
        return "cmmi"
    if norm.startswith("cmex") or "cmex" in norm:
        return "cmex"
    if norm.startswith("msbm") or "msbm" in norm:
        return "msbm"
    if (
        norm == "symbol"
        or norm.startswith("symbol-")
        or norm.startswith("symbolmt")
        or "standardsyml" in norm
        or "euclidsymbol" in norm
        or "euclid symbol" in norm
    ):
        return "symbol"
    if any(
        tok in norm
        for tok in (
            "cambriamath",
            "cambria math",
            "stix",
            "lmmath",
            "latinmodernmath",
            "asanamath",
            "mathitalic",
            "mtex",
            "mathematicalpi",
        )
    ):
        return "unicode_math"
    return None


def is_math_font(font_name: str) -> bool:
    """Return True if font_name represents a mathematical or symbol font."""
    return classify_math_font(font_name) is not None


def contains_math_symbol(text: str) -> bool:
    """Return True if text contains any Unicode Greek or mathematical symbol."""
    return any(ch in _MATH_TRIGGER_CHARS for ch in text)


def decode_math_font_text(text: str, font_name: str) -> str:
    """Decode legacy Symbol, CMSY, CMMI, or CMEX font bytes into canonical Unicode."""
    if not text:
        return ""
    kind = classify_math_font(font_name)
    if kind == "symbol":
        return "".join(_SYMBOL_FONT_MAP.get(ch, ch) for ch in text)
    if kind == "cmsy":
        return "".join(_CMSY_FONT_MAP.get(ch, ch) for ch in text)
    if kind == "cmmi":
        return "".join(_CMMI_FONT_MAP.get(ch, ch) for ch in text)
    if kind == "cmex":
        return "".join(_CMEX_FONT_MAP.get(ch, ch) for ch in text)
    return text


def detect_script_kind(
    run: TextRun,
    base_run: Optional[TextRun] = None,
) -> Optional[str]:
    """Detect whether run is a superscript ('sup') or subscript ('sub').

    Checks explicit TextRun.baseline_offset first, then falls back to geometric
    bounding-box vertical displacement + reduced font size relative to base_run.
    """
    if run.baseline_offset > 0.5:
        return "sup"
    if run.baseline_offset < -0.5:
        return "sub"

    if (
        base_run is None
        or run.bbox is None
        or base_run.bbox is None
        or base_run.font_size <= 0.0
        or run.font_size <= 0.0
    ):
        return None

    # Geometric heuristic: smaller font size on the same visual line with shifted baseline
    if run.font_size > 0.85 * base_run.font_size:
        return None

    b_box = base_run.bbox
    r_box = run.bbox
    if r_box.height <= 0.0 or b_box.height <= 0.0:
        return None

    # Must lie near the same horizontal line (not a different line)
    if r_box.y0 > b_box.y1 + 0.5 * base_run.font_size or r_box.y1 < b_box.y0 - 0.5 * base_run.font_size:
        return None

    # Must appear after the start of the base run and reasonably close horizontally
    if r_box.x0 < b_box.x0 - 1.0 or (r_box.x0 - b_box.x1) > max(base_run.font_size * 1.2, 12.0):
        return None

    base_cy = (b_box.y0 + b_box.y1) * 0.5
    run_cy = (r_box.y0 + r_box.y1) * 0.5

    # Document presentation space: Y increases downward (smaller y1 = raised baseline)
    if r_box.y1 < b_box.y1 - 0.15 * base_run.font_size and run_cy < base_cy:
        return "sup"
    if r_box.y1 > b_box.y1 + 0.12 * base_run.font_size and run_cy > base_cy:
        return "sub"
    return None


def _format_latex_script_arg(expr: str) -> str:
    """Wrap multi-token or macro LaTeX script arguments in braces; keep single tokens bare."""
    cleaned = expr.strip()
    if not cleaned:
        return "{}"
    if len(cleaned) == 1 and cleaned.isalnum():
        return cleaned
    return "{" + cleaned + "}"


def _append_latex_token(parts: List[str], token: str) -> None:
    """Append a LaTeX math token while preventing macro-name collisions like \\alphax."""
    if not token:
        return
    if parts:
        prev = parts[-1]
        if (
            prev.startswith("\\")
            and len(prev) > 1
            and prev[-1].isalpha()
            and token[0].isalpha()
        ):
            parts.append(" ")
    parts.append(token)


def translate_math_text_to_latex(text: str, font_name: str = "") -> str:
    """Translate decoded math/Greek text into clean LaTeX math-mode notation."""
    if not text:
        return ""
    kind = classify_math_font(font_name)
    decoded = decode_math_font_text(text, font_name)

    parts: List[str] = []
    n = len(decoded)
    i = 0
    while i < n:
        ch = decoded[i]
        if ch == "\r":
            i += 1
            continue

        # Group contiguous Unicode superscripts (e.g. ⁻⁶ -> ^{-6})
        if ch in _UNICODE_SUPERSCRIPTS:
            sup_chars: List[str] = []
            while i < n and decoded[i] in _UNICODE_SUPERSCRIPTS:
                sup_chars.append(_UNICODE_SUPERSCRIPTS[decoded[i]])
                i += 1
            parts.append("^" + _format_latex_script_arg("".join(sup_chars)))
            continue

        # Group contiguous Unicode subscripts (e.g. ₁₂ -> _{12})
        if ch in _UNICODE_SUBSCRIPTS:
            sub_chars: List[str] = []
            while i < n and decoded[i] in _UNICODE_SUBSCRIPTS:
                sub_chars.append(_UNICODE_SUBSCRIPTS[decoded[i]])
                i += 1
            parts.append("_" + _format_latex_script_arg("".join(sub_chars)))
            continue

        # Calligraphic uppercase in CMSY (A-Z -> \mathcal{A})
        if kind == "cmsy" and "A" <= ch <= "Z":
            _append_latex_token(parts, f"\\mathcal{{{ch}}}")
            i += 1
            continue

        # Blackboard bold uppercase in MSBM (R -> \mathbb{R})
        if kind == "msbm" and "A" <= ch <= "Z":
            _append_latex_token(parts, f"\\mathbb{{{ch}}}")
            i += 1
            continue

        mapped = UNICODE_TO_LATEX_MATH.get(ch)
        if mapped is not None:
            _append_latex_token(parts, mapped)
            i += 1
            continue

        # Safe escaping of TeX structural chars inside math mode
        if ch in ("%", "#", "&", "$"):
            parts.append("\\" + ch)
        elif ch == "{":
            parts.append(r"\{")
        elif ch == "}":
            parts.append(r"\}")
        elif ch == "_":
            parts.append(r"\_")
        elif ch == "\\":
            _append_latex_token(parts, r"\backslash")
        else:
            _append_latex_token(parts, ch)
        i += 1

    return "".join(parts)


def _is_math_connector(text: str) -> bool:
    """Return True if a short plain run can bridge two adjacent math expressions."""
    if not text or "\n" in text:
        return False
    stripped = text.strip()
    if not stripped:
        return len(text) <= 2
    if not _WHOLE_MATH_EXPR_RE.match(stripped):
        return False
    for word in re.findall(r"[A-Za-z]+", stripped):
        if len(word) > 1 and word not in _MATH_FUNC_NAMES:
            return False
    return True


def _is_math_base_candidate(text: str, font_name: str) -> Tuple[Optional[str], Optional[str]]:
    """Split a plain run preceding a script into (prose_prefix, math_base) if applicable.

    Returns (None, None) when the preceding run is prose (e.g. a multi-letter word
    receiving a footnote superscript, or trailing whitespace).
    """
    if not text or text[-1].isspace():
        return None, None
    if is_math_font(font_name) or contains_math_symbol(text):
        lead_len = len(text) - len(text.lstrip())
        return text[:lead_len], text[lead_len:]

    stripped = text.strip()
    if stripped and _WHOLE_MATH_EXPR_RE.match(stripped):
        words = re.findall(r"[A-Za-z]+", stripped)
        has_eq_op = any(op in stripped for op in ("=", "+", "-", "/", "<", ">", "(", ")"))
        if all(len(w) == 1 or w in _MATH_FUNC_NAMES for w in words):
            lead_len = len(text) - len(text.lstrip())
            return text[:lead_len], text[lead_len:]
        if has_eq_op and all(len(w) <= 2 or w in _MATH_FUNC_NAMES for w in words):
            lead_len = len(text) - len(text.lstrip())
            return text[:lead_len], text[lead_len:]

    m = _TRAILING_MATH_BASE_RE.match(text)
    if m:
        prefix = m.group("prefix") or ""
        base = m.group("base")
        return prefix, base

    return None, None


def _split_inline_unicode_math(text: str) -> List[Tuple[bool, str]]:
    """Split a single plain run containing Unicode Greek/math symbols into (is_math, chunk) spans."""
    if not contains_math_symbol(text):
        return [(False, text)]

    segments: List[Tuple[bool, str]] = []
    pos = 0
    n = len(text)
    for m in _INLINE_MATH_SPAN_RE.finditer(text):
        start, end = m.start(), m.end()
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1] in " \t.,;:!?":
            end -= 1
        sub = text[start:end]
        if not sub or not contains_math_symbol(sub):
            continue
        if start > pos:
            segments.append((False, text[pos:start]))
        segments.append((True, sub))
        pos = end

    if pos < n:
        segments.append((False, text[pos:]))
    return segments


def _hoist_outer_ws(raw: str) -> Tuple[str, str, str]:
    """Split raw into (leading_ws, core, trailing_ws)."""
    stripped = raw.strip()
    if not stripped:
        return raw, "", ""
    lead_len = len(raw) - len(raw.lstrip())
    trail_len = len(raw) - len(raw.rstrip())
    lead = raw[:lead_len]
    trail = raw[len(raw) - trail_len :] if trail_len > 0 else ""
    return lead, stripped, trail


def render_latex_math_runs(
    runs: Sequence[TextRun],
    render_run_fn: Callable[[TextRun, Optional[str], bool], str],
    first_run_override: Optional[str] = None,
    suppress_bold: bool = False,
) -> Tuple[str, bool]:
    """Render a paragraph's TextRuns with mathematical formula & symbol heuristics.

    Returns:
        Tuple of (rendered_latex_string, used_math_flag).
    """
    if not runs:
        return "", False

    eff_texts: List[str] = []
    override_used = False
    for r in runs:
        if not override_used and first_run_override is not None and r.text:
            eff_texts.append(first_run_override)
            override_used = True
        else:
            eff_texts.append(r.text)

    # Sequence of (kind, math_or_raw_val, fallback_rendered_text)
    tokens: List[Tuple[str, str, str]] = []
    used_math = False
    n = len(runs)
    i = 0

    while i < n:
        r = runs[i]
        raw = eff_texts[i]
        if not raw:
            i += 1
            continue

        # 1. Check if this non-script run is a base followed by one or more math script runs
        next_script = (
            detect_script_kind(runs[i + 1], r)
            if detect_script_kind(r) is None and i + 1 < n
            else None
        )
        if next_script is not None:
            next_core = eff_texts[i + 1].strip()
            is_ordinal = next_script == "sup" and next_core.lower() in _ORDINAL_SUFFIXES
            if next_core and not is_ordinal:
                prefix, base = _is_math_base_candidate(raw, r.font_name)
                if base is not None:
                    if prefix:
                        rendered_pref = render_run_fn(r, prefix, suppress_bold)
                        tokens.append(("text", rendered_pref, rendered_pref))
                    math_expr = translate_math_text_to_latex(base, r.font_name)
                    anchor = r
                    trail_after_scripts = ""
                    j = i + 1
                    while j < n:
                        sk = detect_script_kind(runs[j], anchor)
                        if sk is None:
                            break
                        s_raw = eff_texts[j]
                        _, s_core, s_trail = _hoist_outer_ws(s_raw)
                        if not s_core:
                            break
                        s_tex = translate_math_text_to_latex(s_core, runs[j].font_name)
                        op = "^" if sk == "sup" else "_"
                        math_expr += op + _format_latex_script_arg(s_tex)
                        trail_after_scripts = s_trail
                        j += 1
                        if s_trail:
                            break
                    tokens.append(("math", math_expr, ""))
                    used_math = True
                    if trail_after_scripts:
                        if len(trail_after_scripts) <= 2 and "\n" not in trail_after_scripts:
                            tokens.append(("conn", trail_after_scripts, trail_after_scripts))
                        else:
                            tokens.append(("text", trail_after_scripts, trail_after_scripts))
                    i = j
                    continue

        # 2. Check if this run itself uses a math/symbol font
        if is_math_font(r.font_name):
            lead, core, trail = _hoist_outer_ws(raw)
            if lead:
                tokens.append(("conn" if len(lead) <= 2 else "text", lead, lead))
            if core:
                math_expr = translate_math_text_to_latex(core, r.font_name)
                tokens.append(("math", math_expr, ""))
                used_math = True
            if trail:
                tokens.append(("conn" if len(trail) <= 2 else "text", trail, trail))
            i += 1
            continue

        # 3. Check if this run contains Unicode Greek or math symbols inline
        if contains_math_symbol(raw):
            for is_m, chunk in _split_inline_unicode_math(raw):
                if not chunk:
                    continue
                if is_m:
                    tokens.append(("math", translate_math_text_to_latex(chunk), ""))
                    used_math = True
                else:
                    rendered_chunk = render_run_fn(r, chunk, suppress_bold)
                    if _is_math_connector(chunk) and not (
                        r.is_bold or r.is_underline or r.is_strikethrough
                    ):
                        tokens.append(("conn", chunk, rendered_chunk))
                    else:
                        tokens.append(("text", rendered_chunk, rendered_chunk))
            i += 1
            continue

        # 4. Plain prose run (eligible as math connector if short operator/symbol bridge)
        rendered_plain = render_run_fn(r, raw, suppress_bold)
        if _is_math_connector(raw) and not (r.is_bold or r.is_underline or r.is_strikethrough):
            tokens.append(("conn", raw, rendered_plain))
        else:
            tokens.append(("text", rendered_plain, rendered_plain))
        i += 1

    if not used_math:
        out_plain: List[str] = []
        override_used = False
        for r in runs:
            if not override_used and first_run_override is not None and r.text:
                out_plain.append(render_run_fn(r, first_run_override, suppress_bold))
                override_used = True
            else:
                out_plain.append(render_run_fn(r, None, suppress_bold))
        return "".join(out_plain), False

    # Merge adjacent ("math", ...) tokens bridged by one or more ("conn", ...) tokens
    merged: List[Tuple[str, str]] = []
    idx = 0
    t_len = len(tokens)
    while idx < t_len:
        kind, val, fallback = tokens[idx]
        if kind == "math":
            buf = [val]
            idx += 1
            while idx < t_len:
                if tokens[idx][0] == "math":
                    _append_latex_token(buf, tokens[idx][1])
                    idx += 1
                elif tokens[idx][0] == "conn":
                    # Look ahead past consecutive connectors to see if another math token follows
                    k = idx
                    while k < t_len and tokens[k][0] == "conn":
                        k += 1
                    if k < t_len and tokens[k][0] == "math":
                        conn_joined = "".join(tokens[m_i][1] for m_i in range(idx, k))
                        # Avoid merging across plain whitespace without an operator unless short
                        conn_tex = translate_math_text_to_latex(conn_joined)
                        _append_latex_token(buf, conn_tex)
                        _append_latex_token(buf, tokens[k][1])
                        idx = k + 1
                    else:
                        break
                else:
                    break
            merged.append(("math", "".join(buf).strip()))
        elif kind == "conn":
            merged.append(("text", fallback))
            idx += 1
        else:
            merged.append((kind, val))
            idx += 1

    result_parts: List[str] = []
    for kind, val in merged:
        if kind == "math" and val:
            result_parts.append(f"${val}$")
        else:
            result_parts.append(val)
    return "".join(result_parts), True


__all__ = [
    "UNICODE_TO_LATEX_MATH",
    "classify_math_font",
    "contains_math_symbol",
    "decode_math_font_text",
    "detect_script_kind",
    "is_math_font",
    "render_latex_math_runs",
    "translate_math_text_to_latex",
]
