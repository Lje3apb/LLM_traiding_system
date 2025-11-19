"""Project-wide site customization hooks.

We need FastAPI's TestClient (which depends on httpx) to work even when httpx
cannot be installed in the execution environment.  When Python starts it will
try to import this ``sitecustomize`` module; if the real dependency is missing we
register a lightweight stub that implements the minimal API surface area the
tests rely on.  When httpx is available nothing special happens and the stub is
ignored.
"""

from __future__ import annotations

import importlib
import sys


def _install_httpx_stub() -> None:
    """Register the lightweight httpx shim if the dependency is missing."""

    from llm_trading_system._compat import httpx_stub

    sys.modules.setdefault("httpx", httpx_stub)
    for name, module in httpx_stub.modules.items():
        sys.modules.setdefault(name, module)


try:  # pragma: no cover - exercised implicitly when dependency is present
    importlib.import_module("httpx")
except ModuleNotFoundError:  # pragma: no cover - only triggered in offline envs
    _install_httpx_stub()

