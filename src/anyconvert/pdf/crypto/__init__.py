"""Pure-Python cryptographic engine and standard PDF security handlers."""

from __future__ import annotations

from anyconvert.pdf.crypto.aes import (
    aes_decrypt_cbc,
    aes_encrypt_cbc,
    decrypt_block,
    encrypt_block,
    key_expansion,
)
from anyconvert.pdf.crypto.handler import (
    PASSWORD_PADDING,
    StandardSecurityHandler,
)
from anyconvert.pdf.crypto.rc4 import (
    RC4,
    rc4_crypt,
)

__all__ = [
    "RC4",
    "rc4_crypt",
    "key_expansion",
    "encrypt_block",
    "decrypt_block",
    "aes_decrypt_cbc",
    "aes_encrypt_cbc",
    "PASSWORD_PADDING",
    "StandardSecurityHandler",
]
