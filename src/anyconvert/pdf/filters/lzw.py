"""Pure-Python LZWDecode stream decompression filter.

Adheres to PDF 32000-1 §7.4.4 with dynamic 9-12 bit code sizing,
clear table (256), end of data (257), and EarlyChange parameter support.
"""

from __future__ import annotations

from typing import List, Union

from anyconvert.common.reader import BitReader, ByteReader
from anyconvert.exceptions import PDFSyntaxError


def lzw_decode(data: bytes, early_change: int = 1) -> bytes:
    """Decompress LZW encoded byte stream.

    Args:
        data: Compressed LZW stream.
        early_change: 1 (default for PDF) or 0 (standard TIFF/GIF behavior).

    Returns:
        bytes: Decompressed binary data.

    Raises:
        PDFSyntaxError: If stream contains corrupt LZW codes.
    """
    if not data:
        return b""

    bit_reader = BitReader(data, msb_first=True)
    out = bytearray()

    def reset_table() -> list[bytes]:
        # Entries 0-255 are 1-byte strings, 256 is ClearTable, 257 is EOD
        return [bytes([i]) for i in range(256)] + [b"", b""]

    table = reset_table()
    code_len = 9
    prev_entry = b""

    while not bit_reader.is_eof:
        try:
            code = bit_reader.read_bits(code_len)
        except EOFError:
            # End of stream without explicit EOD
            break

        if code == 257:  # End of Data (EOD)
            break

        if code == 256:  # Clear Table
            table = reset_table()
            code_len = 9
            prev_entry = b""

            # Read first code following 256
            if bit_reader.is_eof:
                break
            try:
                code = bit_reader.read_bits(code_len)
            except EOFError:
                break

            if code == 257:
                break

            if code >= len(table):
                raise PDFSyntaxError(f"Invalid code {code} following clear table code")

            entry = table[code]
            out.extend(entry)
            prev_entry = entry
            continue

        if prev_entry == b"":
            # First code of the stream
            if code >= len(table):
                raise PDFSyntaxError(f"Invalid initial code {code}")
            entry = table[code]
            out.extend(entry)
            prev_entry = entry
            continue

        if code < len(table):
            entry = table[code]
            out.extend(entry)
            # Add to dictionary: prev_entry + entry[0]
            if len(table) < 4096:
                table.append(prev_entry + entry[:1])
        elif code == len(table):
            # Special case: code equals next dictionary index
            entry = prev_entry + prev_entry[:1]
            out.extend(entry)
            if len(table) < 4096:
                table.append(entry)
        else:
            raise PDFSyntaxError(f"LZW code {code} exceeds dictionary size {len(table)}")

        prev_entry = entry

        # Check for code size expansion
        # If early_change == 1: expand when next entry index reaches (1 << code_len) - 1
        # If early_change == 0: expand when next entry index reaches (1 << code_len)
        threshold = (1 << code_len) - 1 if early_change == 1 else (1 << code_len)
        if len(table) >= threshold and code_len < 12:
            code_len += 1

    return bytes(out)
