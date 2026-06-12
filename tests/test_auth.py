import hashlib

import pytest
from fastapi import HTTPException

import auth


def test_get_expected_token_uses_password_and_salt(monkeypatch):
    monkeypatch.setattr(auth, "ACCESS_PASSWORD", "secret")

    expected = hashlib.sha256(
        f"secret_{auth.TOKEN_SALT}".encode("utf-8")
    ).hexdigest()

    assert auth.get_expected_token() == expected


def test_verify_token_accepts_valid_bearer_token(monkeypatch):
    monkeypatch.setattr(auth, "ACCESS_PASSWORD", "secret")
    token = auth.get_expected_token()

    assert auth.verify_token(f"Bearer {token}") is True


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        "",
        "Token abc",
        "Bearer wrong",
        "Bearer",
    ],
)
def test_verify_token_rejects_invalid_authorization(monkeypatch, authorization):
    monkeypatch.setattr(auth, "ACCESS_PASSWORD", "secret")

    with pytest.raises(HTTPException) as exc_info:
        auth.verify_token(authorization)

    assert exc_info.value.status_code == 401


def test_verify_token_allows_requests_when_password_is_empty(monkeypatch):
    monkeypatch.setattr(auth, "ACCESS_PASSWORD", "")

    assert auth.verify_token(None) is True
