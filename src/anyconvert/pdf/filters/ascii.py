"""ASCII stream decompression filters: ASCIIHexDecode and ASCII85Decode.

Adheres to PDF 32000-1 §7.4.2 and §7.4.3.
"""

from __future__ import annotations

from anyconvert.common.reader import PDF_WHITESPACE
from anyconvert.exceptions import PDFSyntaxError


def ascii_hex_decode(data: bytes) -> bytes:
    """Decode ASCIIHexDecode stream ignoring whitespace and handling odd-nibble padding.

    Args:
        data: Hex-encoded byte stream.

    Returns:
        bytes: Decoded binary data.

    Raises:
        PDFSyntaxError: If malformed hex characters are found.
    """
    hex_digits = bytearray()
    for b in data:
        if b == 0x3E:  # '>' indicates End of Data (EOD)
            break
        if b in PDF_WHITESPACE:
            continue
        if (0x30 <= b <= 0x39) or (0x41 <= b <= 0x46) or (0x61 <= b <= 0x66):
            hex_digits.append(b)
        else:
            raise PDFSyntaxError(f"Invalid character in ASCIIHexDecode stream: {chr(b)!r}")

    # If odd number of hex digits, pad with '0'
    if len(hex_digits) % 2 != 0:
        hex_digits.append(0x30)

    try:
        return bytes.fromhex(hex_digits.decode("ascii"))
    except ValueError as err:
        raise PDFSyntaxError(f"Failed to decode ASCIIHex stream: {err}") from err


def ascii_85_decode(data: bytes) -> bytes:
    """Decode ASCII85Decode (Radix-85) stream.

    Supports '<~' and '~>' delimiters, the 'z' zero-group exception byte,
    and partial final 5-tuples.

    Args:
        data: ASCII85 encoded byte sequence.

    Returns:
        bytes: Decoded binary data.

    Raises:
        PDFSyntaxError: If stream contains invalid Radix-85 characters or syntax.
    """
    # Strip optional <~ prefix
    raw = data
    if raw.startswith(b"<~"):
        raw = raw[2:]

    out = bytearray()
    group: list[int] = []

    i = 0
    length = len(raw)

    while i < length:
        b = raw[i]
        i += 1

        # Check for EOD delimiter '~>'
        if b == 0x7E:  # '~'
            if i < length and raw[i] == 0x3E:  # '>'
                break

        if b in PDF_WHITESPACE:
            continue

        # Special 'z' character represents 4 zero bytes
        if b == 0x7A:  # 'z'
            if len(group) != 0:
                raise PDFSyntaxError("'z' character inside partial ASCII85 5-tuple")
            out.extend(b"\x00\x00\x00\x00")
            continue

        # Valid ASCII85 character range: '!' (33) to 'u' (117)
        if 33 <= b <= 117:
            group.append(b - 33)
            if len(group) == 5:
                # Calculate 32-bit value
                val = (
                    group[0] * 52200625  # 85^4
                    + group[1] * 614125   # 85^3
                    + group[2] * 7225     # 85^2
                    + group[3] * 85       # 85^1
                    + group[4]
                )
                out.extend(val.to_bytes(4, "big"))
                group.clear()
        else:
            raise PDFSyntaxError(f"Invalid character in ASCII85 stream: {chr(b)!r}")

    # Process remaining partial group
    k = len(group)
    if k > 0:
        if k == 1:
            raise PDFSyntaxError("Single character remaining in ASCII85 stream")
        # Pad with 84 ('u' - 33) to make 5 characters
        pad_count = 5 - k
        for _ in range(pad_count):
            group.append(84)

        val = (
            group[0] * 52200625
            + group[1] * 614125
            + group[2] * 7225
            + group[3] * 85
            + group[4]
        )
        full_bytes = val.to_bytes(4, "big")
        # Emit only k - 1 bytes
        out.extend(full_bytes[: k - 1])

    return bytes(out)
