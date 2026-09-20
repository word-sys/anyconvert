"""PDF Standard Security Handler implementation.

Supports PDF standard encryption Revisions 2, 3, 4, 5, and 6:
- User and Owner password authentication.
- Key derivation via MD5, SHA-256, and multi-round hashing loops.
- Object-level key derivation (Algorithm 1).
- RC4 (40-128 bit) and AES (128/256 bit CBC) decryption for strings and streams.
"""

from __future__ import annotations

import hashlib
import struct
from typing import Any, Optional, Sequence, Union

from anyconvert.exceptions import PDFPasswordRequiredError, PDFSecurityError
from anyconvert.pdf.crypto.aes import (
    AES,
    aes_decrypt_cbc_with_iv,
)
from anyconvert.pdf.crypto.rc4 import rc4_crypt
from anyconvert.pdf.parser import (
    PDFArray,
    PDFDict,
    PDFHexString,
    PDFName,
    PDFString,
)

# Standard 32-byte password padding specified in PDF 32000-1 §7.6.3.3
PASSWORD_PADDING: bytes = bytes([
    0x28, 0xBF, 0x4E, 0x5E, 0x4E, 0x75, 0x8A, 0x41,
    0x64, 0x00, 0x4E, 0x56, 0xFF, 0xFA, 0x01, 0x08,
    0x2E, 0x2E, 0x00, 0xB6, 0xD0, 0x68, 0x3E, 0x80,
    0x2F, 0x0C, 0xA9, 0xFE, 0x64, 0x53, 0x69, 0x7A,
])


