"""Tests for password hashing helpers in auth module."""

from llm_trading_system.api import auth


def test_verify_password_falls_back_to_bcrypt(monkeypatch):
    """If passlib fails we still validate credentials with raw bcrypt."""

    hashed = auth._USERS_DB["admin"].hashed_password

    def _boom(*args, **kwargs):  # pragma: no cover - simple stub
        raise ValueError("password cannot be longer than 72 bytes")

    monkeypatch.setattr(auth.pwd_context, "verify", _boom)

    assert auth.verify_password("admin123", hashed)


def test_get_password_hash_falls_back_to_bcrypt(monkeypatch):
    """Password hashing also works without the passlib backend."""

    def _boom(*args, **kwargs):  # pragma: no cover - simple stub
        raise RuntimeError("backend unavailable")

    monkeypatch.setattr(auth.pwd_context, "hash", _boom)

    hashed = auth.get_password_hash("secret123")
    assert hashed.startswith("$2b$") or hashed.startswith("$2a$")
    assert auth.verify_password("secret123", hashed)
