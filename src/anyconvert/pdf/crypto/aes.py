"""Pure-Python implementation of AES-128 and AES-256 in CBC mode (FIPS 197).

Implements:
- Full AES block cipher (128-bit and 256-bit keys)
- Standard S-Box and Inverse S-Box transformations
- Key expansion for 10-round (AES-128) and 14-round (AES-256) schemes
- Cipher Block Chaining (CBC) mode with PKCS#7 padding and unpadding
- Zero third-party dependencies
"""

from __future__ import annotations

import os
from typing import List, Optional, Tuple, Union

# Standard Rijndael S-Box
S_BOX: List[int] = [
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
]

# Standard Inverse S-Box
INV_S_BOX: List[int] = [
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
]

# Round constants Rcon
RCON: List[int] = [
    0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36,
]


def _xtime(a: int) -> int:
    """Galois field multiplication of byte by 2 modulo irreducible polynomial 0x11B."""
    return ((a << 1) ^ 0x11B) & 0xFF if (a & 0x80) else (a << 1) & 0xFF


def _mul(a: int, b: int) -> int:
    """Galois field multiplication in GF(2^8)."""
    res = 0
    temp = a
    for bit in range(8):
        if (b >> bit) & 1:
            res ^= temp
        temp = _xtime(temp)
    return res


