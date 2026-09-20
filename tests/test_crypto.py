"""Unit tests for Phase 6: Pure-Python RC4, AES, and PDF SecurityHandler."""

from __future__ import annotations

import hashlib
import struct
import unittest

from anyconvert.exceptions import PDFPasswordRequiredError
from anyconvert.pdf.crypto.aes import (
    AES,
    aes_decrypt_cbc_with_iv,
    aes_encrypt_cbc_with_iv,
    pkcs7_pad,
    pkcs7_unpad,
)
from anyconvert.pdf.crypto.handler import PASSWORD_PADDING, SecurityHandler
from anyconvert.pdf.crypto.rc4 import RC4, rc4_crypt
from anyconvert.pdf.parser import PDFDict, PDFName, PDFString


class TestRC4(unittest.TestCase):
    """Tests for pure-Python RC4 stream cipher."""

    def test_rc4_known_vectors(self) -> None:
        # RFC 6229 / Wikipedia test vectors
        # Vector 1: Key = "Key", Data = "Plaintext"
        key1 = b"Key"
        plain1 = b"Plaintext"
        expected1 = bytes([0xBB, 0xF3, 0x16, 0xE8, 0xD9, 0x40, 0xAF, 0x0A, 0xD3])
        cipher1 = rc4_crypt(key1, plain1)
        self.assertEqual(cipher1, expected1)
        self.assertEqual(rc4_crypt(key1, cipher1), plain1)

        # Vector 2: Key = "Wiki", Data = "pedia"
        key2 = b"Wiki"
        plain2 = b"pedia"
        expected2 = bytes([0x10, 0x21, 0xBF, 0x04, 0x20])
        cipher2 = rc4_crypt(key2, plain2)
        self.assertEqual(cipher2, expected2)
        self.assertEqual(rc4_crypt(key2, cipher2), plain2)

    def test_rc4_roundtrip(self) -> None:
        key = b"A_Secret_Key_128"
        data = b"This is a longer message that will be encrypted and decrypted via RC4!"
        encrypted = rc4_crypt(key, data)
        self.assertNotEqual(encrypted, data)
        decrypted = rc4_crypt(key, encrypted)
        self.assertEqual(decrypted, data)

    def test_rc4_invalid_key(self) -> None:
        with self.assertRaises(ValueError):
            RC4(b"")
        with self.assertRaises(ValueError):
            RC4(b"x" * 257)


class TestAES(unittest.TestCase):
    """Tests for pure-Python AES-128 and AES-256 block cipher and CBC mode."""

    def test_aes128_known_fips197_vector(self) -> None:
        # NIST FIPS-197 Appendix B test vector for AES-128
        key = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
        plaintext = bytes.fromhex("00112233445566778899aabbccddeeff")
        expected_cipher = bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a")

        cipher = AES(key)
        encrypted = cipher.encrypt_block(plaintext)
        self.assertEqual(encrypted, expected_cipher)

        decrypted = cipher.decrypt_block(encrypted)
        self.assertEqual(decrypted, plaintext)

    def test_aes256_known_fips197_vector(self) -> None:
        # NIST FIPS-197 Appendix C test vector for AES-256
        key = bytes.fromhex("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f")
        plaintext = bytes.fromhex("00112233445566778899aabbccddeeff")
        expected_cipher = bytes.fromhex("8ea2b7ca516745bfeafc49904b496089")

        cipher = AES(key)
        encrypted = cipher.encrypt_block(plaintext)
        self.assertEqual(encrypted, expected_cipher)

        decrypted = cipher.decrypt_block(encrypted)
        self.assertEqual(decrypted, plaintext)

    def test_pkcs7_padding(self) -> None:
        data = b"Hello"
        padded = pkcs7_pad(data, 16)
        self.assertEqual(len(padded), 16)
        self.assertEqual(padded[-1], 11)
        self.assertEqual(pkcs7_unpad(padded), data)

        # Exact block size adds full padding block
        exact = b"1234567812345678"
        padded_exact = pkcs7_pad(exact, 16)
        self.assertEqual(len(padded_exact), 32)
        self.assertEqual(pkcs7_unpad(padded_exact), exact)

        # Invalid padding raises ValueError
        with self.assertRaises(ValueError):
            pkcs7_unpad(b"corrupted\x00")
        with self.assertRaises(ValueError):
            pkcs7_unpad(b"")

    def test_aes_cbc_with_iv_roundtrip(self) -> None:
        key = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
        message = b"Confidential document stream payload that spans multiple 16-byte blocks."
        iv = bytes.fromhex("000102030405060708090a0b0c0d0e0f")

        encrypted = aes_encrypt_cbc_with_iv(key, message, iv=iv)
        # Prepend IV (16 bytes)
        self.assertEqual(encrypted[:16], iv)

        decrypted = aes_decrypt_cbc_with_iv(key, encrypted)
        self.assertEqual(decrypted, message)


class TestSecurityHandler(unittest.TestCase):
    """Tests for PDF Standard Security Handler."""

    def test_revision2_empty_password(self) -> None:
        # Build synthetic Revision 2 encryption dictionary with empty user password
        # V=1, R=2, Length=40 (5 bytes)
        # Permissions = -64
        # Empty password padded with PASSWORD_PADDING
        password = b""
        padded = PASSWORD_PADDING
        o_val = b"0" * 32
        p_val = -64
        doc_id = b"DocID12345678901"

        # Calculate expected encryption key
        m = hashlib.md5()
        m.update(padded)
        m.update(o_val)
        m.update(struct.pack("<i", p_val))
        m.update(doc_id)
        doc_key = m.digest()[:5]

        # In Revision 2, U is RC4(doc_key, PASSWORD_PADDING)
        u_val = rc4_crypt(doc_key, PASSWORD_PADDING)

        encrypt_dict = PDFDict({
            "Filter": PDFName("Standard"),
            "V": 1,
            "R": 2,
            "O": PDFString(o_val),
            "U": PDFString(u_val),
            "P": p_val,
            "Length": 40,
        })

        handler = SecurityHandler(encrypt_dict, doc_ids=[PDFString(doc_id)])
        self.assertFalse(handler.is_authenticated)

        # Authenticate with empty password
        auth_ok = handler.authenticate("")
        self.assertTrue(auth_ok)
        self.assertTrue(handler.is_authenticated)

        # Encrypt a test string for Object 1, Generation 0
        # Object key = MD5(doc_key + obj_id(3) + gen(2))[:10]
        obj_key_hash = hashlib.md5(doc_key + b"\x01\x00\x00\x00\x00").digest()[:10]
        plaintext = b"Sensitive PDF Text"
        ciphertext = rc4_crypt(obj_key_hash, plaintext)

        decrypted = handler.decrypt_data(ciphertext, obj_id=1, gen=0)
        self.assertEqual(decrypted, plaintext)

    def test_unauthenticated_raises(self) -> None:
        encrypt_dict = PDFDict({
            "Filter": PDFName("Standard"),
            "V": 1,
            "R": 2,
            "O": PDFString(b"O" * 32),
            "U": PDFString(b"U" * 32),
            "P": -4,
        })
        handler = SecurityHandler(encrypt_dict)
        with self.assertRaises(PDFPasswordRequiredError):
            handler.decrypt_data(b"data", obj_id=1, gen=0)


if __name__ == "__main__":
    unittest.main()
