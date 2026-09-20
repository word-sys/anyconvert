"""Pure-Python AES-128 and AES-256 cipher implementation in CBC mode.

Adheres to NIST FIPS-197, NIST SP 800-38A (CBC mode), and PKCS#7 (RFC 5652).
Zero third-party dependencies.
"""

from __future__ import annotations

from typing import List, Sequence, Tuple, Union


# Rijndael S-Box
S_BOX: Tuple[int, ...] = (
    0x63, 0x7C, 0x77, 0x7B, 0xF2, 0x6B, 0x6F, 0xC5, 0x30, 0x01, 0x67, 0x2B, 0xFE, 0xD7, 0xAB, 0x76,
    0xCA, 0x82, 0xC9, 0x7D, 0xFA, 0x59, 0x47, 0xF0, 0xAD, 0xD4, 0xA2, 0xAF, 0x9C, 0xA4, 0x72, 0xC0,
    0xB7, 0xFD, 0x93, 0x26, 0x36, 0x3F, 0xF7, 0xCC, 0x34, 0xA5, 0xE5, 0xF1, 0x71, 0xD8, 0x31, 0x15,
    0x04, 0xC7, 0x23, 0xC3, 0x18, 0x96, 0x05, 0x9A, 0x07, 0x12, 0x80, 0xE2, 0xEB, 0x27, 0xB2, 0x75,
    0x09, 0x83, 0x2C, 0x1A, 0x1B, 0x6E, 0x5A, 0xA0, 0x52, 0x3B, 0xD6, 0xB3, 0x29, 0xE3, 0x2F, 0x84,
    0x53, 0xD1, 0x00, 0xED, 0x20, 0xFC, 0xB1, 0x5B, 0x6A, 0xCB, 0xBE, 0x39, 0x4A, 0x4C, 0x58, 0xCF,
    0xD0, 0xEF, 0xAA, 0xFB, 0x43, 0x4D, 0x33, 0x85, 0x45, 0xF9, 0x02, 0x7F, 0x50, 0x3C, 0x9F, 0xA8,
    0x51, 0xA3, 0x40, 0x8F, 0x92, 0x9D, 0x38, 0xF5, 0xBC, 0xB6, 0xDA, 0x21, 0x10, 0xFF, 0xF3, 0xD2,
    0xCD, 0x0C, 0x13, 0xEC, 0x5F, 0x97, 0x44, 0x17, 0xC4, 0xA7, 0x7E, 0x3D, 0x64, 0x5D, 0x19, 0x73,
    0x60, 0x81, 0x4F, 0xDC, 0x22, 0x2A, 0x90, 0x88, 0x46, 0xEE, 0xB8, 0x14, 0xDE, 0x5E, 0x0B, 0xDB,
    0xE0, 0x32, 0x3A, 0x0A, 0x49, 0x06, 0x24, 0x5C, 0xC2, 0xD3, 0xAC, 0x62, 0x91, 0x95, 0xE4, 0x79,
    0xE7, 0xC8, 0x37, 0x6D, 0x8D, 0xD5, 0x4E, 0xA9, 0x6C, 0x56, 0xF4, 0xEA, 0x65, 0x7A, 0xAE, 0x08,
    0xBA, 0x78, 0x25, 0x2E, 0x1C, 0xA6, 0xB4, 0xC6, 0xE8, 0xDD, 0x74, 0x1F, 0x4B, 0xBD, 0x8B, 0x8A,
    0x70, 0x3E, 0xB5, 0x66, 0x48, 0x03, 0xF6, 0x0E, 0x61, 0x35, 0x57, 0xB9, 0x86, 0xC1, 0x1D, 0x9E,
    0xE1, 0xF8, 0x98, 0x11, 0x69, 0xD9, 0x8E, 0x94, 0x9B, 0x1E, 0x87, 0xE9, 0xCE, 0x55, 0x28, 0xDF,
    0x8C, 0xA1, 0x89, 0x0D, 0xBF, 0xE6, 0x42, 0x68, 0x41, 0x99, 0x2D, 0x0F, 0xB0, 0x54, 0xBB, 0x16,
)

