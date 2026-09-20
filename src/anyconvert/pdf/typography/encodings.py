"""Standard PDF character encodings, Adobe Glyph List (AGL), and /Differences resolvers.

Implements ISO 32000-1 Annex D:
- StandardEncoding
- MacRomanEncoding
- WinAnsiEncoding
- PDFDocEncoding
- SymbolEncoding & ZapfDingbatsEncoding
- Adobe Glyph List (AGL) with algorithmic uniXXXX / uXXXX resolution
- /Differences array parser and dynamic encoding mutations
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Sequence, Union

from anyconvert.pdf.parser import PDFArray, PDFDict, PDFName
from anyconvert.pdf.xref import XRefResolver

# ==============================================================================
# 1. Base Encoding Tables (ISO 32000-1 Annex D)
# ==============================================================================

# Standard ASCII printable characters (32..126)
_ASCII_BASE: Dict[int, str] = {i: chr(i) for i in range(32, 127)}

# WinAnsiEncoding (Windows-1252 / ISO 8859-1 superset)
WIN_ANSI_ENCODING: Dict[int, str] = dict(_ASCII_BASE)
WIN_ANSI_ENCODING.update({
    # Control codes commonly mapped
    9: "\t", 10: "\n", 13: "\r",
    # 128..159 Windows-1252 extensions
    128: "\u20ac",  # Euro
    130: "\u201a",  # quotesinglbase
    131: "\u0192",  # florin
    132: "\u201e",  # quotedblbase
    133: "\u2026",  # ellipsis
    134: "\u2020",  # dagger
    135: "\u2021",  # daggerdbl
    136: "\u02c6",  # circumflex
    137: "\u2030",  # perthousand
    138: "\u0160",  # Scaron
    139: "\u2039",  # guilsinglleft
    140: "\u0152",  # OE
    142: "\u017d",  # Zcaron
    145: "\u2018",  # quoteleft
    146: "\u2019",  # quoteright
    147: "\u201c",  # quotedblleft
    148: "\u201d",  # quotedblright
    149: "\u2022",  # bullet
    150: "\u2013",  # endash
    151: "\u2014",  # emdash
    152: "\u02dc",  # tilde
    153: "\u2122",  # trademark
    154: "\u0161",  # scaron
    155: "\u203a",  # guilsinglright
    156: "\u0153",  # oe
    158: "\u017e",  # zcaron
    159: "\u0178",  # Ydieresis
})
# 160..255 ISO 8859-1 Latin-1
for c in range(160, 256):
    WIN_ANSI_ENCODING[c] = chr(c)

# MacRomanEncoding (Mac OS Roman)
MAC_ROMAN_ENCODING: Dict[int, str] = dict(_ASCII_BASE)
_MAC_ROMAN_EXTENSIONS: Dict[int, str] = {
    128: "\u00c4", 129: "\u00c5", 130: "\u00c7", 131: "\u00c9", 132: "\u00d1", 133: "\u00d6", 134: "\u00dc", 135: "\u00e1",
    136: "\u00e0", 137: "\u00e2", 138: "\u00e4", 139: "\u00e3", 140: "\u00e5", 141: "\u00e7", 142: "\u00e9", 143: "\u00e8",
    144: "\u00ea", 145: "\u00eb", 146: "\u00ed", 147: "\u00ec", 148: "\u00ee", 149: "\u00ef", 150: "\u00f1", 151: "\u00f3",
    152: "\u00f2", 153: "\u00f4", 154: "\u00f6", 155: "\u00f5", 156: "\u00fa", 157: "\u00f9", 158: "\u00fb", 159: "\u00fc",
    160: "\u2020", 161: "\u00b0", 162: "\u00a2", 163: "\u00a3", 164: "\u00a7", 165: "\u2022", 166: "\u00b6", 167: "\u00df",
    168: "\u00ae", 169: "\u00a9", 170: "\u2122", 171: "\u00b4", 172: "\u00a8", 173: "\u2260", 174: "\u00c6", 175: "\u00d8",
    176: "\u221e", 177: "\u00b1", 178: "\u2264", 179: "\u2265", 180: "\u00a5", 181: "\u00b5", 182: "\u2202", 183: "\u2211",
    184: "\u220f", 185: "\u03c0", 186: "\u222b", 187: "\u00aa", 188: "\u00ba", 189: "\u03a9", 190: "\u00e6", 191: "\u00f8",
    192: "\u00bf", 193: "\u00a1", 194: "\u00ac", 195: "\u221a", 196: "\u0192", 197: "\u2248", 198: "\u2206", 199: "\u00ab",
    200: "\u00bb", 201: "\u2026", 202: "\u00a0", 203: "\u00c0", 204: "\u00c3", 205: "\u00d5", 206: "\u0152", 207: "\u0153",
    208: "\u2013", 209: "\u2014", 210: "\u201c", 211: "\u201d", 212: "\u2018", 213: "\u2019", 214: "\u00f7", 215: "\u25ca",
    216: "\u00ff", 217: "\u0178", 218: "\u2044", 219: "\u20ac", 220: "\u2039", 221: "\u203a", 222: "\ufb01", 223: "\ufb02",
    224: "\u2021", 225: "\u00b7", 226: "\u201a", 227: "\u201e", 228: "\u2030", 229: "\u00c2", 230: "\u00ca", 231: "\u00c1",
    232: "\u00cb", 233: "\u00c8", 234: "\u00cd", 235: "\u00ce", 236: "\u00cf", 237: "\u00cc", 238: "\u00d3", 239: "\u00d4",
    240: "\uf8ff", 241: "\u00d2", 242: "\u00da", 243: "\u00db", 244: "\u00d9", 245: "\u0131", 246: "\u02c6", 247: "\u02dc",
    248: "\u00af", 249: "\u02d8", 250: "\u02d9", 251: "\u02da", 252: "\u00b8", 253: "\u02dd", 254: "\u02db", 255: "\u02c7",
}
MAC_ROMAN_ENCODING.update(_MAC_ROMAN_EXTENSIONS)

# StandardEncoding (PostScript Standard Encoding)
STANDARD_ENCODING: Dict[int, str] = dict(_ASCII_BASE)
STANDARD_ENCODING[39] = "\u2019"  # quoteright
STANDARD_ENCODING[96] = "\u2018"  # quoteleft
_STANDARD_EXTENSIONS: Dict[int, str] = {
    161: "\u00a1", 162: "\u00a2", 163: "\u00a3", 164: "\u2044", 165: "\u00a5", 166: "\u0192", 167: "\u00a7", 168: "\u00a4",
    169: "'", 170: "\u201c", 171: "\u00ab", 172: "\u2039", 173: "\u203a", 174: "\ufb01", 175: "\ufb02",
    177: "\u2013", 178: "\u2020", 179: "\u2021", 180: "\u00b7", 182: "\u00b6", 183: "\u2022", 184: "\u201a", 185: "\u201e",
    186: "\u201d", 187: "\u00bb", 188: "\u2026", 189: "\u2030", 191: "\u00bf", 193: "`", 194: "\u00b4", 195: "^",
    196: "~", 197: "\u00af", 198: "\u02d8", 199: "\u02d9", 200: "\u00a8", 202: "\u02da", 203: "\u00b8", 205: "\u02dd",
    206: "\u02db", 207: "\u02c7", 208: "\u2014", 225: "\u00c6", 227: "\u00aa", 232: "\u0141", 233: "\u00d8", 234: "\u0152",
    235: "\u00ba", 241: "\u00e6", 245: "\u0131", 248: "\u0142", 249: "\u00f8", 250: "\u0153", 251: "\u00df",
}
STANDARD_ENCODING.update(_STANDARD_EXTENSIONS)

# PDFDocEncoding (ISO 32000-1 Table D.2)
PDF_DOC_ENCODING: Dict[int, str] = dict(_ASCII_BASE)
PDF_DOC_ENCODING.update({
    24: "\u02d8", 25: "\u02c7", 26: "\u02c6", 27: "\u02d9", 28: "\u02dd", 29: "\u02db", 30: "\u02da", 31: "\u02dc",
    128: "\u2022", 129: "\u2020", 130: "\u2021", 131: "\u2026", 132: "\u2014", 133: "\u2013", 134: "\u0192", 135: "\u2044",
    136: "\u2039", 137: "\u203a", 138: "\u2212", 139: "\u2030", 140: "\u201e", 141: "\u201c", 142: "\u201d", 143: "\u2018",
    144: "\u2019", 145: "\u201a", 146: "\u2122", 147: "\ufb01", 148: "\ufb02", 149: "\u0141", 150: "\u0152", 151: "\u0160",
    152: "\u0178", 153: "\u017d", 154: "\u0131", 155: "\u0142", 156: "\u0153", 157: "\u0161", 158: "\u017e", 160: "\u20ac",
})
for c in range(161, 256):
    PDF_DOC_ENCODING[c] = chr(c)

# SymbolEncoding (ISO 32000-1 Table D.3)
SYMBOL_ENCODING: Dict[int, str] = {
    32: " ", 33: "!", 34: "\u2200", 35: "#", 36: "\u2203", 37: "%", 38: "&", 39: "\u220d", 40: "(", 41: ")",
    42: "\u2217", 43: "+", 44: ",", 45: "\u2212", 46: ".", 47: "/", 48: "0", 49: "1", 50: "2", 51: "3", 52: "4",
    53: "5", 54: "6", 55: "7", 56: "8", 57: "9", 58: ":", 59: ";", 60: "<", 61: "=", 62: ">", 63: "?",
    64: "\u2245", 65: "\u0391", 66: "\u0392", 67: "\u03a7", 68: "\u0394", 69: "\u0395", 70: "\u03a6", 71: "\u0393",
    72: "\u0397", 73: "\u0399", 74: "\u03d1", 75: "\u039a", 76: "\u039b", 77: "\u039c", 78: "\u039d", 79: "\u039f",
    80: "\u03a0", 81: "\u0398", 82: "\u03a1", 83: "\u03a3", 84: "\u03a4", 85: "\u03a5", 86: "\u03c2", 87: "\u03a9",
    88: "\u039e", 89: "\u03a8", 90: "\u0396", 91: "[", 92: "\u2234", 93: "]", 94: "\u22a5", 95: "_", 96: "\u05be",
    97: "\u03b1", 98: "\u03b2", 99: "\u03c7", 100: "\u03b4", 101: "\u03b5", 102: "\u03c6", 103: "\u03b3", 104: "\u03b7",
    105: "\u03b9", 106: "\u03d5", 107: "\u03ba", 108: "\u03bb", 109: "\u03bc", 110: "\u03bd", 111: "\u03bf", 112: "\u03c0",
    113: "\u03b8", 114: "\u03c1", 115: "\u03c3", 116: "\u03c4", 117: "\u03c5", 118: "\u03d6", 119: "\u03c9", 120: "\u03be",
    121: "\u03c8", 122: "\u03b6", 123: "{", 124: "|", 125: "}", 126: "~",
    161: "\u03d2", 162: "\u2032", 163: "\u2264", 164: "\u2044", 165: "\u221e", 166: "\u0192", 167: "\u2663", 168: "\u2666",
    169: "\u2665", 170: "\u2660", 171: "\u2194", 172: "\u2190", 173: "\u2191", 174: "\u2192", 175: "\u2193", 176: "\u00b0",
    177: "\u00b1", 178: "\u2033", 179: "\u2265", 180: "\u00d7", 181: "\u221d", 182: "\u2202", 183: "\u2022", 184: "\u00f7",
    185: "\u2260", 186: "\u2261", 187: "\u2248", 188: "\u2026", 193: "\u2135", 194: "\u2111", 195: "\u211c", 196: "\u2118",
    197: "\u2297", 198: "\u2295", 199: "\u2205", 200: "\u2229", 201: "\u222a", 202: "\u2283", 203: "\u2287", 204: "\u2284",
    205: "\u2282", 206: "\u2286", 207: "\u2208", 208: "\u2209", 209: "\u2220", 210: "\u2207", 211: "\u00ae", 212: "\u00a9",
    213: "\u2122", 214: "\u220f", 215: "\u221a", 216: "\u22c5", 217: "\u00ac", 218: "\u2227", 219: "\u2228", 220: "\u21d4",
    221: "\u21d0", 222: "\u21d1", 223: "\u21d2", 224: "\u21d3", 225: "\u25ca", 226: "\u3008", 228: "\u00ae", 229: "\u00a9",
    230: "\u2122", 231: "\u2211", 242: "\u222b",
}

# ZapfDingbatsEncoding (ISO 32000-1 Table D.4)
ZAPF_DINGBATS_ENCODING: Dict[int, str] = {
    32: " ", 33: "\u2701", 34: "\u2702", 35: "\u2703", 36: "\u2704", 37: "\u260e", 38: "\u2706", 39: "\u2707",
    40: "\u2708", 41: "\u2709", 42: "\u270a", 43: "\u270b", 44: "\u270c", 45: "\u270d", 46: "\u270e", 47: "\u270f",
    48: "\u2710", 49: "\u2711", 50: "\u2712", 51: "\u2713", 52: "\u2714", 53: "\u2715", 54: "\u2716", 55: "\u2717",
    56: "\u2718", 57: "\u2719", 58: "\u271a", 59: "\u271b", 60: "\u271c", 61: "\u271d", 62: "\u271e", 63: "\u271f",
    64: "\u2720", 65: "\u2721", 66: "\u2722", 67: "\u2723", 68: "\u2724", 69: "\u2725", 70: "\u2726", 71: "\u2727",
    72: "\u2728", 73: "\u2729", 74: "\u272a", 75: "\u272b", 76: "\u272c", 77: "\u272d", 78: "\u272e", 79: "\u272f",
    80: "\u2730", 81: "\u2731", 82: "\u2732", 83: "\u2733", 84: "\u2734", 85: "\u2735", 86: "\u2736", 87: "\u2737",
    88: "\u2738", 89: "\u2739", 90: "\u273a", 91: "\u273b", 92: "\u273c", 93: "\u273d", 94: "\u273e", 95: "\u273f",
    96: "\u2740", 97: "\u2741", 98: "\u2742", 99: "\u2743", 100: "\u2744", 101: "\u2745", 102: "\u2746", 103: "\u2747",
    104: "\u2748", 105: "\u2749", 106: "\u274a", 107: "\u274b", 108: "\u25cf", 109: "\u274d", 110: "\u25a0", 111: "\u274f",
    112: "\u2750", 113: "\u2751", 114: "\u2752", 115: "\u25b2", 116: "\u25bc", 117: "\u25c6", 118: "\u2756", 119: "\u25d7",
    120: "\u2758", 121: "\u2759", 122: "\u275a", 123: "\u275b", 124: "\u275c", 125: "\u275d", 126: "\u275e",
    161: "\u2761", 162: "\u2762", 163: "\u2763", 164: "\u2764", 165: "\u2765", 166: "\u2766", 167: "\u2767", 168: "\u2663",
    169: "\u2666", 170: "\u2665", 171: "\u2660", 172: "\u2460", 173: "\u2461", 174: "\u2462", 175: "\u2463", 176: "\u2464",
    177: "\u2465", 178: "\u2466", 179: "\u2467", 180: "\u2468", 181: "\u2469", 182: "\u2776", 183: "\u2777", 184: "\u2778",
    185: "\u2779", 186: "\u277a", 187: "\u277b", 188: "\u277c", 189: "\u277d", 190: "\u277e", 191: "\u277f", 192: "\u2780",
    193: "\u2781", 194: "\u2782", 195: "\u2783", 196: "\u2784", 197: "\u2785", 198: "\u2786", 199: "\u2787", 200: "\u2788",
    201: "\u2789", 202: "\u278a", 203: "\u278b", 204: "\u278c", 205: "\u278d", 206: "\u278e", 207: "\u278f", 208: "\u2790",
    209: "\u2791", 210: "\u2792", 211: "\u2793", 212: "\u2794", 213: "\u2192", 214: "\u2194", 215: "\u2195", 216: "\u2799",
    217: "\u279a", 218: "\u279b", 219: "\u279c", 220: "\u279d", 221: "\u279e", 222: "\u279f", 223: "\u27a0", 224: "\u27a1",
    225: "\u27a2", 226: "\u27a3", 227: "\u27a4", 228: "\u27a5", 229: "\u27a6", 230: "\u27a7", 231: "\u27a8", 232: "\u27a9",
    233: "\u27aa", 234: "\u27ab", 235: "\u27ac", 236: "\u27ad", 237: "\u27ae", 238: "\u27af", 239: "\u27b1", 241: "\u27b2",
    242: "\u27b3", 243: "\u27b4", 244: "\u27b5", 245: "\u27b6", 246: "\u27b7", 247: "\u27b8", 248: "\u27b9", 249: "\u27ba",
    250: "\u27bb", 251: "\u27bc", 252: "\u27bd", 253: "\u27be", 254: "\u27bf",
}


# ==============================================================================
# 2. Adobe Glyph List (AGL) Core Map & Dynamic Resolver
# ==============================================================================

ADOBE_GLYPH_LIST: Dict[str, str] = {
    "space": " ", "exclam": "!", "quotedbl": '"', "numbersign": "#", "dollar": "$",
    "percent": "%", "ampersand": "&", "quotesingle": "'", "parenleft": "(", "parenright": ")",
    "asterisk": "*", "plus": "+", "comma": ",", "hyphen": "-", "period": ".", "slash": "/",
    "colon": ":", "semicolon": ";", "less": "<", "equal": "=", "greater": ">", "question": "?",
    "at": "@", "bracketleft": "[", "backslash": "\\", "bracketright": "]", "asciicircum": "^",
    "underscore": "_", "grave": "`", "braceleft": "{", "bar": "|", "braceright": "}", "asciitilde": "~",
    # Ligatures
    "fi": "\ufb01", "fl": "\ufb02", "ff": "\ufb00", "ffi": "\ufb03", "ffl": "\ufb04", "st": "\ufb06",
    # Quotes & Punctuation
    "bullet": "\u2022", "emdash": "\u2014", "endash": "\u2013", "ellipsis": "\u2026",
    "quoteleft": "\u2018", "quoteright": "\u2019", "quotedblleft": "\u201c", "quotedblright": "\u201d",
    "quotesinglbase": "\u201a", "quotedblbase": "\u201e", "guilsinglleft": "\u2039", "guilsinglright": "\u203a",
    "guillemotleft": "\u00ab", "guillemotright": "\u00bb", "dagger": "\u2020", "daggerdbl": "\u2021",
    "periodcentered": "\u00b7", "paragraph": "\u00b6", "section": "\u00a7", "exclamdown": "\u00a1",
    "questiondown": "\u00bf", "fraction": "\u2044", "perthousand": "\u2030", "minute": "\u2032", "second": "\u2033",
    # Currency
    "Euro": "\u20ac", "cent": "\u00a2", "sterling": "\u00a3", "yen": "\u00a5", "currency": "\u00a4", "florin": "\u0192",
    # Marks & Symbols
    "copyright": "\u00a9", "registered": "\u00ae", "trademark": "\u2122", "degree": "\u00b0", "plusminus": "\u00b1",
    "multiply": "\u00d7", "divide": "\u00f7", "minus": "\u2212", "equal": "=", "logicalnot": "\u00ac",
    "acute": "\u00b4", "circumflex": "\u02c6", "tilde": "\u02dc", "macron": "\u00af", "breve": "\u02d8",
    "dotaccent": "\u02d9", "dieresis": "\u00a8", "ring": "\u02da", "cedilla": "\u00b8", "hungarumlaut": "\u02dd",
    "ogonek": "\u02db", "caron": "\u02c7",
    # Latin Ligatures & Extended Characters
    "AE": "\u00c6", "ae": "\u00e6", "OE": "\u0152", "oe": "\u0153", "germandbls": "\u00df",
    "Lslash": "\u0141", "lslash": "\u0142", "Oslash": "\u00d8", "oslash": "\u00f8",
    "Scaron": "\u0160", "scaron": "\u0161", "Zcaron": "\u017d", "zcaron": "\u017e",
    "Ydieresis": "\u0178", "ydieresis": "\u00ff", "dotlessi": "\u0131",
    "ordfeminine": "\u00aa", "ordmasculine": "\u00ba",
    # Accented letters
    "Agrave": "\u00c0", "Aacute": "\u00c1", "Acircumflex": "\u00c2", "Atilde": "\u00c3", "Adieresis": "\u00c4", "Aring": "\u00c5",
    "Ccedilla": "\u00c7", "Egrave": "\u00c8", "Eacute": "\u00c9", "Ecircumflex": "\u00ca", "Edieresis": "\u00cb",
    "Igrave": "\u00cc", "Iacute": "\u00cd", "Icircumflex": "\u00ce", "Idieresis": "\u00cf", "Eth": "\u00d0", "Ntilde": "\u00d1",
    "Ograve": "\u00d2", "Oacute": "\u00d3", "Ocircumflex": "\u00d4", "Otilde": "\u00d5", "Odieresis": "\u00d6",
    "Ugrave": "\u00d9", "Uacute": "\u00da", "Ucircumflex": "\u00db", "Udieresis": "\u00dc", "Yacute": "\u00dd", "Thorn": "\u00de",
    "agrave": "\u00e0", "aacute": "\u00e1", "acircumflex": "\u00e2", "atilde": "\u00e3", "adieresis": "\u00e4", "aring": "\u00e5",
    "ccedilla": "\u00e7", "egrave": "\u00e8", "eacute": "\u00e9", "ecircumflex": "\u00ea", "edieresis": "\u00eb",
    "igrave": "\u00ec", "iacute": "\u00ed", "icircumflex": "\u00ee", "idieresis": "\u00ef", "eth": "\u00f0", "ntilde": "\u00f1",
    "ograve": "\u00f2", "oacute": "\u00f3", "ocircumflex": "\u00f4", "otilde": "\u00f5", "odieresis": "\u00f6",
    "ugrave": "\u00f9", "uacute": "\u00fa", "ucircumflex": "\u00fb", "udieresis": "\u00fc", "yacute": "\u00fd", "thorn": "\u00fe",
}
# Populate basic letters a..z, A..Z, 0..9
for ch in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
    ADOBE_GLYPH_LIST[ch] = ch


def glyph_name_to_unicode(name: str) -> Optional[str]:
    """Convert PostScript glyph name to Unicode string using AGL and algorithmic rules.

    Supports:
    1. Static Adobe Glyph List lookup (e.g., 'bullet' -> '•', 'fi' -> 'ﬁ').
    2. Variant suffixes (e.g., 'A.swash' -> 'A', 'e.alt' -> 'e').
    3. uniXXXX syntax (e.g., 'uni0041' -> 'A', 'uni0152' -> 'Œ', 'uni00460046' -> 'FF').
    4. uXXXX / uXXXXX / uXXXXXX syntax (e.g., 'u0041' -> 'A', 'u1F600' -> '😀').

    Args:
        name: PostScript glyph name string.

    Returns:
        Optional[str]: Mapped Unicode string, or None if unknown.
    """
    if not name or name == ".notdef":
        return None

    # 1. Direct AGL lookup
    if name in ADOBE_GLYPH_LIST:
        return ADOBE_GLYPH_LIST[name]

    # 2. Strip variant suffix (e.g. 'A.sc' -> 'A')
    if "." in name:
        base_name = name.split(".", 1)[0]
        if base_name in ADOBE_GLYPH_LIST:
            return ADOBE_GLYPH_LIST[base_name]
        # Also try uniXXXX on the base
        res = glyph_name_to_unicode(base_name)
        if res is not None:
            return res

    # 3. Algorithmic uniXXXX (multiples of 4 hex digits)
    if name.startswith("uni") and len(name) >= 7 and (len(name) - 3) % 4 == 0:
        hex_part = name[3:]
        chars: list[str] = []
        try:
            for i in range(0, len(hex_part), 4):
                val = int(hex_part[i : i + 4], 16)
                chars.append(chr(val))
            return "".join(chars)
        except ValueError:
            pass

    # 4. Algorithmic uXXXX / uXXXXX / uXXXXXX (4 to 6 hex digits)
    if name.startswith("u") and 5 <= len(name) <= 7:
        try:
            val = int(name[1:], 16)
            if 0 <= val <= 0x10FFFF:
                return chr(val)
        except ValueError:
            pass

    # Single-character fallback
    if len(name) == 1:
        return name

    return None


def get_base_encoding(name: Union[str, PDFName]) -> Dict[int, str]:
    """Return dictionary mapping for named base encoding.

    Args:
        name: Name of standard encoding.

    Returns:
        Dict[int, str]: Mapping from character code (0..255) to Unicode character.
    """
    encoding_name = name.name if isinstance(name, PDFName) else name
    if encoding_name.startswith("/"):
        encoding_name = encoding_name[1:]

    if encoding_name == "WinAnsiEncoding":
        return dict(WIN_ANSI_ENCODING)
    elif encoding_name == "MacRomanEncoding":
        return dict(MAC_ROMAN_ENCODING)
    elif encoding_name == "StandardEncoding":
        return dict(STANDARD_ENCODING)
    elif encoding_name == "PDFDocEncoding":
        return dict(PDF_DOC_ENCODING)
    elif encoding_name == "Symbol":
        return dict(SYMBOL_ENCODING)
    elif encoding_name == "ZapfDingbats":
        return dict(ZAPF_DINGBATS_ENCODING)

    # Standard default is StandardEncoding for Type 1, WinAnsi for TrueType
    return dict(WIN_ANSI_ENCODING)


def resolve_differences(
    base: Dict[int, str],
    differences: Sequence[Any],
    resolver: Optional[XRefResolver] = None,
) -> Dict[int, str]:
    """Apply PDF /Differences array to mutate base character mapping.

    Format per PDF 32000-1 §9.6.6:
    [ code1 /name1 /name2 ... code2 /name3 ... ]

    Args:
        base: Starting base encoding dictionary.
        differences: Sequence of integer starting codes and glyph names.
        resolver: Optional XRefResolver for indirect references.

    Returns:
        Dict[int, str]: Mutated character mapping.
    """
    mapping = dict(base)
    cur_code = 0

    for item in differences:
        resolved = resolver.dereference(item) if resolver is not None else item

        if isinstance(resolved, int):
            cur_code = resolved
        elif isinstance(resolved, (str, PDFName)):
            glyph_name = resolved.name if isinstance(resolved, PDFName) else resolved
            if glyph_name.startswith("/"):
                glyph_name = glyph_name[1:]

            u_char = glyph_name_to_unicode(glyph_name)
            if u_char is not None:
                mapping[cur_code] = u_char
            else:
                # Fallback: keep existing or use Latin-1 chr if code in 0..255
                if cur_code not in mapping and 0 <= cur_code <= 255:
                    mapping[cur_code] = chr(cur_code)

            cur_code += 1

    return mapping


class EncodingResolver:
    """Resolves font encoding specifications and differences to a character mapping."""

    __slots__ = ("_mapping",)

    def __init__(
        self,
        encoding_spec: Any,
        resolver: Optional[XRefResolver] = None,
        default_base: str = "WinAnsiEncoding",
    ) -> None:
        """Initialize EncodingResolver.

        Args:
            encoding_spec: /Encoding entry from font dictionary (Name, Dict, Array, or None).
            resolver: Optional XRefResolver.
            default_base: Default base encoding name if not specified.
        """
        self._mapping: Dict[int, str] = {}
        self._resolve(encoding_spec, resolver, default_base)

    @property
    def mapping(self) -> Dict[int, str]:
        """Return resolved mapping from character code to Unicode string."""
        return self._mapping

    def decode_char(self, code: int) -> str:
        """Decode single character code to Unicode string."""
        if code in self._mapping:
            return self._mapping[code]
        if 0 <= code <= 255:
            return chr(code)
        return "\ufffd"

    def _resolve(
        self,
        spec: Any,
        resolver: Optional[XRefResolver],
        default_base: str,
    ) -> None:
        """Resolve encoding specification into mapping."""
        resolved = resolver.dereference(spec) if resolver is not None else spec

        if resolved is None:
            self._mapping = get_base_encoding(default_base)
            return

        if isinstance(resolved, (str, PDFName)):
            self._mapping = get_base_encoding(resolved)
            return

        if isinstance(resolved, (list, PDFArray)):
            # Direct /Differences array
            base = get_base_encoding(default_base)
            self._mapping = resolve_differences(base, resolved, resolver)
            return

        if isinstance(resolved, PDFDict):
            # /Type /Encoding dictionary
            base_enc = resolved.get("BaseEncoding", default_base)
            base_map = get_base_encoding(base_enc)

            diffs = resolved.get("Differences")
            if diffs is not None:
                diffs_resolved = resolver.dereference(diffs) if resolver is not None else diffs
                if isinstance(diffs_resolved, (list, PDFArray)):
                    self._mapping = resolve_differences(base_map, diffs_resolved, resolver)
                    return

            self._mapping = base_map
            return

        self._mapping = get_base_encoding(default_base)
