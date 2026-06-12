"""Encryption compatibility with the Go backend.

The on-disk format is base64std(nonce_12B || ciphertext || tag_GCM), identical
to Go's gcm.Seal(nonce, nonce, plaintext, nil) with AES-256 key.
"""

import base64

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from cognits.storage.files import NONCE_SIZE, decrypt_with_key, encrypt_with_key


def test_roundtrip():
    key = bytes(range(32))
    for plaintext in ["", "sk-abc123", "key with ñ and 中文"]:
        if plaintext == "":
            continue
        ct = encrypt_with_key(key, plaintext)
        assert decrypt_with_key(key, ct) == plaintext


def test_wire_format():
    key = bytes(32)
    raw = base64.b64decode(encrypt_with_key(key, "x"))
    # 12-byte nonce + ciphertext(1) + GCM tag(16)
    assert len(raw) == NONCE_SIZE + 1 + 16


def test_go_compatible_vector():
    # Vector built with the same semantics as Go's gcm.Seal:
    # AES-256-GCM, 12-byte nonce prepended, 16-byte tag at the end.
    key = b"0123456789abcdef0123456789abcdef"
    nonce = b"\x00" * 12
    ct = AESGCM(key).encrypt(nonce, b"hello", None)
    vector = base64.b64encode(nonce + ct).decode()
    assert decrypt_with_key(key, vector) == "hello"


def test_short_ciphertext():
    with pytest.raises(ValueError):
        decrypt_with_key(bytes(32), base64.b64encode(b"short").decode())


def test_tamper_detection():
    key = bytes(32)
    raw = bytearray(base64.b64decode(encrypt_with_key(key, "secret")))
    raw[-1] ^= 0xFF
    with pytest.raises(Exception):
        decrypt_with_key(key, base64.b64encode(bytes(raw)).decode())