# Inverse Rijndael S-Box
INV_S_BOX: Tuple[int, ...] = (
    0x52, 0x09, 0x6A, 0xD5, 0x30, 0x36, 0xA5, 0x38, 0xBF, 0x40, 0xA3, 0x9E, 0x81, 0xF3, 0xD7, 0xFB,
    0x7C, 0xE3, 0x39, 0x82, 0x9B, 0x2F, 0xFF, 0x87, 0x34, 0x8E, 0x43, 0x44, 0xC4, 0xDE, 0xE9, 0xCB,
    0x54, 0x7B, 0x94, 0x32, 0xA6, 0xC2, 0x23, 0x3D, 0xEE, 0x4C, 0x95, 0x0B, 0x42, 0xFA, 0xC3, 0x4E,
    0x08, 0x2E, 0xA1, 0x66, 0x28, 0xD9, 0x24, 0xB2, 0x76, 0x5B, 0xA2, 0x49, 0x6D, 0x8B, 0xD1, 0x25,
    0x72, 0xF8, 0xF6, 0x64, 0x86, 0x68, 0x98, 0x16, 0xD4, 0xA4, 0x5C, 0xCC, 0x5D, 0x65, 0xB6, 0x92,
    0x6C, 0x70, 0x48, 0x50, 0xFD, 0xED, 0xB9, 0xDA, 0x5E, 0x15, 0x46, 0x57, 0xA7, 0x8D, 0x9D, 0x84,
    0x90, 0xD8, 0xAB, 0x00, 0x8C, 0xBC, 0xD3, 0x0A, 0xF7, 0xE4, 0x58, 0x05, 0xB8, 0xB3, 0x45, 0x06,
    0xD0, 0x2C, 0x1E, 0x8F, 0xCA, 0x3F, 0x0F, 0x02, 0xC1, 0xAF, 0xBD, 0x03, 0x01, 0x13, 0x8A, 0x6B,
    0x3A, 0x91, 0x11, 0x41, 0x4F, 0x67, 0xDC, 0xEA, 0x97, 0xF2, 0xCF, 0xCE, 0xF0, 0xB4, 0xE6, 0x73,
    0x96, 0xAC, 0x74, 0x22, 0xE7, 0xAD, 0x35, 0x85, 0xE2, 0xF9, 0x37, 0xE8, 0x1C, 0x75, 0xDF, 0x6E,
    0x47, 0xF1, 0x1A, 0x71, 0x1D, 0x29, 0xC5, 0x89, 0x6F, 0xB7, 0x62, 0x0E, 0xAA, 0x18, 0xBE, 0x1B,
    0xFC, 0x56, 0x3E, 0x4B, 0xC6, 0xD2, 0x79, 0x20, 0x9A, 0xDB, 0xC0, 0xFE, 0x78, 0xCD, 0x5A, 0xF4,
    0x1F, 0xDD, 0xA8, 0x33, 0x88, 0x07, 0xC7, 0x31, 0xB1, 0x12, 0x10, 0x59, 0x27, 0x80, 0xEC, 0x5F,
    0x60, 0x51, 0x7F, 0xA9, 0x19, 0xB5, 0x4A, 0x0D, 0x2D, 0xE5, 0x7A, 0x9F, 0x93, 0xC9, 0x9C, 0xEF,
    0xA0, 0xE0, 0x3B, 0x4D, 0xAE, 0x2A, 0xF5, 0xB0, 0xC8, 0xEB, 0xBB, 0x3C, 0x83, 0x53, 0x99, 0x61,
    0x17, 0x2B, 0x04, 0x7E, 0xBA, 0x77, 0xD6, 0x26, 0xE1, 0x69, 0x14, 0x63, 0x55, 0x21, 0x0C, 0x7D,
)

# Round constants Rcon
RCON: Tuple[int, ...] = (
    0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36,
)


def _xts(a: int) -> int:
    """Multiplication by 2 in GF(2^8)."""
    return ((a << 1) ^ 0x1B) & 0xFF if (a & 0x80) else (a << 1)


# Precomputed Galois Field multiplication lookup tables for MixColumns
_MUL2 = tuple(_xts(i) for i in range(256))
_MUL3 = tuple(_xts(i) ^ i for i in range(256))
_MUL9 = tuple(_xts(_xts(_xts(i))) ^ i for i in range(256))
_MUL11 = tuple(_xts(_xts(_xts(i)) ^ i) ^ i for i in range(256))
_MUL13 = tuple(_xts(_xts(_xts(i) ^ i)) ^ i for i in range(256))
_MUL14 = tuple(_xts(_xts(_xts(i) ^ i) ^ i) for i in range(256))


