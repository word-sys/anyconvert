r"""RTF 1.9.1 Unicode escaping, ANSI codepage fallback mapping, and font resolution.

Provides pure-Python 7-bit ASCII RTF text encoding (\uN\'xx and \uN?),
automatic script/codepage detection for Turkish, Cyrillic, Greek, Central European,
Arabic, Hebrew, and CJK text, and PDF-to-RTF font face resolution.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Dict, List, Optional, Tuple

# PDF embedded font subset prefix (e.g., "ABCDEF+Helvetica-Bold")
_SUBSET_PREFIX_RE = re.compile(r"^[A-Z]{6}\+")

# PostScript / PDF font aliases normalized to cross-platform RTF font names
_FONT_ALIAS_MAP: Dict[str, str] = {
    "times": "Times New Roman",
    "timesroman": "Times New Roman",
    "timesnewromanpsmt": "Times New Roman",
    "timesnewromanps": "Times New Roman",
    "timesnewroman": "Times New Roman",
    "arialmt": "Arial",
    "arial": "Arial",
    "courier": "Courier New",
    "couriernewpsmt": "Courier New",
    "couriernewps": "Courier New",
    "couriernew": "Courier New",
    "calibri": "Calibri",
    "cambria": "Cambria",
    "georgia": "Georgia",
    "verdana": "Verdana",
    "tahoma": "Tahoma",
    "garamond": "Garamond",
    "palatino": "Palatino Linotype",
    "liberationsans": "Liberation Sans",
    "liberationserif": "Liberation Serif",
    "liberationmono": "Liberation Mono",
    "dejavusans": "DejaVu Sans",
    "dejavuserif": "DejaVu Serif",
    "dejavusansmono": "DejaVu Sans Mono",
    "helvetica": "Helvetica",
    "symbol": "Symbol",
    "zapfdingbats": "Zapf Dingbats",
}

_MONOSPACE_HINTS = (
    "mono",
    "courier",
    "consolas",
    "menlo",
    "monaco",
    "terminal",
    "sourcecode",
)
_SERIF_HINTS = (
    "times",
    "georgia",
    "garamond",
    "cambria",
    "palatino",
    "serif",
    "book",
    "baskerville",
    "mincho",
    "song",
    "batang",
)
_SANS_HINTS = (
    "helvetica",
    "arial",
    "calibri",
    "verdana",
    "tahoma",
    "segoe",
    "sans",
    "roboto",
    "inter",
    "open",
    "gothic",
    "meiryo",
    "yahei",
)
_TECH_HINTS = ("symbol", "wingdings", "webdings", "zapf")


@dataclass(frozen=True, slots=True)
class RtfCodePageProfile:
    """RTF ANSI codepage, font charset (\\fcharset), and Windows LCID language profile."""

    codepage: int
    charset: int
    lang_id: int
    python_codec: Optional[str]
    name: str


# Standard Windows ANSI codepages supported natively by Python's stdlib codecs
CP_WESTERN = RtfCodePageProfile(1252, 0, 1033, "cp1252", "western")
CP_CENTRAL_EUR = RtfCodePageProfile(1250, 238, 1045, "cp1250", "central_european")
CP_CYRILLIC = RtfCodePageProfile(1251, 204, 1049, "cp1251", "cyrillic")
CP_GREEK = RtfCodePageProfile(1253, 161, 1032, "cp1253", "greek")
CP_TURKISH = RtfCodePageProfile(1254, 162, 1055, "cp1254", "turkish")
CP_HEBREW = RtfCodePageProfile(1255, 177, 1037, "cp1255", "hebrew")
CP_ARABIC = RtfCodePageProfile(1256, 178, 1025, "cp1256", "arabic")
CP_JAPANESE = RtfCodePageProfile(932, 128, 1041, None, "japanese")
CP_SIMPLIFIED_CHINESE = RtfCodePageProfile(936, 134, 2052, None, "chinese")
CP_KOREAN = RtfCodePageProfile(949, 129, 1042, None, "korean")

_PROFILES_BY_CODEPAGE: Dict[int, RtfCodePageProfile] = {
    p.codepage: p
    for p in (
        CP_WESTERN,
        CP_CENTRAL_EUR,
        CP_CYRILLIC,
        CP_GREEK,
        CP_TURKISH,
        CP_HEBREW,
        CP_ARABIC,
        CP_JAPANESE,
        CP_SIMPLIFIED_CHINESE,
        CP_KOREAN,
    )
}

# Turkish-distinctive Unicode characters not in cp1252
_TURKISH_CHARS = frozenset("ğĞıİşŞ")
# Central/Eastern European distinctive Latin characters not in cp1252
_CENTRAL_EUR_CHARS = frozenset("ąćęłńśźżĄĆĘŁŃŚŹŻčďěňřšťůČĎĚŇŘŠŤŮőűŐŰăâîșțĂÂÎȘȚ")


def get_codepage_profile(codepage: int) -> RtfCodePageProfile:
    """Return the RtfCodePageProfile for a Windows ANSI codepage number."""
    return _PROFILES_BY_CODEPAGE.get(codepage, CP_WESTERN)


def detect_rtf_codepage(
    text: str,
    default_codepage: int = 1252,
) -> RtfCodePageProfile:
    """Detect the dominant non-ASCII script in text and return its RTF codepage profile."""
    if not text:
        return get_codepage_profile(default_codepage)

    counts: Dict[str, int] = {
        "turkish": 0,
        "cyrillic": 0,
        "greek": 0,
        "central_european": 0,
        "arabic": 0,
        "hebrew": 0,
        "japanese": 0,
        "korean": 0,
        "chinese": 0,
    }

    for ch in text:
        code = ord(ch)
        if code <= 0x7F:
            continue
        if ch in _TURKISH_CHARS:
            counts["turkish"] += 1
        elif 0x0400 <= code <= 0x04FF or 0x0500 <= code <= 0x052F:
            counts["cyrillic"] += 1
        elif 0x0370 <= code <= 0x03FF or 0x1F00 <= code <= 0x1FFF:
            counts["greek"] += 1
        elif 0x0600 <= code <= 0x06FF or 0x0750 <= code <= 0x077F:
            counts["arabic"] += 1
        elif 0x0590 <= code <= 0x05FF:
            counts["hebrew"] += 1
        elif 0x3040 <= code <= 0x30FF or 0x31F0 <= code <= 0x31FF:
            counts["japanese"] += 1
        elif 0xAC00 <= code <= 0xD7AF or 0x1100 <= code <= 0x11FF:
            counts["korean"] += 1
        elif 0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF:
            counts["chinese"] += 1
        elif ch in _CENTRAL_EUR_CHARS:
            counts["central_european"] += 1

    # Japanese mixes Hiragana/Katakana with Kanji (CJK Unified); prioritize Japanese if Kana present
    if counts["japanese"] > 0:
        return CP_JAPANESE

    best_script = max(counts, key=lambda k: counts[k])
    if counts[best_script] == 0:
        return get_codepage_profile(default_codepage)

    profile_map: Dict[str, RtfCodePageProfile] = {
        "turkish": CP_TURKISH,
        "cyrillic": CP_CYRILLIC,
        "greek": CP_GREEK,
        "central_european": CP_CENTRAL_EUR,
        "arabic": CP_ARABIC,
        "hebrew": CP_HEBREW,
        "korean": CP_KOREAN,
        "chinese": CP_SIMPLIFIED_CHINESE,
    }
    return profile_map[best_script]


def clean_rtf_font_name(raw_name: str) -> str:
    """Normalize a PDF font name into a clean RTF font face name."""
    if not raw_name or not raw_name.strip():
        return "Helvetica"
    cleaned = _SUBSET_PREFIX_RE.sub("", raw_name.strip())
    base = re.split(r"[-,]", cleaned, maxsplit=1)[0].strip()
    base = base.replace(";", "").replace("{", "").replace("}", "").replace("\\", "")
    return base or "Helvetica"


def resolve_rtf_font(raw_name: str) -> Tuple[str, str]:
    """Resolve a PDF font name to its canonical (display_name, rtf_family) pair."""
    cleaned = clean_rtf_font_name(raw_name)
    alias_key = cleaned.lower().replace(" ", "").replace("_", "")
    resolved = _FONT_ALIAS_MAP.get(alias_key, cleaned)
    family = classify_rtf_font_family(resolved)
    return resolved, family


def classify_rtf_font_family(font_name: str) -> str:
    """Map a font name to its RTF 1.9.1 font family control word."""
    low = font_name.lower().replace(" ", "").replace("-", "").replace("_", "")
    if any(k in low for k in _MONOSPACE_HINTS):
        return r"\fmodern"
    if any(k in low for k in _TECH_HINTS):
        return r"\ftech"
    if any(k in low for k in _SERIF_HINTS):
        return r"\froman"
    if any(k in low for k in _SANS_HINTS):
        return r"\fswiss"
    return r"\fnil"


def _ansi_fallback_for_char(ch: str, python_codec: Optional[str]) -> str:
    """Return a single-byte RTF ANSI fallback (\\'xx) if representable in codec, else '?'."""
    if not python_codec:
        return "?"
    try:
        encoded = ch.encode(python_codec)
        if len(encoded) == 1:
            byte_val = encoded[0]
            if byte_val >= 0x80:
                return f"\\'{byte_val:02x}"
    except UnicodeEncodeError:
        pass
    return "?"


def encode_rtf_unicode(text: str, codepage: int = 1252) -> str:
    """Encode arbitrary Unicode text into strict 7-bit ASCII RTF with ANSI fallbacks.

    Emits \\uN\\'xx when the character maps cleanly to a single byte in the active
    Windows ANSI codepage (e.g. cp1254 for Turkish, cp1251 for Cyrillic, cp1253
    for Greek, cp1252 for Western), and \\uN? otherwise, keeping \\uc1 strictly valid.
    """
    if not text:
        return ""

    profile = get_codepage_profile(codepage)
    codec = profile.python_codec
    out: List[str] = []

    for ch in text:
        code = ord(ch)
        if ch == "\\":
            out.append(r"\\")
        elif ch == "{":
            out.append(r"\{")
        elif ch == "}":
            out.append(r"\}")
        elif ch == "\n":
            out.append(r"\line ")
        elif ch == "\t":
            out.append(r"\tab ")
        elif ch == "\r":
            continue
        elif 0x20 <= code <= 0x7E:
            out.append(ch)
        elif code < 0x20 or code == 0x7F:
            continue
        elif code <= 0xFFFF:
            signed = code if code <= 32767 else code - 65536
            fallback = _ansi_fallback_for_char(ch, codec)
            out.append(f"\\u{signed}{fallback}")
        else:
            # Supplementary plane code point encoded as UTF-16 surrogate pair
            cp = code - 0x10000
            high = 0xD800 + (cp >> 10)
            low = 0xDC00 + (cp & 0x3FF)
            out.append(f"\\u{high - 65536}?\\u{low - 65536}?")

    return "".join(out)


def escape_rtf_text(text: str, codepage: int = 1252) -> str:
    """Alias for encode_rtf_unicode() maintaining backward compatibility."""
    return encode_rtf_unicode(text, codepage=codepage)


__all__ = [
    "RtfCodePageProfile",
    "CP_WESTERN",
    "CP_CENTRAL_EUR",
    "CP_CYRILLIC",
    "CP_GREEK",
    "CP_TURKISH",
    "CP_HEBREW",
    "CP_ARABIC",
    "CP_JAPANESE",
    "CP_SIMPLIFIED_CHINESE",
    "CP_KOREAN",
    "get_codepage_profile",
    "detect_rtf_codepage",
    "clean_rtf_font_name",
    "resolve_rtf_font",
    "classify_rtf_font_family",
    "encode_rtf_unicode",
    "escape_rtf_text",
]
