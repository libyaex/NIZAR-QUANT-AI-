"""Fernet encryption helpers for exchange API secrets (encrypt at rest)."""
import base64
import logging

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


class CredentialVault:
    """Encrypts/decrypts exchange secrets. Never log full secrets."""

    def __init__(self, key: str):
        if not key:
            raise ValueError("CREDENTIAL_ENCRYPTION_KEY is not configured")
        self._fernet = Fernet(key.encode() if isinstance(key, str) else key)

    def encrypt(self, secret: str) -> str:
        if not secret:
            return ""
        token = self._fernet.encrypt(secret.encode())
        return base64.urlsafe_b64encode(token).decode()

    def decrypt(self, token: str) -> str:
        if not token:
            return ""
        try:
            return self._fernet.decrypt(base64.urlsafe_b64decode(token.encode())).decode()
        except (InvalidToken, ValueError):
            logger.error("Failed to decrypt credential (wrong key or corrupted data)")
            raise


def mask_secret(secret: str) -> str:
    """Return a safe display form like `abcd****wxyz` for audit logs only."""
    if not secret:
        return ""
    if len(secret) <= 8:
        return "****"
    return f"{secret[:4]}****{secret[-4:]}"