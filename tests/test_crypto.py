"""Compatibilidad del cifrado con el backend Go.

El formato en disco es base64std(nonce_12B || ciphertext || tag_GCM), idéntico
al gcm.Seal(nonce, nonce, plaintext, nil) de Go con clave AES-256.
"""

import base64

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from cognits.storage.files import NONCE_SIZE, decrypt_with_key, encrypt_with_key


def test_roundtrip():
    key = bytes(range(32))
    for plaintext in ["", "sk-abc123", "clave con ñ y 中文"]:
        if plaintext == "":
            continue
        ct = encrypt_with_key(key, plaintext)
        assert decrypt_with_key(key, ct) == plaintext


def test_wire_format():
    key = bytes(32)
    raw = base64.b64decode(encrypt_with_key(key, "x"))
    # nonce de 12 bytes + ciphertext(1) + tag GCM(16)
    assert len(raw) == NONCE_SIZE + 1 + 16


def test_go_compatible_vector():
    # Vector construido con la misma semántica que gcm.Seal de Go:
    # AES-256-GCM, nonce de 12 bytes prefijado, tag de 16 bytes al final.
    key = b"0123456789abcdef0123456789abcdef"
    nonce = b"\x00" * 12
    ct = AESGCM(key).encrypt(nonce, b"hola", None)
    vector = base64.b64encode(nonce + ct).decode()
    assert decrypt_with_key(key, vector) == "hola"


def test_short_ciphertext():
    with pytest.raises(ValueError):
        decrypt_with_key(bytes(32), base64.b64encode(b"corto").decode())


def test_tamper_detection():
    key = bytes(32)
    raw = bytearray(base64.b64decode(encrypt_with_key(key, "secreto")))
    raw[-1] ^= 0xFF
    with pytest.raises(Exception):
        decrypt_with_key(key, base64.b64encode(bytes(raw)).decode())