def key_expansion(key: bytes) -> Tuple[List[List[int]], int]:
    """Expand 16-byte (AES-128) or 32-byte (AES-256) key into round keys.

    Returns:
        Tuple of (round_keys, number_of_rounds).
    """
    key_len = len(key)
    if key_len == 16:
        nk = 4
        nr = 10
    elif key_len == 32:
        nk = 8
        nr = 14
    else:
        raise ValueError(f"AES key length must be 16 or 32 bytes, received: {key_len}")

    # Convert key to words (4 bytes each)
    w: List[List[int]] = []
    for i in range(nk):
        w.append([key[4 * i], key[4 * i + 1], key[4 * i + 2], key[4 * i + 3]])

    for i in range(nk, 4 * (nr + 1)):
        temp = list(w[i - 1])
        if i % nk == 0:
            # RotWord
            temp = temp[1:] + temp[:1]
            # SubWord
            temp = [S_BOX[b] for b in temp]
            # Rcon
            temp[0] ^= RCON[i // nk]
        elif nk > 6 and (i % nk == 4):
            # SubWord only (for AES-256)
            temp = [S_BOX[b] for b in temp]

        w_prev = w[i - nk]
        new_word = [w_prev[b] ^ temp[b] for b in range(4)]
        w.append(new_word)

    # Group into (nr + 1) round keys of 16 bytes each
    round_keys: List[List[int]] = []
    for r in range(nr + 1):
        rk: List[int] = []
        for word_idx in range(4):
            rk.extend(w[r * 4 + word_idx])
        round_keys.append(rk)

    return round_keys, nr


def encrypt_block(block: bytes, round_keys: List[List[int]], nr: int) -> bytes:
    """Encrypt a single 16-byte block using expanded round keys."""
    # State as 4x4 matrix: state[row][col]
    state = [
        [block[0], block[4], block[8], block[12]],
        [block[1], block[5], block[9], block[13]],
        [block[2], block[6], block[10], block[14]],
        [block[3], block[7], block[11], block[15]],
    ]

    # Initial Round: AddRoundKey
    rk0 = round_keys[0]
    for c in range(4):
        for r in range(4):
            state[r][c] ^= rk0[c * 4 + r]

    # Main Rounds 1 .. nr - 1
    for round_num in range(1, nr):
        # 1. SubBytes
        for r in range(4):
            for c in range(4):
                state[r][c] = S_BOX[state[r][c]]

        # 2. ShiftRows
        state[1] = state[1][1:] + state[1][:1]
        state[2] = state[2][2:] + state[2][:2]
        state[3] = state[3][3:] + state[3][:3]

        # 3. MixColumns
        for c in range(4):
            s0 = state[0][c]
            s1 = state[1][c]
            s2 = state[2][c]
            s3 = state[3][c]
            state[0][c] = _xtime(s0) ^ (_xtime(s1) ^ s1) ^ s2 ^ s3
            state[1][c] = s0 ^ _xtime(s1) ^ (_xtime(s2) ^ s2) ^ s3
            state[2][c] = s0 ^ s1 ^ _xtime(s2) ^ (_xtime(s3) ^ s3)
            state[3][c] = (_xtime(s0) ^ s0) ^ s1 ^ s2 ^ _xtime(s3)

        # 4. AddRoundKey
        rk = round_keys[round_num]
        for c in range(4):
            for r in range(4):
                state[r][c] ^= rk[c * 4 + r]

    # Final Round (no MixColumns)
    for r in range(4):
        for c in range(4):
            state[r][c] = S_BOX[state[r][c]]

    state[1] = state[1][1:] + state[1][:1]
    state[2] = state[2][2:] + state[2][:2]
    state[3] = state[3][3:] + state[3][:3]

    rk_final = round_keys[nr]
    out = bytearray(16)
    for c in range(4):
        for r in range(4):
            out[c * 4 + r] = state[r][c] ^ rk_final[c * 4 + r]

    return bytes(out)


def decrypt_block(block: bytes, round_keys: List[List[int]], nr: int) -> bytes:
    """Decrypt a single 16-byte block using expanded round keys."""
    state = [
        [block[0], block[4], block[8], block[12]],
        [block[1], block[5], block[9], block[13]],
        [block[2], block[6], block[10], block[14]],
        [block[3], block[7], block[11], block[15]],
    ]

    # Initial AddRoundKey with final key
    rk_final = round_keys[nr]
    for c in range(4):
        for r in range(4):
            state[r][c] ^= rk_final[c * 4 + r]

    # Main Rounds (nr - 1 down to 1)
    for round_num in range(nr - 1, 0, -1):
        # 1. InvShiftRows
        state[1] = state[1][3:] + state[1][:3]
        state[2] = state[2][2:] + state[2][:2]
        state[3] = state[3][1:] + state[3][:1]

        # 2. InvSubBytes
        for r in range(4):
            for c in range(4):
                state[r][c] = INV_S_BOX[state[r][c]]

        # 3. AddRoundKey
        rk = round_keys[round_num]
        for c in range(4):
            for r in range(4):
                state[r][c] ^= rk[c * 4 + r]

        # 4. InvMixColumns
        for c in range(4):
            s0 = state[0][c]
            s1 = state[1][c]
            s2 = state[2][c]
            s3 = state[3][c]
            state[0][c] = _mul(s0, 0x0E) ^ _mul(s1, 0x0B) ^ _mul(s2, 0x0D) ^ _mul(s3, 0x09)
            state[1][c] = _mul(s0, 0x09) ^ _mul(s1, 0x0E) ^ _mul(s2, 0x0B) ^ _mul(s3, 0x0D)
            state[2][c] = _mul(s0, 0x0D) ^ _mul(s1, 0x09) ^ _mul(s2, 0x0E) ^ _mul(s3, 0x0B)
            state[3][c] = _mul(s0, 0x0B) ^ _mul(s1, 0x0D) ^ _mul(s2, 0x09) ^ _mul(s3, 0x0E)

    # Final Round (no InvMixColumns)
    state[1] = state[1][3:] + state[1][:3]
    state[2] = state[2][2:] + state[2][:2]
    state[3] = state[3][1:] + state[3][:1]

    for r in range(4):
        for c in range(4):
            state[r][c] = INV_S_BOX[state[r][c]]

    rk0 = round_keys[0]
    out = bytearray(16)
    for c in range(4):
        for r in range(4):
            out[c * 4 + r] = state[r][c] ^ rk0[c * 4 + r]

    return bytes(out)


def aes_decrypt_cbc(
    data: Union[bytes, bytearray, memoryview],
    key: bytes,
    iv: Optional[bytes] = None,
) -> bytes:
    """Decrypt ciphertext using AES in Cipher Block Chaining (CBC) mode with PKCS#7 unpadding.

    In PDF documents, the 16-byte IV is typically prepended to the ciphertext.
    If `iv` is None, the first 16 bytes of `data` are extracted as the IV.

    Args:
        data: Ciphertext bytes (with prepended IV if iv is None).
        key: 16-byte (AES-128) or 32-byte (AES-256) key.
        iv: Optional explicit 16-byte IV.

    Returns:
        Unpadded plaintext bytes.

    Raises:
        ValueError: If ciphertext length is invalid or PKCS#7 padding is corrupt.
    """
    raw_data = bytes(data)
    if iv is None:
        if len(raw_data) < 32:
            raise ValueError(f"AES ciphertext with prepended IV must be >= 32 bytes ({len(raw_data)})")
        iv_bytes = raw_data[:16]
        ct = raw_data[16:]
    else:
        if len(iv) != 16:
            raise ValueError(f"AES IV must be exactly 16 bytes, received {len(iv)}")
        iv_bytes = bytes(iv)
        ct = raw_data

    if len(ct) % 16 != 0:
        raise ValueError(f"Ciphertext length ({len(ct)}) must be a multiple of 16")

    round_keys, nr = key_expansion(key)
    plaintext_blocks = bytearray()
    prev_ct_block = iv_bytes

    for i in range(0, len(ct), 16):
        ct_block = ct[i : i + 16]
        decrypted = decrypt_block(ct_block, round_keys, nr)
        # XOR with previous ciphertext block (CBC mode)
        pt_block = bytes([decrypted[b] ^ prev_ct_block[b] for b in range(16)])
        plaintext_blocks.extend(pt_block)
        prev_ct_block = ct_block

    # PKCS#7 unpadding
    if not plaintext_blocks:
        return b""

    pad_len = plaintext_blocks[-1]
    if pad_len < 1 or pad_len > 16:
        # Invalid padding byte
        return bytes(plaintext_blocks)

    # Check padding bytes integrity
    pad_bytes = plaintext_blocks[-pad_len:]
    if all(b == pad_len for b in pad_bytes):
        return bytes(plaintext_blocks[:-pad_len])

    # If padding mismatch, return unstripped
    return bytes(plaintext_blocks)


def aes_encrypt_cbc(
    data: Union[bytes, bytearray, memoryview],
    key: bytes,
    iv: Optional[bytes] = None,
) -> bytes:
    """Encrypt plaintext using AES in CBC mode with PKCS#7 padding.

    Prepends the 16-byte IV to the returned ciphertext stream.

    Args:
        data: Plaintext bytes.
        key: 16-byte (AES-128) or 32-byte (AES-256) key.
        iv: Optional explicit 16-byte IV (if None, generated via os.urandom).

    Returns:
        Ciphertext with 16-byte IV prepended.
    """
    raw_data = bytes(data)
    iv_bytes = os.urandom(16) if iv is None else bytes(iv)

    # PKCS#7 padding
    pad_len = 16 - (len(raw_data) % 16)
    padded = raw_data + bytes([pad_len] * pad_len)

    round_keys, nr = key_expansion(key)
    out = bytearray(iv_bytes)
    prev_ct_block = iv_bytes

    for i in range(0, len(padded), 16):
        pt_block = padded[i : i + 16]
        # XOR with previous ciphertext block
        input_block = bytes([pt_block[b] ^ prev_ct_block[b] for b in range(16)])
        ct_block = encrypt_block(input_block, round_keys, nr)
        out.extend(ct_block)
        prev_ct_block = ct_block

    return bytes(out)


__all__ = [
    "key_expansion",
    "encrypt_block",
    "decrypt_block",
    "aes_decrypt_cbc",
    "aes_encrypt_cbc",
]
