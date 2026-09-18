"""Standard Security Handler implementation for PDF encryption and decryption.

Supports:
- Algorithm 2 (40-bit RC4, Revision 2)
- Algorithm 3 & 4 (128-bit RC4 and AES-128 in CBC mode, Revisions 3 and 4)
- Algorithm 5 & 6 (256-bit AES in CBC mode, Revisions 5 and 6)
- User and owner password authentication
- Object-level key derivation and transparent string/stream decryption
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import struct
from typing import Any, Dict, List, Optional, Tuple, Union

from anyconvert.exceptions import (
    PDFCryptoError,
    PDFInvalidPasswordError,
    PDFPasswordRequiredError,
    PDFSecurityError,
    PDFUnsupportedSecurityHandlerError,
)
from anyconvert.pdf.crypto.aes import aes_decrypt_cbc, aes_encrypt_cbc
from anyconvert.pdf.crypto.rc4 import rc4_crypt
from anyconvert.pdf.parser import PDFRef, PDFStream, PDFString

# Standard 32-byte padding specified in ISO 32000-1 Section 7.6.3.3
PASSWORD_PADDING = (
    b"\x28\xbf\x4e\x5e\x4e\x75\x8a\x41"
    b"\x64\x00\x4e\x56\xff\xfa\x01\x08"
    b"\x2e\x2e\x00\xb6\xd0\x68\x3e\x80"
    b"\x2f\x0c\xa9\xfe\x64\x53\x69\x7a"
)


@dataclass
class StandardSecurityHandler:
    """Handles PDF decryption using the Standard Security Handler."""

    encrypt_dict: Dict[str, Any]
    file_id: bytes
    password: bytes = b""

    # Extracted parameters
    version: int = 1
    revision: int = 2
    key_length: int = 5  # in bytes (5 to 32)
    permissions: int = 0
    owner_entry: bytes = b""
    user_entry: bytes = b""
    encrypt_metadata: bool = True
    cipher_name: str = "RC4"  # 'RC4' or 'AES'

    # Master derived encryption key
    encryption_key: bytes = b""

    def __post_init__(self) -> None:
        self._parse_encrypt_dict()
        self._authenticate_and_derive_key()

    def _parse_encrypt_dict(self) -> None:
        """Extract and validate parameters from the /Encrypt dictionary."""
        d = self.encrypt_dict

        # Filter must be /Standard
        filter_name = d.get("Filter")
        if filter_name not in ("Standard", "/Standard"):
            raise PDFUnsupportedSecurityHandlerError(
                f"Unsupported security handler filter: {filter_name}"
            )

        self.version = int(d.get("V", 1))
        self.revision = int(d.get("R", 2))
        raw_length = d.get("Length", 40)
        self.key_length = int(raw_length) // 8

        # Permissions flag (32-bit signed integer)
        p_val = d.get("P", 0)
        self.permissions = int(p_val) if isinstance(p_val, int) else 0

        # Owner / User verification strings
        o_val = d.get("O")
        if isinstance(o_val, PDFString):
            self.owner_entry = o_val.data
        elif isinstance(o_val, bytes):
            self.owner_entry = o_val

        u_val = d.get("U")
        if isinstance(u_val, PDFString):
            self.user_entry = u_val.data
        elif isinstance(u_val, bytes):
            self.user_entry = u_val

        self.encrypt_metadata = bool(d.get("EncryptMetadata", True))

        # Determine cipher family
        if self.version in (1, 2):
            self.cipher_name = "RC4"
        elif self.version == 4:
            # Check CryptFilter (/CF) if specified
            cf_dict = d.get("CF")
            stm_f = d.get("StmF", "StdCF")
            if isinstance(cf_dict, dict) and stm_f in cf_dict:
                cf = cf_dict[stm_f]
                cfm = cf.get("CFM") if isinstance(cf, dict) else None
                if cfm in ("AESV2", "/AESV2"):
                    self.cipher_name = "AES"
                else:
                    self.cipher_name = "RC4"
            else:
                self.cipher_name = "AES"
        elif self.version == 5:
            self.cipher_name = "AES"
            self.key_length = 32
        else:
            raise PDFUnsupportedSecurityHandlerError(f"Unsupported PDF encryption version: {self.version}")

    def _pad_password(self, pwd: bytes) -> bytes:
        """Pad or truncate password to 32 bytes."""
        if len(pwd) >= 32:
            return pwd[:32]
        return pwd + PASSWORD_PADDING[: 32 - len(pwd)]

    def _authenticate_and_derive_key(self) -> None:
        """Authenticate password against /U or /O and compute master encryption key."""
        pwd = self.password

        # Revision 5 / 6 (AES-256)
        if self.revision in (5, 6):
            if not self._authenticate_rev5_6(pwd):
                raise PDFInvalidPasswordError("Invalid password for AES-256 encrypted document")
            return

        # Revision 2, 3, 4
        # First try authenticating as user password
        derived_key = self._compute_encryption_key_r2_4(pwd)
        if self._check_user_password(derived_key):
            self.encryption_key = derived_key
            return

        # If user authentication fails, try authenticating as owner password
        user_pwd = self._compute_user_password_from_owner(pwd)
        if user_pwd is not None:
            derived_key = self._compute_encryption_key_r2_4(user_pwd)
            if self._check_user_password(derived_key):
                self.encryption_key = derived_key
                return

        # If password was empty, suggest password required; otherwise invalid password
        if not pwd:
            raise PDFPasswordRequiredError("Document is encrypted and requires a password")
        raise PDFInvalidPasswordError("Invalid password supplied for document decryption")

    def _compute_encryption_key_r2_4(self, password: bytes) -> bytes:
        """Derive encryption key for Revisions 2 to 4 (ISO 32000-1 Algorithm 2)."""
        padded = self._pad_password(password)
        h = hashlib.md5()
        h.update(padded)
        h.update(self.owner_entry)
        h.update(struct.pack("<i", self.permissions))
        h.update(self.file_id)

        if self.revision >= 4 and not self.encrypt_metadata:
            h.update(b"\xff\xff\xff\xff")

        digest = h.digest()

        if self.revision >= 3:
            for _ in range(50):
                digest = hashlib.md5(digest[: self.key_length]).digest()

        return digest[: self.key_length]

    def _check_user_password(self, key: bytes) -> bool:
        """Validate derived key against the /U entry."""
        if self.revision == 2:
            computed_u = rc4_crypt(key, PASSWORD_PADDING)
            return computed_u == self.user_entry[:32]

        # Revision 3 and 4
        h = hashlib.md5()
        h.update(PASSWORD_PADDING)
        h.update(self.file_id)
        digest = h.digest()

        temp = rc4_crypt(key, digest)
        for i in range(1, 20):
            step_key = bytes([b ^ i for b in key])
            temp = rc4_crypt(step_key, temp)

        return temp == self.user_entry[:16]

    def _compute_user_password_from_owner(self, owner_pwd: bytes) -> Optional[bytes]:
        """Derive user password using owner password (ISO 32000-1 Algorithm 7)."""
        padded = self._pad_password(owner_pwd)
        h = hashlib.md5(padded).digest()

        if self.revision >= 3:
            for _ in range(50):
                h = hashlib.md5(h).digest()

        key = h[: self.key_length]

        if self.revision == 2:
            return rc4_crypt(key, self.owner_entry)

        # Revision 3 and 4
        temp = self.owner_entry
        for i in range(19, -1, -1):
            step_key = bytes([b ^ i for b in key])
            temp = rc4_crypt(step_key, temp)

        return temp

    def _authenticate_rev5_6(self, password: bytes) -> bool:
        """Authenticate password for Revision 5 / 6 (AES-256 / ISO 32000-2)."""
        # Truncate password to 127 bytes if needed per spec
        pwd = password[:127]

        # Revision 5 / 6 contains /U (48 bytes: 32 hash + 8 validation salt + 8 key salt)
        # and /UE (32 bytes AES-256 encrypted file key)
        u = self.user_entry
        ue_entry = self.encrypt_dict.get("UE")
        ue = ue_entry.data if isinstance(ue_entry, PDFString) else (ue_entry or b"")

        o = self.owner_entry
        oe_entry = self.encrypt_dict.get("OE")
        oe = oe_entry.data if isinstance(oe_entry, PDFString) else (oe_entry or b"")

        # Check User Password
        if len(u) >= 40 and len(ue) >= 32:
            val_salt = u[32:40]
            key_salt = u[40:48] if len(u) >= 48 else b""
            # Compute SHA-256 of password + validation salt
            computed_val = hashlib.sha256(pwd + val_salt).digest()
            if computed_val == u[:32]:
                # Authenticated as user! Decrypt file key from /UE using key derived from pwd + key_salt
                int_key = hashlib.sha256(pwd + key_salt).digest()
                # Decrypt UE with AES-128/256 CBC with zero IV
                self.encryption_key = aes_decrypt_cbc(ue, int_key, iv=b"\x00" * 16)
                return True

        # Check Owner Password
        if len(o) >= 40 and len(oe) >= 32:
            val_salt = o[32:40]
            key_salt = o[40:48] if len(o) >= 48 else b""
            computed_val = hashlib.sha256(pwd + val_salt).digest()
            if computed_val == o[:32]:
                int_key = hashlib.sha256(pwd + key_salt).digest()
                self.encryption_key = aes_decrypt_cbc(oe, int_key, iv=b"\x00" * 16)
                return True

        return False

    def derive_object_key(self, obj_num: int, gen_num: int) -> bytes:
        """Derive object-specific encryption key."""
        if self.version == 5:
            # AES-256 uses master encryption key directly across all objects
            return self.encryption_key

        # Revisions 2, 3, 4
        h = hashlib.md5()
        h.update(self.encryption_key)
        h.update(obj_num.to_bytes(3, "little"))
        h.update(gen_num.to_bytes(2, "little"))

        if self.cipher_name == "AES":
            h.update(b"sAlT")

        obj_key_len = min(len(self.encryption_key) + 5, 16)
        return h.digest()[:obj_key_len]

    def decrypt_bytes(
        self,
        data: bytes,
        obj_num: int,
        gen_num: int,
    ) -> bytes:
        """Decrypt raw byte sequence belonging to a specific object.

        Args:
            data: Encrypted bytes.
            obj_num: Object identifier.
            gen_num: Generation number.

        Returns:
            Decrypted plaintext bytes.
        """
        if not data:
            return b""

        obj_key = self.derive_object_key(obj_num, gen_num)

        if self.cipher_name == "RC4":
            return rc4_crypt(obj_key, data)

        # AES (CBC mode with IV prepended)
        if len(data) < 32:
            # Too short for prepended IV + block
            return data
        try:
            return aes_decrypt_cbc(data, obj_key)
        except Exception as err:
            raise PDFCryptoError(f"AES decryption error for object {obj_num}: {err}") from err

    def decrypt_string(self, string_obj: PDFString, obj_num: int, gen_num: int) -> PDFString:
        """Decrypt a PDFString object."""
        plain = self.decrypt_bytes(string_obj.data, obj_num, gen_num)
        return PDFString(data=plain, is_hex=string_obj.is_hex)

    def decrypt_stream(self, stream_obj: PDFStream, obj_num: int, gen_num: int) -> PDFStream:
        """Decrypt a PDFStream object."""
        # Check /Filter for /Crypt filter
        s_dict = stream_obj.dictionary
        raw_bytes = stream_obj.to_bytes()

        decrypted_bytes = self.decrypt_bytes(raw_bytes, obj_num, gen_num)
        return PDFStream(
            dictionary=s_dict,
            raw_data=memoryview(decrypted_bytes),
            offset=stream_obj.offset,
        )


__all__ = [
    "PASSWORD_PADDING",
    "StandardSecurityHandler",
]
