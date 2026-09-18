"""Pure-Python implementation of the RC4 (ARC4) stream cipher.

Complies with standard RC4 specification:
- 256-byte S-box Key Scheduling Algorithm (KSA)
- Pseudo-Random Generation Algorithm (PRGA)
- Zero external dependencies
"""

from __future__ import annotations

from typing import Union


class RC4:
    """Pure-Python stateful RC4 stream cipher."""

    __slots__ = ("_s", "_i", "_j")

    def __init__(self, key: Union[bytes, bytearray, memoryview]) -> None:
        """Initialize RC4 state using the Key Scheduling Algorithm (KSA).

        Args:
            key: Secret key bytes (1 to 256 bytes).
        """
        key_bytes = bytes(key)
        key_len = len(key_bytes)
        if key_len == 0:
            raise ValueError("RC4 key cannot be empty")

        s = list(range(256))
        j = 0
        for i in range(256):
            j = (j + s[i] + key_bytes[i % key_len]) & 0xFF
            s[i], s[j] = s[j], s[i]

        self._s: list[int] = s
        self._i: int = 0
        self._j: int = 0

    def process(self, data: Union[bytes, bytearray, memoryview]) -> bytes:
        """Encrypt or decrypt data using the PRGA byte generator.

        Since RC4 is a symmetric stream cipher, encryption and decryption
        are identical XOR operations.

        Args:
            data: Input plaintext or ciphertext bytes.

        Returns:
            Processed bytes.
        """
        data_bytes = bytes(data)
        out = bytearray(len(data_bytes))
        s = self._s
        i = self._i
        j = self._j

        for idx, b in enumerate(data_bytes):
            i = (i + 1) & 0xFF
            j = (j + s[i]) & 0xFF
            s[i], s[j] = s[j], s[i]
            k = s[(s[i] + s[j]) & 0xFF]
            out[idx] = b ^ k

        self._i = i
        self._j = j
        return bytes(out)

    def encrypt(self, data: Union[bytes, bytearray, memoryview]) -> bytes:
        """Encrypt data."""
        return self.process(data)

    def decrypt(self, data: Union[bytes, bytearray, memoryview]) -> bytes:
        """Decrypt data."""
        return self.process(data)


def rc4_crypt(key: Union[bytes, bytearray, memoryview], data: Union[bytes, bytearray, memoryview]) -> bytes:
    """One-shot RC4 encryption / decryption.

    Args:
        key: Secret key bytes.
        data: Input bytes to transform.

    Returns:
        Transformed bytes.
    """
    cipher = RC4(key)
    return cipher.process(data)


__all__ = [
    "RC4",
    "rc4_crypt",
]
