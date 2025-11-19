"""Pytest configuration shared across the suite."""

from __future__ import annotations

import importlib
import sys

import pytest
from fastapi import Request


def _ensure_httpx_available() -> None:
    """Inject the lightweight httpx stub when the dependency is missing."""

    try:
        importlib.import_module("httpx")
        return
    except ModuleNotFoundError:
        pass

    from llm_trading_system._compat import httpx_stub

    sys.modules.setdefault("httpx", httpx_stub)
    for name, module in httpx_stub.modules.items():
        sys.modules.setdefault(name, module)


_ensure_httpx_available()


@pytest.fixture(scope="session", autouse=True)
def _disable_auth_dependencies() -> None:
    """Override auth dependencies so UI/API tests can run without logging in."""

    from llm_trading_system.api import auth
    from llm_trading_system.api.server import app, limiter

    test_user = auth.get_user("admin")
    assert test_user is not None, "seed admin user must exist for tests"

    def _fake_auth(request: Request) -> auth.User:  # pragma: no cover - helper
        request.session.setdefault("user_id", test_user.user_id)
        return test_user

    def _fake_optional(request: Request) -> auth.User:
        request.session.setdefault("user_id", test_user.user_id)
        return test_user

    app.dependency_overrides[auth.require_auth] = _fake_auth
    app.dependency_overrides[auth.require_admin] = _fake_auth
    app.dependency_overrides[auth.optional_auth] = _fake_optional

    limiter.enabled = False

    yield

    app.dependency_overrides.pop(auth.require_auth, None)
    app.dependency_overrides.pop(auth.require_admin, None)
    app.dependency_overrides.pop(auth.optional_auth, None)
    limiter.enabled = True

