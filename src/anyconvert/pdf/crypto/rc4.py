"""Pure-Python RC4 (ARC4) stream cipher implementation.

Implements RC4 stream cipher (40 to 128 bit key) adhering to RFC 6229 and PDF 32000-1 §7.6.
Uses Key-Scheduling Algorithm (KSA) and Pseudo-Random Generation Algorithm (PRGA).
"""

from __future__ import annotations

from typing import Union


class RC4:
    """Pure-Python RC4 stream cipher state machine."""

    __slots__ = ("_s", "_i", "_j")

    def __init__(self, key: Union[bytes, bytearray, memoryview]) -> None:
        """Initialize RC4 cipher with key.

        Args:
            key: Secret key (1 to 256 bytes, typically 5 to 16 bytes for 40-128 bits).

        Raises:
            ValueError: If key is empty.
        """
        key_bytes = bytes(key)
        key_len = len(key_bytes)
        if key_len == 0 or key_len > 256:
            raise ValueError(f"RC4 key length must be between 1 and 256 bytes, got {key_len}")

        # Key-Scheduling Algorithm (KSA)
        s = list(range(256))
        j = 0
        for i in range(256):
            j = (j + s[i] + key_bytes[i % key_len]) & 0xFF
            s[i], s[j] = s[j], s[i]

        self._s: list[int] = s
        self._i: int = 0
        self._j: int = 0

    def process(self, data: Union[bytes, bytearray, memoryview]) -> bytes:
        """Encrypt or decrypt data (RC4 is symmetric).

        Args:
            data: Input byte sequence.

        Returns:
            bytes: Encrypted or decrypted byte sequence.
        """
        input_bytes = bytes(data)
        out = bytearray(len(input_bytes))
        s = self._s
        i = self._i
        j = self._j

        for idx, byte in enumerate(input_bytes):
            i = (i + 1) & 0xFF
            j = (j + s[i]) & 0xFF
            s[i], s[j] = s[j], s[i]
            k = s[(s[i] + s[j]) & 0xFF]
            out[idx] = byte ^ k

        self._i = i
        self._j = j
        return bytes(out)

    def encrypt(self, plaintext: Union[bytes, bytearray, memoryview]) -> bytes:
        """Encrypt plaintext."""
        return self.process(plaintext)

    def decrypt(self, ciphertext: Union[bytes, bytearray, memoryview]) -> bytes:
        """Decrypt ciphertext."""
        return self.process(ciphertext)


def rc4_crypt(
    key: Union[bytes, bytearray, memoryview], data: Union[bytes, bytearray, memoryview]
) -> bytes:
    """One-shot RC4 encryption/decryption.

    Args:
        key: Encryption key.
        data: Input payload.

    Returns:
        bytes: Output payload.
    """
    cipher = RC4(key)
    return cipher.process(data)
