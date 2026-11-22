"""Fernet symmetric encryption helpers for channel credentials stored at rest."""

import json

from cryptography.fernet import Fernet, InvalidToken


class CredentialCryptoError(ValueError):
    """Raised when channel credentials cannot be encrypted or decrypted."""


def _build_fernet(fernet_key: str) -> Fernet:
    key = fernet_key.strip()
    if not key:
        raise CredentialCryptoError("FERNET_KEY environment variable is required")
    try:
        return Fernet(key.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise CredentialCryptoError(f"Invalid FERNET_KEY format: {exc}") from exc


def generate_fernet_key() -> str:
    """Generate a new URL-safe base64-encoded 32-byte Fernet key."""
    return Fernet.generate_key().decode("utf-8")


def encrypt_credentials(payload: dict[str, str], *, fernet_key: str) -> str:
    """Encrypt a dictionary of channel credentials into a Fernet token string."""
    fernet = _build_fernet(fernet_key)
    raw_json = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return fernet.encrypt(raw_json).decode("utf-8")


def decrypt_credentials(token: str, *, fernet_key: str) -> dict[str, str]:
    """Decrypt a stored Fernet token back into a string credential mapping."""
    fernet = _build_fernet(fernet_key)
    try:
        raw_bytes = fernet.decrypt(token.encode("utf-8"))
    except InvalidToken as exc:
        raise CredentialCryptoError("Failed to decrypt channel credentials") from exc

    parsed = json.loads(raw_bytes.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise CredentialCryptoError("Decrypted credentials payload must be a JSON object")
    return {str(k): str(v) for k, v in parsed.items()}
