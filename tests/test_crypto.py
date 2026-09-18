"""Test suite for Phase 6: Cryptographic Engine & Security Handlers."""

from __future__ import annotations

import hashlib
import struct
import unittest

from anyconvert.exceptions import (
    PDFInvalidPasswordError,
    PDFPasswordRequiredError,
    PDFUnsupportedSecurityHandlerError,
)
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
from anyconvert.pdf.parser import PDFStream, PDFString


class TestRC4Cipher(unittest.TestCase):
    """Test pure-Python RC4 stream cipher against standard test vectors."""

    def test_rc4_rfc_test_vectors(self) -> None:
        # Known test vectors
        # 1. Key: "Key", Plaintext: "Plaintext"
        ct1 = rc4_crypt(b"Key", b"Plaintext")
        self.assertEqual(ct1, b"\xbb\xf3\x16\xe8\xd9\x40\xaf\x0a\xd3")
        self.assertEqual(rc4_crypt(b"Key", ct1), b"Plaintext")

        # 2. Key: "Wiki", Plaintext: "pedia"
        ct2 = rc4_crypt(b"Wiki", b"pedia")
        self.assertEqual(ct2, bytes.fromhex("1021bf0420"))
        self.assertEqual(rc4_crypt(b"Wiki", ct2), b"pedia")


        # 3. Key: "Secret", Plaintext: "Attack at dawn"
        ct3 = rc4_crypt(b"Secret", b"Attack at dawn")
        self.assertEqual(rc4_crypt(b"Secret", ct3), b"Attack at dawn")

    def test_rc4_stateful_stream(self) -> None:
        key = b"StreamKey"
        c1 = RC4(key)
        part1 = c1.encrypt(b"Hello, ")
        part2 = c1.encrypt(b"World!")
        full_ct = part1 + part2

        # Decrypt sequentially
        c2 = RC4(key)
        dec1 = c2.decrypt(part1)
        dec2 = c2.decrypt(part2)
        self.assertEqual(dec1 + dec2, b"Hello, World!")


class TestAESCipher(unittest.TestCase):
    """Test pure-Python AES-128 and AES-256 against NIST FIPS 197 test vectors."""

    def test_aes_128_nist_vector(self) -> None:
        # NIST SP 800-38A AES-128 test vector (Block Cipher)
        key = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
        pt = bytes.fromhex("00112233445566778899aabbccddeeff")
        expected_ct = bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a")

        rks, nr = key_expansion(key)
        self.assertEqual(nr, 10)

        ct = encrypt_block(pt, rks, nr)
        self.assertEqual(ct, expected_ct)

        decrypted = decrypt_block(ct, rks, nr)
        self.assertEqual(decrypted, pt)

    def test_aes_256_nist_vector(self) -> None:
        # NIST SP 800-38A AES-256 test vector (Block Cipher)
        key = bytes.fromhex("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f")
        pt = bytes.fromhex("00112233445566778899aabbccddeeff")
        expected_ct = bytes.fromhex("8ea2b7ca516745bfeafc49904b496089")

        rks, nr = key_expansion(key)
        self.assertEqual(nr, 14)

        ct = encrypt_block(pt, rks, nr)
        self.assertEqual(ct, expected_ct)

        decrypted = decrypt_block(ct, rks, nr)
        self.assertEqual(decrypted, pt)

    def test_aes_cbc_roundtrip(self) -> None:
        key = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
        plaintexts = [
            b"",
            b"Short",
            b"ExactSixteenByte",
            b"A slightly longer message that spans across multiple AES 16-byte blocks smoothly!",
        ]

        for pt in plaintexts:
            ct = aes_encrypt_cbc(pt, key)
            decrypted = aes_decrypt_cbc(ct, key)
            self.assertEqual(decrypted, pt)


class TestStandardSecurityHandler(unittest.TestCase):
    """Test StandardSecurityHandler authentication and decryption."""

    def test_revision_2_user_password(self) -> None:
        # Build synthetic Rev 2 Encrypt Dict with known password 'test'
        password = b"test"
        padded_pwd = password + PASSWORD_PADDING[:28]
        file_id = b"DocumentID123456"
        permissions = -4  # standard permissions integer

        # Derive Rev 2 key (Length = 40 bits = 5 bytes)
        key_length = 5
        h = hashlib.md5()
        h.update(padded_pwd)
        owner_str = b"O" * 32
        h.update(owner_str)
        h.update(struct.pack("<i", permissions))
        h.update(file_id)
        master_key = h.digest()[:key_length]

        # Rev 2 /U entry is RC4 of padding with master_key
        user_str = rc4_crypt(master_key, PASSWORD_PADDING)

        encrypt_dict = {
            "Filter": "Standard",
            "V": 1,
            "R": 2,
            "Length": 40,
            "P": permissions,
            "O": owner_str,
            "U": user_str,
        }

        handler = StandardSecurityHandler(
            encrypt_dict=encrypt_dict,
            file_id=file_id,
            password=b"test",
        )
        self.assertEqual(handler.encryption_key, master_key)

        # Encrypt a test string for Object 1, Generation 0
        obj_key = handler.derive_object_key(1, 0)
        secret_text = b"Confidential Financial Report"
        enc_bytes = rc4_crypt(obj_key, secret_text)

        str_obj = PDFString(data=enc_bytes)
        decrypted_str = handler.decrypt_string(str_obj, 1, 0)
        self.assertEqual(decrypted_str.data, secret_text)

        # Encrypt a stream
        stream_obj = PDFStream(dictionary={}, raw_data=memoryview(enc_bytes))
        decrypted_stream = handler.decrypt_stream(stream_obj, 1, 0)
        self.assertEqual(decrypted_stream.to_bytes(), secret_text)

    def test_invalid_password_raises_error(self) -> None:
        encrypt_dict = {
            "Filter": "Standard",
            "V": 1,
            "R": 2,
            "Length": 40,
            "P": -4,
            "O": b"O" * 32,
            "U": b"U" * 32,
        }
        with self.assertRaises(PDFInvalidPasswordError):
            StandardSecurityHandler(
                encrypt_dict=encrypt_dict,
                file_id=b"12345678",
                password=b"wrong_password",
            )

    def test_unsupported_filter_raises_error(self) -> None:
        encrypt_dict = {
            "Filter": "CustomProprietaryFilter",
            "V": 1,
            "R": 2,
        }
        with self.assertRaises(PDFUnsupportedSecurityHandlerError):
            StandardSecurityHandler(
                encrypt_dict=encrypt_dict,
                file_id=b"1234",
                password=b"",
            )


if __name__ == "__main__":
    unittest.main()
