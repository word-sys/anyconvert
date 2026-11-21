"""Mathematical formula, baseline-shift, and symbol heuristics for Typst (.typ).

Detects superscript/subscript baseline shifts (explicit baseline_offset or geometric
bounding-box displacement), decodes legacy Symbol/CMSY/CMMI/CMEX/MSBM math fonts,
and translates Greek/mathematical symbols into clean Typst math notation ($x^2$,
$alpha + beta = gamma$, $sum_(i=1)^n$).
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Sequence, Tuple

from anyconvert.emitters.latex.math import (
    _ORDINAL_SUFFIXES,
    _UNICODE_SUBSCRIPTS,
    _UNICODE_SUPERSCRIPTS,
    _hoist_outer_ws,
    _is_math_base_candidate,
    _is_math_connector,
    _split_inline_unicode_math,
    classify_math_font,
    contains_math_symbol,
    decode_math_font_text,
    detect_script_kind,
    is_math_font,
)
from anyconvert.ir.model import TextRun

# Canonical Unicode Greek & math symbol -> Typst math identifier / operator
UNICODE_TO_TYPST_MATH: Dict[str, str] = {
    # Lowercase Greek
    "α": "alpha",
    "β": "beta",
    "γ": "gamma",
    "δ": "delta",
    "ε": "epsilon",
    "ϵ": "epsilon.alt",
    "ζ": "zeta",
    "η": "eta",
    "θ": "theta",
    "ϑ": "theta.alt",
    "ι": "iota",
    "κ": "kappa",
    "λ": "lambda",
    "μ": "mu",
    "ν": "nu",
    "ξ": "xi",
    "π": "pi",
    "ϖ": "pi.alt",
    "ρ": "rho",
    "ϱ": "rho.alt",
    "σ": "sigma",
    "ς": "sigma.alt",
    "τ": "tau",
    "υ": "upsilon",
    "φ": "phi",
    "ϕ": "phi.alt",
    "χ": "chi",
    "ψ": "psi",
    "ω": "omega",
    # Uppercase Greek
    "Γ": "Gamma",
    "Δ": "Delta",
    "Θ": "Theta",
    "Λ": "Lambda",
    "Ξ": "Xi",
    "Π": "Pi",
    "Σ": "Sigma",
    "Υ": "Upsilon",
    "Φ": "Phi",
    "Ψ": "Psi",
    "Ω": "Omega",
    # Operators, relations, sets, logic, calculus, arrows
    "−": "-",
    "±": "plus.minus",
    "∓": "minus.plus",
    "×": "times",
    "÷": "div",
    "⋅": "dot.op",
    "∗": "ast.op",
    "∘": "circle.small",
    "∞": "infinity",
    "∂": "diff",
    "∇": "nabla",
    "√": "sqrt",
    "∑": "sum",
    "∏": "product",
    "∫": "integral",
    "∮": "integral.cont",
    "≈": "approx",
    "≠": "!=",
    "≡": "equiv",
    "≤": "<=",
    "≥": ">=",
    "≪": "<<",
    "≫": ">>",
    "∝": "prop",
    "∼": "tilde.op",
    "≃": "tilde.eq",
    "≅": "tilde.equiv",
    "∈": "in",
    "∉": "in.not",
    "∋": "in.rev",
    "⊂": "subset",
    "⊃": "supset",
    "⊆": "subset.eq",
    "⊇": "supset.eq",
    "∪": "union",
    "∩": "inter",
    "∅": "emptyset",
    "∀": "forall",
    "∃": "exists",
    "¬": "not",
    "∧": "and",
    "∨": "or",
    "⊥": "perp",
    "∥": "parallel",
    "∠": "angle",
    "←": "<-",
    "→": "->",
    "↑": "arrow.t",
    "↓": "arrow.b",
    "↔": "<->",
    "⇐": "arrow.l.double",
    "⇒": "=>",
    "⇔": "<=>",
    "↦": "|->",
    "′": "'",
    "″": "''",
    "⊕": "plus.circle",
    "⊖": "minus.circle",
    "⊗": "times.circle",
    "∖": "without",
    "⟨": "chevron.l",
    "⟩": "chevron.r",
    "ℕ": "NN",
    "ℤ": "ZZ",
    "ℚ": "QQ",
    "ℝ": "RR",
    "ℂ": "CC",
}

_BB_SHORTCUTS: Dict[str, str] = {
    "N": "NN",
    "Z": "ZZ",
    "Q": "QQ",
    "R": "RR",
    "C": "CC",
}


def _format_typst_script_arg(expr: str) -> str:
    """Wrap multi-character Typst script arguments in parentheses; keep single tokens bare."""
    cleaned = expr.strip()
    if not cleaned:
        return "()"
    if len(cleaned) == 1 and cleaned.isalnum():
        return cleaned
    return f"({cleaned})"


def _append_typst_token(parts: List[str], token: str, is_sym: bool = False) -> None:
    """Append a Typst math token while preventing symbol/identifier fusion."""
    if not token:
        return
    if parts:
        prev = parts[-1]
        if prev and not prev[-1].isspace() and not token[0].isspace():
            prev_word = prev[-1].isalnum() or prev[-1] == "."
            curr_word = token[0].isalnum()
            if prev_word and curr_word:
                # Separate multi-char symbols (e.g. alpha x, 2 pi, x in RR)
                if is_sym or len(prev) > 1 or len(token) > 1:
                    parts.append(" ")
    parts.append(token)


def translate_math_text_to_typst(text: str, font_name: str = "") -> str:
    """Translate decoded math/Greek text into clean Typst math-mode notation."""
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

        # Group contiguous Unicode superscripts (e.g. ⁻⁶ -> ^(-6))
        if ch in _UNICODE_SUPERSCRIPTS:
            sup_chars: List[str] = []
            while i < n and decoded[i] in _UNICODE_SUPERSCRIPTS:
                sup_chars.append(_UNICODE_SUPERSCRIPTS[decoded[i]])
                i += 1
            parts.append("^" + _format_typst_script_arg("".join(sup_chars)))
            continue

        # Group contiguous Unicode subscripts (e.g. ₁₂ -> _(12))
        if ch in _UNICODE_SUBSCRIPTS:
            sub_chars: List[str] = []
            while i < n and decoded[i] in _UNICODE_SUBSCRIPTS:
                sub_chars.append(_UNICODE_SUBSCRIPTS[decoded[i]])
                i += 1
            parts.append("_" + _format_typst_script_arg("".join(sub_chars)))
            continue

        # Calligraphic uppercase in CMSY (A-Z -> cal(A))
        if kind == "cmsy" and "A" <= ch <= "Z":
            _append_typst_token(parts, f"cal({ch})", is_sym=True)
            i += 1
            continue

        # Blackboard bold uppercase in MSBM (R -> RR, F -> bb(F))
        if kind == "msbm" and "A" <= ch <= "Z":
            bb_tok = _BB_SHORTCUTS.get(ch, f"bb({ch})")
            _append_typst_token(parts, bb_tok, is_sym=True)
            i += 1
            continue

        mapped = UNICODE_TO_TYPST_MATH.get(ch)
        if mapped is not None:
            _append_typst_token(parts, mapped, is_sym=True)
            i += 1
            continue

        # Escape characters that would break Typst math mode delimiters
        if ch in ("$", "#", '"', "\\"):
            parts.append("\\" + ch)
        else:
            _append_typst_token(parts, ch, is_sym=False)
        i += 1

    return "".join(parts)


def render_typst_math_runs(
    runs: Sequence[TextRun],
    render_run_fn: Callable[[TextRun, Optional[str], bool], str],
    first_run_override: Optional[str] = None,
    suppress_bold: bool = False,
) -> Tuple[str, bool]:
    """Render a paragraph's TextRuns with mathematical formula & symbol heuristics.

    Returns:
        Tuple of (rendered_typst_string, used_math_flag).
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
                    math_expr = translate_math_text_to_typst(base, r.font_name)
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
                        s_typ = translate_math_text_to_typst(s_core, runs[j].font_name)
                        op = "^" if sk == "sup" else "_"
                        math_expr += op + _format_typst_script_arg(s_typ)
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
                math_expr = translate_math_text_to_typst(core, r.font_name)
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
                    tokens.append(("math", translate_math_text_to_typst(chunk), ""))
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
                    _append_typst_token(buf, tokens[idx][1], is_sym=True)
                    idx += 1
                elif tokens[idx][0] == "conn":
                    k = idx
                    while k < t_len and tokens[k][0] == "conn":
                        k += 1
                    if k < t_len and tokens[k][0] == "math":
                        conn_joined = "".join(tokens[m_i][1] for m_i in range(idx, k))
                        conn_typ = translate_math_text_to_typst(conn_joined)
                        _append_typst_token(buf, conn_typ, is_sym=False)
                        _append_typst_token(buf, tokens[k][1], is_sym=True)
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
            # Inline Typst math must NOT have leading/trailing spaces inside $...$
            result_parts.append(f"${val}$")
        else:
            result_parts.append(val)
    return "".join(result_parts), True


__all__ = [
    "UNICODE_TO_TYPST_MATH",
    "classify_math_font",
    "contains_math_symbol",
    "decode_math_font_text",
    "detect_script_kind",
    "is_math_font",
    "render_typst_math_runs",
    "translate_math_text_to_typst",
]
