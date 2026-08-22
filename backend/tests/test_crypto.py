import pytest
from cryptography.fernet import Fernet

from app.auth import crypto


def test_token_roundtrips_through_encrypt_and_decrypt():
    plaintext = "gho_1234567890abcdefghijklmnopqrstuvwxyz"
    ciphertext = crypto.encrypt_token(plaintext)
    assert crypto.decrypt_token(ciphertext) == plaintext


def test_encrypted_token_bytes_contain_no_plaintext_substring():
    plaintext = "gho_1234567890abcdefghijklmnopqrstuvwxyz"
    ciphertext = crypto.encrypt_token(plaintext)
    assert plaintext.encode("utf-8") not in ciphertext
    # Defense in depth: no 8-char window of the plaintext survives either.
    for i in range(0, len(plaintext) - 8):
        assert plaintext[i : i + 8].encode("utf-8") not in ciphertext


def test_resolve_key_refuses_to_start_in_production_with_missing_key(monkeypatch):
    monkeypatch.setattr(crypto.settings, "COMPASS_ENV", "production")
    monkeypatch.setattr(crypto.settings, "COMPASS_TOKEN_ENCRYPTION_KEY", "")
    with pytest.raises(RuntimeError, match="COMPASS_TOKEN_ENCRYPTION_KEY"):
        crypto._resolve_key()


def test_resolve_key_refuses_to_start_in_production_with_an_invalid_key(monkeypatch):
    monkeypatch.setattr(crypto.settings, "COMPASS_ENV", "production")
    monkeypatch.setattr(crypto.settings, "COMPASS_TOKEN_ENCRYPTION_KEY", "not-a-valid-fernet-key")
    with pytest.raises(RuntimeError, match="COMPASS_TOKEN_ENCRYPTION_KEY"):
        crypto._resolve_key()


def test_resolve_key_derives_an_ephemeral_key_in_development_and_warns(monkeypatch, caplog):
    monkeypatch.setattr(crypto.settings, "COMPASS_ENV", "development")
    monkeypatch.setattr(crypto.settings, "COMPASS_TOKEN_ENCRYPTION_KEY", "")
    with caplog.at_level("WARNING"):
        key = crypto._resolve_key()
    Fernet(key)  # does not raise -- a structurally valid key was produced
    assert any("ephemeral" in record.message for record in caplog.records)


def test_resolve_key_accepts_a_valid_configured_key(monkeypatch):
    valid_key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setattr(crypto.settings, "COMPASS_ENV", "production")
    monkeypatch.setattr(crypto.settings, "COMPASS_TOKEN_ENCRYPTION_KEY", valid_key)
    assert crypto._resolve_key() == valid_key.encode("utf-8")