class AES:
    """Pure-Python implementation of AES (Rijndael) block cipher.

    Supports 128-bit, 192-bit, and 256-bit keys.
    """

    __slots__ = ("_nr", "_nk", "_round_keys")

    def __init__(self, key: Union[bytes, bytearray, memoryview]) -> None:
        """Initialize AES with secret key.

        Args:
            key: 16-byte (AES-128), 24-byte (AES-192), or 32-byte (AES-256) key.
        """
        key_bytes = bytes(key)
        key_len = len(key_bytes)

        if key_len == 16:
            self._nk = 4
            self._nr = 10
        elif key_len == 24:
            self._nk = 6
            self._nr = 12
        elif key_len == 32:
            self._nk = 8
            self._nr = 14
        else:
            raise ValueError(f"Invalid AES key length: {key_len} bytes (must be 16, 24, or 32)")

        self._round_keys: List[List[int]] = self._key_expansion(key_bytes)

    def _key_expansion(self, key: bytes) -> List[List[int]]:
        """Expand cipher key into (Nr + 1) 16-byte round keys."""
        nk = self._nk
        nr = self._nr
        # Words array: total 4 * (Nr + 1) 4-byte words
        w: List[List[int]] = []

        # First Nk words are taken directly from the key
        for i in range(nk):
            w.append([key[4 * i], key[4 * i + 1], key[4 * i + 2], key[4 * i + 3]])

        # Generate remaining words
        for i in range(nk, 4 * (nr + 1)):
            temp = list(w[i - 1])
            if i % nk == 0:
                # RotWord & SubWord & XOR Rcon
                temp = [
                    S_BOX[temp[1]] ^ RCON[i // nk],
                    S_BOX[temp[2]],
                    S_BOX[temp[3]],
                    S_BOX[temp[0]],
                ]
            elif nk > 6 and i % nk == 4:
                # SubWord for AES-256
                temp = [S_BOX[b] for b in temp]

            w_prev = w[i - nk]
            w.append([
                w_prev[0] ^ temp[0],
                w_prev[1] ^ temp[1],
                w_prev[2] ^ temp[2],
                w_prev[3] ^ temp[3],
            ])

        # Group words into 16-byte round keys
        round_keys: List[List[int]] = []
        for r in range(nr + 1):
            rk: List[int] = []
            for c in range(4):
                rk.extend(w[4 * r + c])
            round_keys.append(rk)

        return round_keys

    def encrypt_block(self, block: Union[bytes, bytearray, memoryview]) -> bytes:
        """Encrypt a single 16-byte block.

        Args:
            block: Exactly 16 bytes of plaintext.

        Returns:
            bytes: Exactly 16 bytes of ciphertext.
        """
        if len(block) != 16:
            raise ValueError(f"AES block size must be 16 bytes, got {len(block)}")

        # State matrix (4x4 column-major order): state[r][c]
        state = bytearray(block)
        round_keys = self._round_keys
        nr = self._nr

        # Initial Round: AddRoundKey
        rk0 = round_keys[0]
        for i in range(16):
            state[i] ^= rk0[i]

        # Rounds 1 to Nr - 1
        for round_idx in range(1, nr):
            # 1. SubBytes
            for i in range(16):
                state[i] = S_BOX[state[i]]

            # 2. ShiftRows
            # Row 0: s0, s4, s8, s12 (unchanged)
            # Row 1: s1, s5, s9, s13 -> s5, s9, s13, s1
            # Row 2: s2, s6, s10, s14 -> s10, s14, s2, s6
            # Row 3: s3, s7, s11, s15 -> s15, s3, s7, s11
            s1, s5, s9, s13 = state[1], state[5], state[9], state[13]
            state[1], state[5], state[9], state[13] = s5, s9, s13, s1

            s2, s6, s10, s14 = state[2], state[6], state[10], state[14]
            state[2], state[6], state[10], state[14] = s10, s14, s2, s6

            s3, s7, s11, s15 = state[3], state[7], state[11], state[15]
            state[3], state[7], state[11], state[15] = s15, s3, s7, s11

            # 3. MixColumns
            for c in range(0, 16, 4):
                c0, c1, c2, c3 = state[c], state[c + 1], state[c + 2], state[c + 3]
                state[c] = _MUL2[c0] ^ _MUL3[c1] ^ c2 ^ c3
                state[c + 1] = c0 ^ _MUL2[c1] ^ _MUL3[c2] ^ c3
                state[c + 2] = c0 ^ c1 ^ _MUL2[c2] ^ _MUL3[c3]
                state[c + 3] = _MUL3[c0] ^ c1 ^ c2 ^ _MUL2[c3]

            # 4. AddRoundKey
            rk = round_keys[round_idx]
            for i in range(16):
                state[i] ^= rk[i]

        # Final Round (no MixColumns)
        # 1. SubBytes
        for i in range(16):
            state[i] = S_BOX[state[i]]

        # 2. ShiftRows
        s1, s5, s9, s13 = state[1], state[5], state[9], state[13]
        state[1], state[5], state[9], state[13] = s5, s9, s13, s1

        s2, s6, s10, s14 = state[2], state[6], state[10], state[14]
        state[2], state[6], state[10], state[14] = s10, s14, s2, s6

        s3, s7, s11, s15 = state[3], state[7], state[11], state[15]
        state[3], state[7], state[11], state[15] = s15, s3, s7, s11

        # 3. AddRoundKey
        rk_final = round_keys[nr]
        for i in range(16):
            state[i] ^= rk_final[i]

        return bytes(state)

    def decrypt_block(self, block: Union[bytes, bytearray, memoryview]) -> bytes:
        """Decrypt a single 16-byte block.

        Args:
            block: Exactly 16 bytes of ciphertext.

        Returns:
            bytes: Exactly 16 bytes of plaintext.
        """
        if len(block) != 16:
            raise ValueError(f"AES block size must be 16 bytes, got {len(block)}")

        state = bytearray(block)
        round_keys = self._round_keys
        nr = self._nr

        # Initial Round: AddRoundKey with final round key
        rk_final = round_keys[nr]
        for i in range(16):
            state[i] ^= rk_final[i]

        # Rounds Nr - 1 down to 1
        for round_idx in range(nr - 1, 0, -1):
            # 1. InvShiftRows
            # Row 1: s1, s5, s9, s13 -> s13, s1, s5, s9
            # Row 2: s2, s6, s10, s14 -> s10, s14, s2, s6
            # Row 3: s3, s7, s11, s15 -> s7, s11, s15, s3
            s1, s5, s9, s13 = state[1], state[5], state[9], state[13]
            state[1], state[5], state[9], state[13] = s13, s1, s5, s9

            s2, s6, s10, s14 = state[2], state[6], state[10], state[14]
            state[2], state[6], state[10], state[14] = s10, s14, s2, s6

            s3, s7, s11, s15 = state[3], state[7], state[11], state[15]
            state[3], state[7], state[11], state[15] = s7, s11, s15, s3

            # 2. InvSubBytes
            for i in range(16):
                state[i] = INV_S_BOX[state[i]]

            # 3. AddRoundKey
            rk = round_keys[round_idx]
            for i in range(16):
                state[i] ^= rk[i]

            # 4. InvMixColumns
            for c in range(0, 16, 4):
                c0, c1, c2, c3 = state[c], state[c + 1], state[c + 2], state[c + 3]
                state[c] = _MUL14[c0] ^ _MUL11[c1] ^ _MUL13[c2] ^ _MUL9[c3]
                state[c + 1] = _MUL9[c0] ^ _MUL14[c1] ^ _MUL11[c2] ^ _MUL13[c3]
                state[c + 2] = _MUL13[c0] ^ _MUL9[c1] ^ _MUL14[c2] ^ _MUL11[c3]
                state[c + 3] = _MUL11[c0] ^ _MUL13[c1] ^ _MUL9[c2] ^ _MUL14[c3]

        # Final Round (no InvMixColumns)
        # 1. InvShiftRows
        s1, s5, s9, s13 = state[1], state[5], state[9], state[13]
        state[1], state[5], state[9], state[13] = s13, s1, s5, s9

        s2, s6, s10, s14 = state[2], state[6], state[10], state[14]
        state[2], state[6], state[10], state[14] = s10, s14, s2, s6

        s3, s7, s11, s15 = state[3], state[7], state[11], state[15]
        state[3], state[7], state[11], state[15] = s7, s11, s15, s3

        # 2. InvSubBytes
        for i in range(16):
            state[i] = INV_S_BOX[state[i]]

        # 3. AddRoundKey with rk0
        rk0 = round_keys[0]
        for i in range(16):
            state[i] ^= rk0[i]

        return bytes(state)

    def decrypt_cbc(
        self, data: Union[bytes, bytearray, memoryview], iv: Union[bytes, bytearray, memoryview]
    ) -> bytes:
        """Decrypt ciphertext in Cipher Block Chaining (CBC) mode.

        Args:
            data: Ciphertext bytes (length must be multiple of 16).
            iv: Initialization Vector (exactly 16 bytes).

        Returns:
            bytes: Decrypted plaintext (without padding removal).
        """
        input_bytes = bytes(data)
        iv_bytes = bytes(iv)

        if len(iv_bytes) != 16:
            raise ValueError(f"IV must be exactly 16 bytes, got {len(iv_bytes)}")
        if len(input_bytes) % 16 != 0:
            raise ValueError(f"Ciphertext length ({len(input_bytes)}) must be multiple of 16")

        out = bytearray(len(input_bytes))
        prev_block = iv_bytes

        for idx in range(0, len(input_bytes), 16):
            cipher_block = input_bytes[idx : idx + 16]
            plain_block = self.decrypt_block(cipher_block)
            for j in range(16):
                out[idx + j] = plain_block[j] ^ prev_block[j]
            prev_block = cipher_block

        return bytes(out)

    def encrypt_cbc(
        self, data: Union[bytes, bytearray, memoryview], iv: Union[bytes, bytearray, memoryview]
    ) -> bytes:
        """Encrypt plaintext in Cipher Block Chaining (CBC) mode.

        Args:
            data: Plaintext bytes (length must be multiple of 16).
            iv: Initialization Vector (exactly 16 bytes).

        Returns:
            bytes: Encrypted ciphertext.
        """
        input_bytes = bytes(data)
        iv_bytes = bytes(iv)

        if len(iv_bytes) != 16:
            raise ValueError(f"IV must be exactly 16 bytes, got {len(iv_bytes)}")
        if len(input_bytes) % 16 != 0:
            raise ValueError(f"Plaintext length ({len(input_bytes)}) must be multiple of 16")

        out = bytearray(len(input_bytes))
        prev_block = iv_bytes

        for idx in range(0, len(input_bytes), 16):
            block_to_encrypt = bytearray(16)
            for j in range(16):
                block_to_encrypt[j] = input_bytes[idx + j] ^ prev_block[j]
            cipher_block = self.encrypt_block(block_to_encrypt)
            out[idx : idx + 16] = cipher_block
            prev_block = cipher_block

        return bytes(out)


def pkcs7_pad(data: Union[bytes, bytearray, memoryview], block_size: int = 16) -> bytes:
    """Apply PKCS#7 padding to data for given block size."""
    raw = bytes(data)
    pad_len = block_size - (len(raw) % block_size)
    return raw + bytes([pad_len] * pad_len)


def pkcs7_unpad(data: Union[bytes, bytearray, memoryview]) -> bytes:
    """Validate and remove PKCS#7 padding.

    Args:
        data: Padded byte sequence.

    Returns:
        bytes: Unpadded data.

    Raises:
        ValueError: If padding is invalid.
    """
    raw = bytes(data)
    if not raw:
        raise ValueError("Cannot unpad empty data")

    pad_len = raw[-1]
    if pad_len < 1 or pad_len > 16 or pad_len > len(raw):
        raise ValueError(f"Invalid PKCS#7 padding byte: {pad_len}")

    expected_padding = bytes([pad_len] * pad_len)
    if raw[-pad_len:] != expected_padding:
        raise ValueError("Corrupted PKCS#7 padding sequence")

    return raw[:-pad_len]


def aes_decrypt_cbc_with_iv(
    key: Union[bytes, bytearray, memoryview], data: Union[bytes, bytearray, memoryview]
) -> bytes:
    """Decrypt PDF AES stream or string where the 16-byte IV is prepended to ciphertext.

    Per PDF 32000-1 §7.6.2 (Algorithm 4 / AES):
    The 16-byte initialization vector (IV) is stored as the first 16 bytes of the stream.

    Args:
        key: AES-128 or AES-256 key.
        data: Ciphertext with prepended 16-byte IV.

    Returns:
        bytes: Unpadded plaintext.
    """
    raw = bytes(data)
    if len(raw) < 32:
        raise ValueError(
            f"AES CBC payload too short: {len(raw)} bytes (requires 16-byte IV + at least 16-byte block)"
        )

    iv = raw[:16]
    ciphertext = raw[16:]

    cipher = AES(key)
    decrypted = cipher.decrypt_cbc(ciphertext, iv)
    return pkcs7_unpad(decrypted)


def aes_encrypt_cbc_with_iv(
    key: Union[bytes, bytearray, memoryview],
    plaintext: Union[bytes, bytearray, memoryview],
    iv: Union[bytes, bytearray, memoryview, None] = None,
) -> bytes:
    """Encrypt data in AES CBC mode with prepended IV and PKCS#7 padding.

    Args:
        key: AES key.
        plaintext: Plaintext data.
        iv: Optional 16-byte IV (if None, a deterministic or random IV is used).

    Returns:
        bytes: 16-byte IV + ciphertext.
    """
    import os

    iv_bytes = os.urandom(16) if iv is None else bytes(iv)
    padded = pkcs7_pad(plaintext, block_size=16)

    cipher = AES(key)
    ciphertext = cipher.encrypt_cbc(padded, iv_bytes)
    return iv_bytes + ciphertext
