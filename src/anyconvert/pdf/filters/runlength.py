"""RunLengthDecode (PackBits) stream decompression filter.

Adheres to PDF 32000-1 §7.4.5.
"""

from __future__ import annotations

from anyconvert.exceptions import PDFSyntaxError


def run_length_decode(data: bytes) -> bytes:
    """Decompress PackBits (RunLengthDecode) stream data.

    Args:
        data: Compressed byte stream.

    Returns:
        bytes: Decompressed binary data.

    Raises:
        PDFSyntaxError: If stream terminates unexpectedly mid-packet.
    """
    out = bytearray()
    i = 0
    length = len(data)

    while i < length:
        length_byte = data[i]
        i += 1

        if length_byte == 128:  # End of Data (EOD)
            break
        elif length_byte < 128:  # Literal copy: length_byte + 1 bytes
            count = length_byte + 1
            if i + count > length:
                # Truncated literal run: copy available
                out.extend(data[i:length])
                break
            out.extend(data[i : i + count])
            i += count
        else:  # Repeated byte: (257 - length_byte) times
            count = 257 - length_byte
            if i >= length:
                break
            repeated_byte = data[i]
            i += 1
            out.extend(bytes([repeated_byte] * count))

    return bytes(out)
