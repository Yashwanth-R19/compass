"""Fernet-based encryption for GitHub access tokens at rest (session 02,
Part B). ``users.access_token_encrypted`` is the only place a GitHub token
is ever persisted, and it must never be stored, logged, or returned
plaintext -- plan/RULES.md sec 10.

The key comes from ``COMPASS_TOKEN_ENCRYPTION_KEY`` (a urlsafe-base64
32-byte Fernet key, e.g. generated with ``Fernet.generate_key()`` -- see
DEPLOY.md). In production (``COMPASS_ENV=production``) a missing or invalid
key is a startup-fatal error: the app must refuse to start rather than risk
silently storing a token unencrypted or, worse, using a key nobody wrote
down (tokens become permanently undecryptable the moment the process
restarts with a different derived key). In development, a missing key logs
a loud warning and derives an ephemeral one for the life of the process --
convenient for local dev, and safe specifically because nothing in
development is expected to persist across restarts anyway.
"""

import logging

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

logger = logging.getLogger(__name__)


def _is_valid_fernet_key(key: str) -> bool:
    try:
        Fernet(key.encode("utf-8"))
    except (ValueError, TypeError):
        return False
    return True


def _resolve_key() -> bytes:
    key = settings.COMPASS_TOKEN_ENCRYPTION_KEY
    if key and _is_valid_fernet_key(key):
        return key.encode("utf-8")

    if settings.COMPASS_ENV == "production":
        raise RuntimeError(
            "COMPASS_TOKEN_ENCRYPTION_KEY is missing or is not a valid Fernet key. "
            "Refusing to start in production -- see DEPLOY.md for how to generate one "
            "(Fernet.generate_key()). Compass must never store a GitHub token "
            "unencrypted, and a wrong/ephemeral key would make every stored token "
            "permanently undecryptable the moment the process restarts."
        )

    logger.warning(
        "COMPASS_TOKEN_ENCRYPTION_KEY is missing or invalid -- deriving an ephemeral "
        "Fernet key for this process only. Any token encrypted under it will NOT be "
        "decryptable after a restart. Set COMPASS_TOKEN_ENCRYPTION_KEY for anything "
        "beyond local development."
    )
    return Fernet.generate_key()


_FERNET = Fernet(_resolve_key())


def encrypt_token(plaintext: str) -> bytes:
    """Encrypts ``plaintext`` (a GitHub access token) for storage in
    ``users.access_token_encrypted``. Never call this with anything other
    than the token itself -- the whole point is that nothing upstream of
    this function ever needs to see the token again in plaintext."""
    return _FERNET.encrypt(plaintext.encode("utf-8"))


def decrypt_token(ciphertext: bytes) -> str:
    """Decrypts a value previously produced by ``encrypt_token``. Raises
    ``cryptography.fernet.InvalidToken`` if ``ciphertext`` was encrypted
    under a different key (e.g. COMPASS_TOKEN_ENCRYPTION_KEY rotated or --
    in development -- the process restarted since the token was stored) or
    is corrupted -- callers should treat that as "this stored token is no
    longer usable, the user must reconnect," never as a fatal error."""
    try:
        return _FERNET.decrypt(ciphertext).decode("utf-8")
    except InvalidToken:
        raise


__all__ = ["decrypt_token", "encrypt_token"]
