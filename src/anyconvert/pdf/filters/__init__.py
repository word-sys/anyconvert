"""PDF stream decompression filter pipeline and dispatcher.

Provides zero-dependency decompression for:
- /FlateDecode (Fl / FlateDecode) with TIFF 2 and PNG 10-15 predictors.
- /LZWDecode (LZW / LZWDecode) with dynamic 9-12 bit coding and EarlyChange.
- /ASCII85Decode (A85 / ASCII85Decode).
- /ASCIIHexDecode (AHx / ASCIIHexDecode).
- /RunLengthDecode (RL / RunLengthDecode).
- Multi-stage filter pipelines.
"""

from __future__ import annotations

from typing import Any, List, Optional, Union

from anyconvert.exceptions import PDFUnsupportedFilterError
from anyconvert.pdf.filters.ascii import ascii_85_decode, ascii_hex_decode
from anyconvert.pdf.filters.flate import apply_predictor_reversal, flate_decode
from anyconvert.pdf.filters.lzw import lzw_decode
from anyconvert.pdf.filters.runlength import run_length_decode
from anyconvert.pdf.parser import PDFArray, PDFDict, PDFName

# Filter abbreviation and standard name mappings
_FILTER_MAP = {
    "FlateDecode": "FlateDecode",
    "Fl": "FlateDecode",
    "/FlateDecode": "FlateDecode",
    "/Fl": "FlateDecode",
    "LZWDecode": "LZWDecode",
    "LZW": "LZWDecode",
    "/LZWDecode": "LZWDecode",
    "/LZW": "LZWDecode",
    "ASCII85Decode": "ASCII85Decode",
    "A85": "ASCII85Decode",
    "/ASCII85Decode": "ASCII85Decode",
    "/A85": "ASCII85Decode",
    "ASCIIHexDecode": "ASCIIHexDecode",
    "AHx": "ASCIIHexDecode",
    "/ASCIIHexDecode": "ASCIIHexDecode",
    "/AHx": "ASCIIHexDecode",
    "RunLengthDecode": "RunLengthDecode",
    "RL": "RunLengthDecode",
    "/RunLengthDecode": "RunLengthDecode",
    "/RL": "RunLengthDecode",
    "DCTDecode": "DCTDecode",
    "DCT": "DCTDecode",
    "/DCTDecode": "DCTDecode",
    "/DCT": "DCTDecode",
}


def decode_stream(
    data: bytes,
    filter_spec: Any,
    params_spec: Any = None,
) -> bytes:
    """Decompress a stream according to its /Filter and /DecodeParms specifications.

    Supports single filter names, PDFNames, or sequential pipeline lists of filters.

    Args:
        data: Compressed raw stream data.
        filter_spec: Filter name (str, PDFName) or sequence of filter names.
        params_spec: Optional /DecodeParms (PDFDict) or sequence of parameter dicts.

    Returns:
        bytes: Fully decompressed binary payload.

    Raises:
        PDFUnsupportedFilterError: If a requested filter is unsupported.
    """
    if not filter_spec:
        return data

    # Normalize filter list
    filter_list: List[str] = []
    if isinstance(filter_spec, (list, PDFArray)):
        for item in filter_spec:
            f_name = item.name if isinstance(item, PDFName) else str(item)
            filter_list.append(f_name)
    elif isinstance(filter_spec, PDFName):
        filter_list.append(filter_spec.name)
    else:
        filter_list.append(str(filter_spec))

    # Normalize params list
    params_list: List[Optional[PDFDict]] = []
    if isinstance(params_spec, (list, PDFArray)):
        for p in params_spec:
            params_list.append(p if isinstance(p, PDFDict) else None)
    elif isinstance(params_spec, PDFDict):
        params_list = [params_spec] * len(filter_list)
    else:
        params_list = [None] * len(filter_list)

    # Pad params_list to match filter_list length
    while len(params_list) < len(filter_list):
        params_list.append(None)

    # Process filters sequentially in the order specified in the PDF stream dictionary
    current_data = data
    for f_raw, p_dict in zip(filter_list, params_list):
        f_clean = _FILTER_MAP.get(f_raw)
        if f_clean is None:
            clean_str = f_raw[1:] if f_raw.startswith("/") else f_raw
            f_clean = _FILTER_MAP.get(clean_str)

        if f_clean == "FlateDecode":
            current_data = flate_decode(current_data, params=p_dict)
        elif f_clean == "LZWDecode":
            early_change = 1
            if p_dict is not None:
                early_change = int(p_dict.get("EarlyChange", 1))
            current_data = lzw_decode(current_data, early_change=early_change)
            if p_dict is not None and "Predictor" in p_dict:
                # Apply predictor if specified on LZW
                predictor = int(p_dict.get("Predictor", 1))
                if predictor > 1:
                    columns = int(p_dict.get("Columns", 1))
                    colors = int(p_dict.get("Colors", 1))
                    bpc = int(p_dict.get("BitsPerComponent", 8))
                    current_data = apply_predictor_reversal(
                        current_data, predictor, columns, colors, bpc
                    )
        elif f_clean == "ASCII85Decode":
            current_data = ascii_85_decode(current_data)
        elif f_clean == "ASCIIHexDecode":
            current_data = ascii_hex_decode(current_data)
        elif f_clean == "RunLengthDecode":
            current_data = run_length_decode(current_data)
        elif f_clean == "DCTDecode":
            # DCTDecode is JPEG; raw stream bytes are already standard JPEG
            continue
        else:
            raise PDFUnsupportedFilterError(filter_name=f_raw)

    return current_data


__all__ = [
    "ascii_hex_decode",
    "ascii_85_decode",
    "run_length_decode",
    "lzw_decode",
    "flate_decode",
    "apply_predictor_reversal",
    "decode_stream",
]