class SecurityHandler:
    """Handles PDF standard encryption, password authentication, and decryption."""

    __slots__ = (
        "_encrypt_dict",
        "_doc_id",
        "_v",
        "_r",
        "_o",
        "_u",
        "_p",
        "_key_len",
        "_encrypt_metadata",
        "_cipher_type",
        "_doc_key",
        "_authenticated",
    )

    def __init__(
        self,
        encrypt_dict: PDFDict,
        doc_ids: Optional[Sequence[Any]] = None,
    ) -> None:
        """Initialize SecurityHandler.

        Args:
            encrypt_dict: The /Encrypt dictionary from the PDF trailer.
            doc_ids: Optional sequence containing /ID array from PDF trailer.
        """
        self._encrypt_dict: PDFDict = encrypt_dict

        # Extract primary document ID
        first_id = b""
        if doc_ids and len(doc_ids) > 0:
            raw_id = doc_ids[0]
            if isinstance(raw_id, (PDFString, PDFHexString)):
                first_id = raw_id.value
            elif isinstance(raw_id, bytes):
                first_id = raw_id
            elif isinstance(raw_id, str):
                first_id = raw_id.encode("latin-1")
        self._doc_id: bytes = first_id

        # Version and Revision
        v_val = encrypt_dict.get("V", 0)
        self._v: int = int(v_val) if isinstance(v_val, int) else 0

        r_val = encrypt_dict.get("R", 0)
        self._r: int = int(r_val) if isinstance(r_val, int) else 0

        # /O and /U strings
        o_val = encrypt_dict.get("O", b"")
        self._o: bytes = (
            o_val.value if isinstance(o_val, (PDFString, PDFHexString)) else bytes(o_val)
        )

        u_val = encrypt_dict.get("U", b"")
        self._u: bytes = (
            u_val.value if isinstance(u_val, (PDFString, PDFHexString)) else bytes(u_val)
        )

        # /P permissions
        p_val = encrypt_dict.get("P", 0)
        self._p: int = int(p_val) if isinstance(p_val, int) else 0

        # Key length (in bytes)
        length_bits = encrypt_dict.get("Length", 40 if self._v == 1 else 128)
        self._key_len: int = int(length_bits) // 8

        # Metadata encryption flag
        enc_meta = encrypt_dict.get("EncryptMetadata", True)
        self._encrypt_metadata: bool = bool(enc_meta)

        # Determine cipher type ('RC4' or 'AES')
        self._cipher_type: str = "RC4"
        if self._v in (4, 5, 6):
            cf = encrypt_dict.get("CF")
            stm_f = encrypt_dict.get("StmF")
            if isinstance(cf, PDFDict) and isinstance(stm_f, (str, PDFName)):
                std_cf = cf.get(stm_f)
                if isinstance(std_cf, PDFDict):
                    cfm = std_cf.get("CFM")
                    if cfm in ("AESV2", "AESV3", PDFName("AESV2"), PDFName("AESV3")):
                        self._cipher_type = "AES"
            elif self._v >= 4:
                # Default for V=4 and V=5 is AES
                self._cipher_type = "AES"

        self._doc_key: Optional[bytes] = None
        self._authenticated: bool = False

    @property
    def is_authenticated(self) -> bool:
        """Return True if successfully authenticated."""
        return self._authenticated

    @property
    def cipher_type(self) -> str:
        """Return active cipher type ('RC4' or 'AES')."""
        return self._cipher_type

    def authenticate(self, password: Union[str, bytes] = "") -> bool:
        """Attempt authentication using user password or owner password.

        Args:
            password: Plaintext password string or bytes.

        Returns:
            bool: True if authentication succeeded.
        """
        pwd_bytes = password.encode("latin-1") if isinstance(password, str) else bytes(password)

        if self._r in (2, 3, 4):
            # Try user password first
            if self._authenticate_user_rev234(pwd_bytes):
                self._authenticated = True
                return True
            # Try owner password
            if self._authenticate_owner_rev234(pwd_bytes):
                self._authenticated = True
                return True
        elif self._r in (5, 6):
            # Revision 5 / 6 (AES-256)
            if self._authenticate_rev56(pwd_bytes):
                self._authenticated = True
                return True

        return False

    # =========================================================================
    # Revision 2, 3, 4 Authentication & Key Derivation
    # =========================================================================

    def _derive_key_rev234(self, password: bytes) -> bytes:
        """Derive document encryption key using Algorithm 2 (PDF 32000-1 §7.6.3.3)."""
        # Step 1: Pad or truncate password to 32 bytes
        if len(password) < 32:
            padded = password + PASSWORD_PADDING[: 32 - len(password)]
        else:
            padded = password[:32]

        # Step 2: Initialize MD5
        m = hashlib.md5()
        m.update(padded)

        # Step 3: Pass /O
        m.update(self._o[:32])

        # Step 4: Pass /P as 4-byte unsigned integer, little-endian
        m.update(struct.pack("<i", self._p))

        # Step 5: Pass first document ID
        m.update(self._doc_id)

        # Step 6: If Revision >= 4 and metadata is not encrypted
        if self._r >= 4 and not self._encrypt_metadata:
            m.update(b"\xff\xff\xff\xff")

        digest = m.digest()

        # Step 7: If Revision >= 3, loop 50 times
        if self._r >= 3:
            for _ in range(50):
                digest = hashlib.md5(digest[: self._key_len]).digest()

        return digest[: self._key_len]

    def _authenticate_user_rev234(self, password: bytes) -> bool:
        """Authenticate user password for Revision 2, 3, 4."""
        key = self._derive_key_rev234(password)

        if self._r == 2:
            # Algorithm 4: Encrypt standard padding with key and compare with /U
            test = rc4_crypt(key, PASSWORD_PADDING)
            if test == self._u[:32]:
                self._doc_key = key
                return True
        elif self._r in (3, 4):
            # Algorithm 5:
            # Compute MD5(PASSWORD_PADDING + doc_id)
            h = hashlib.md5(PASSWORD_PADDING + self._doc_id).digest()
            # Encrypt 16-byte hash with RC4
            res = rc4_crypt(key, h)
            for x in range(1, 20):
                step_key = bytes([b ^ x for b in key])
                res = rc4_crypt(step_key, res)

            if res[:16] == self._u[:16]:
                self._doc_key = key
                return True

        return False

    def _authenticate_owner_rev234(self, password: bytes) -> bool:
        """Authenticate owner password for Revision 2, 3, 4."""
        # Pad password to 32 bytes
        if len(password) < 32:
            padded = password + PASSWORD_PADDING[: 32 - len(password)]
        else:
            padded = password[:32]

        m = hashlib.md5(padded)
        digest = m.digest()

        if self._r >= 3:
            for _ in range(50):
                digest = hashlib.md5(digest[: self._key_len]).digest()

        owner_key = digest[: self._key_len]

        # Decrypt /O to recover user password
        if self._r == 2:
            user_pwd = rc4_crypt(owner_key, self._o[:32])
        else:
            out = self._o[:32]
            for x in range(19, -1, -1):
                step_key = bytes([b ^ x for b in owner_key])
                out = rc4_crypt(step_key, out)
            user_pwd = out

        return self._authenticate_user_rev234(user_pwd)

    # =========================================================================
    # Revision 5 & 6 (AES-256)
    # =========================================================================

    def _authenticate_rev56(self, password: bytes) -> bool:
        """Authenticate password for Revision 5 / 6 (AES-256)."""
        # User validation: U is 48 bytes (32-byte hash + 16-byte validation salt)
        if len(self._u) >= 48:
            val_salt = self._u[32:48]
            h = hashlib.sha256(password + val_salt).digest()
            if h == self._u[:32]:
                # Recover document encryption key from /UE
                ue_val = self._encrypt_dict.get("UE")
                if isinstance(ue_val, (PDFString, PDFHexString)):
                    ue_bytes = ue_val.value
                elif isinstance(ue_val, bytes):
                    ue_bytes = ue_val
                else:
                    return False

                key_salt = self._u[40:48] if len(self._u) >= 48 else val_salt[:8]
                k = hashlib.sha256(password + key_salt).digest()
                try:
                    self._doc_key = aes_decrypt_cbc_with_iv(k, ue_bytes)
                    return True
                except Exception:
                    pass

        # Owner validation: O is 48 bytes (32-byte hash + 16-byte validation salt)
        if len(self._o) >= 48:
            val_salt = self._o[32:48]
            h = hashlib.sha256(password + val_salt).digest()
            if h == self._o[:32]:
                oe_val = self._encrypt_dict.get("OE")
                if isinstance(oe_val, (PDFString, PDFHexString)):
                    oe_bytes = oe_val.value
                elif isinstance(oe_val, bytes):
                    oe_bytes = oe_val
                else:
                    return False

                key_salt = self._o[40:48] if len(self._o) >= 48 else val_salt[:8]
                k = hashlib.sha256(password + key_salt).digest()
                try:
                    self._doc_key = aes_decrypt_cbc_with_iv(k, oe_bytes)
                    return True
                except Exception:
                    pass

        return False

    # =========================================================================
    # Object Decryption (Algorithm 1)
    # =========================================================================

    def derive_object_key(self, obj_id: int, gen: int) -> bytes:
        """Derive object-specific key using Algorithm 1 (PDF 32000-1 §7.6.2)."""
        if self._doc_key is None:
            raise PDFPasswordRequiredError("Document is encrypted and has not been authenticated")

        if self._r >= 5:
            # AES-256 uses the same document key directly for all objects
            return self._doc_key

        h = hashlib.md5()
        h.update(self._doc_key)
        h.update(struct.pack("<I", obj_id)[:3])
        h.update(struct.pack("<I", gen)[:2])

        if self._cipher_type == "AES":
            h.update(b"sAlT")

        digest = h.digest()
        if self._cipher_type == "AES":
            return digest[:16]
        return digest[: min(len(self._doc_key) + 5, 16)]

    def decrypt_data(
        self, data: bytes, obj_id: int, gen: int, is_stream: bool = False
    ) -> bytes:
        """Decrypt raw byte payload belonging to indirect object (obj_id, gen).

        Args:
            data: Encrypted byte sequence.
            obj_id: Indirect object ID.
            gen: Generation number.
            is_stream: True if decrypting a stream payload.

        Returns:
            bytes: Decrypted byte payload.
        """
        if not self._authenticated or self._doc_key is None:
            raise PDFPasswordRequiredError(
                f"Password required to decrypt object {obj_id} {gen} R"
            )

        key = self.derive_object_key(obj_id, gen)

        if self._cipher_type == "AES":
            return aes_decrypt_cbc_with_iv(key, data)
        else:
            return rc4_crypt(key, data)

    def decrypt_string(self, s: PDFString, obj_id: int, gen: int) -> PDFString:
        """Decrypt a PDFString literal or hex string."""
        decrypted = self.decrypt_data(s.value, obj_id, gen, is_stream=False)
        return PDFString(value=decrypted)
