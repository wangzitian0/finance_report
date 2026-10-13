"""Tests for production smoke authentication verification probe (AC-runtime.http-probes.1, #2370)."""

from __future__ import annotations

import io
import json
import urllib.error
from unittest.mock import patch

import pytest
from common.runtime.verify_prod_smoke_auth import build_parser, main, verify_auth


class DummyResponse:
    def __init__(self, status: int, data: dict | None = None) -> None:
        self.status = status
        self._raw = json.dumps(data or {}).encode("utf-8")

    def read(self) -> bytes:
        return self._raw

    def __enter__(self) -> DummyResponse:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        pass


def test_verify_auth_success() -> None:
    """Verify auth succeeds when login and me return 200 with access token."""
    login_data = {
        "access_token": "mock-token",
        "id": "mock-user-id",
        "email": "smoke@example.com",
    }
    me_data = {"email": "smoke@example.com"}

    def fake_urlopen(req, timeout=15.0):
        if req.full_url.endswith("/api/auth/login"):
            return DummyResponse(200, login_data)
        if req.full_url.endswith("/api/auth/me"):
            assert req.headers.get("Authorization") == "Bearer mock-token"
            return DummyResponse(200, me_data)
        raise ValueError(f"Unexpected url: {req.full_url}")

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        ok = verify_auth("https://report.zitian.party", "smoke@example.com", "secret")
        assert ok is True


def test_verify_auth_login_status_not_200() -> None:
    """Verify auth fails when login returns non-200 status."""
    with patch("urllib.request.urlopen", return_value=DummyResponse(500, {})):
        ok = verify_auth("https://report.zitian.party", "smoke@example.com", "secret")
        assert ok is False


def test_verify_auth_login_http_error() -> None:
    """Verify auth fails when login raises HTTPError."""
    fp = io.BytesIO(b'{"detail":"Invalid credentials"}')
    exc = urllib.error.HTTPError(
        "https://report.zitian.party/api/auth/login", 401, "Unauthorized", {}, fp
    )
    with patch("urllib.request.urlopen", side_effect=exc):
        ok = verify_auth("https://report.zitian.party", "smoke@example.com", "badpass")
        assert ok is False


def test_verify_auth_login_network_error() -> None:
    """Verify auth fails when connection fails."""
    with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
        ok = verify_auth("https://report.zitian.party", "smoke@example.com", "secret")
        assert ok is False


def test_verify_auth_missing_token() -> None:
    """Verify auth fails when login response lacks access_token."""
    with patch(
        "urllib.request.urlopen",
        return_value=DummyResponse(200, {"id": "1", "email": "a@b.com"}),
    ):
        ok = verify_auth("https://report.zitian.party", "smoke@example.com", "secret")
        assert ok is False


def test_verify_auth_me_fails_status() -> None:
    """Verify auth fails when /api/auth/me returns non-200 status."""
    login_data = {"access_token": "token", "id": "1", "email": "a@b.com"}

    def fake_urlopen(req, timeout=15.0):
        if req.full_url.endswith("/api/auth/login"):
            return DummyResponse(200, login_data)
        return DummyResponse(403, {})

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        ok = verify_auth("https://report.zitian.party", "smoke@example.com", "secret")
        assert ok is False


def test_verify_auth_me_exception() -> None:
    """Verify auth fails when /api/auth/me throws exception."""
    login_data = {"access_token": "token", "id": "1", "email": "a@b.com"}

    def fake_urlopen(req, timeout=15.0):
        if req.full_url.endswith("/api/auth/login"):
            return DummyResponse(200, login_data)
        raise OSError("me timeout")

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        ok = verify_auth("https://report.zitian.party", "smoke@example.com", "secret")
        assert ok is False


def test_build_parser_options() -> None:
    """Verify parser defaults and arguments."""
    parser = build_parser()
    args = parser.parse_args(["--email", "test@test.com", "--password", "pwd"])
    assert args.email == "test@test.com"
    assert args.password == "pwd"
    assert args.url == "https://report.zitian.party"
    assert args.timeout == 15.0


def test_main_missing_credentials(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify main returns 2 when credentials are missing."""
    with patch.dict("os.environ", {}, clear=True):
        code = main([])
        assert code == 2
        captured = capsys.readouterr()
        assert "Smoke credentials missing" in captured.err


def test_main_success() -> None:
    """Verify main returns 0 on success."""
    with patch("common.runtime.verify_prod_smoke_auth.verify_auth", return_value=True):
        code = main(["--email", "a@b.com", "--password", "pwd"])
        assert code == 0


def test_main_failure() -> None:
    """Verify main returns 1 on auth failure."""
    with patch("common.runtime.verify_prod_smoke_auth.verify_auth", return_value=False):
        code = main(["--email", "a@b.com", "--password", "pwd"])
        assert code == 1
