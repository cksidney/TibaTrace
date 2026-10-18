"""Versioned authenticated encryption for clinical object bytes at rest."""

from __future__ import annotations

import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_MAGIC_PREFIX = b"TIBATRACE-CLINICAL-OBJECT"
_MAGIC = _MAGIC_PREFIX + b"\x01"
_NONCE_BYTES = 12
_MAX_KEY_ID_BYTES = 64


class DocumentEncryptionError(ValueError):
    """Stored document bytes cannot be safely encrypted or decrypted."""


def decode_document_key(encoded_key: str) -> bytes:
    """Decode a base64url-encoded 256-bit AES key."""
    if not isinstance(encoded_key, str) or not encoded_key:
        raise DocumentEncryptionError("Document encryption key is invalid.")
    try:
        encoded = encoded_key.encode("ascii")
        padded = encoded + b"=" * (-len(encoded) % 4)
        raw = base64.b64decode(padded, altchars=b"-_", validate=True)
    except (UnicodeEncodeError, binascii.Error, ValueError) as exc:
        raise DocumentEncryptionError("Document encryption key is invalid.") from exc
    if len(raw) != 32:
        raise DocumentEncryptionError("Document encryption key must decode to 32 bytes.")
    return raw


def validate_document_keyring(keyring: object, active_key_id: object) -> None:
    """Validate key IDs, AES key material, and the configured write key."""
    if not isinstance(keyring, dict) or not keyring:
        raise DocumentEncryptionError("Document encryption keyring is required.")
    if not isinstance(active_key_id, str) or active_key_id not in keyring:
        raise DocumentEncryptionError("Active document encryption key is missing from keyring.")
    for key_id, encoded_key in keyring.items():
        if not isinstance(key_id, str):
            raise DocumentEncryptionError("Document encryption key IDs must be strings.")
        try:
            key_id_bytes = key_id.encode("ascii")
        except UnicodeEncodeError as exc:
            raise DocumentEncryptionError("Document encryption key ID must be ASCII.") from exc
        if not key_id_bytes or len(key_id_bytes) > _MAX_KEY_ID_BYTES:
            raise DocumentEncryptionError("Document encryption key ID length is invalid.")
        decode_document_key(encoded_key)


def encrypt_document_bytes(plaintext: bytes, *, key_id: str, key: str, associated_data: str) -> bytes:
    """Encrypt bytes with AES-256-GCM and bind ciphertext to its object key."""
    if not isinstance(plaintext, bytes):
        raise DocumentEncryptionError("Document content must be bytes.")
    try:
        key_id_bytes = key_id.encode("ascii")
        aad = associated_data.encode("utf-8")
    except (AttributeError, UnicodeEncodeError) as exc:
        raise DocumentEncryptionError("Document encryption metadata is invalid.") from exc
    if not key_id_bytes or len(key_id_bytes) > _MAX_KEY_ID_BYTES:
        raise DocumentEncryptionError("Document encryption key ID length is invalid.")
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(decode_document_key(key)).encrypt(nonce, plaintext, aad)
    return _MAGIC + bytes([len(key_id_bytes)]) + key_id_bytes + nonce + ciphertext


def decrypt_document_bytes(stored: bytes, *, keyring: dict[str, str], associated_data: str) -> tuple[bytes, str | None]:
    """Decrypt a TibaTrace envelope; return legacy plaintext with no key ID."""
    if not stored.startswith(_MAGIC_PREFIX):
        return stored, None
    if not stored.startswith(_MAGIC):
        raise DocumentEncryptionError("Stored clinical object has an unsupported encryption version.")
    offset = len(_MAGIC)
    if len(stored) <= offset:
        raise DocumentEncryptionError("Stored clinical object encryption header is incomplete.")
    key_id_length = stored[offset]
    offset += 1
    if key_id_length == 0 or key_id_length > _MAX_KEY_ID_BYTES:
        raise DocumentEncryptionError("Stored clinical object key ID is invalid.")
    required = offset + key_id_length + _NONCE_BYTES + 16
    if len(stored) < required:
        raise DocumentEncryptionError("Stored clinical object encryption envelope is incomplete.")
    try:
        key_id = stored[offset : offset + key_id_length].decode("ascii")
    except UnicodeDecodeError as exc:
        raise DocumentEncryptionError("Stored clinical object key ID is invalid.") from exc
    offset += key_id_length
    nonce = stored[offset : offset + _NONCE_BYTES]
    ciphertext = stored[offset + _NONCE_BYTES :]
    encoded_key = keyring.get(key_id)
    if not encoded_key:
        raise DocumentEncryptionError("Stored clinical object references an unavailable key.")
    try:
        aad = associated_data.encode("utf-8")
        plaintext = AESGCM(decode_document_key(encoded_key)).decrypt(nonce, ciphertext, aad)
    except (InvalidTag, UnicodeEncodeError) as exc:
        raise DocumentEncryptionError("Stored clinical object failed authenticated decryption.") from exc
    return plaintext, key_id
