"""Lightweight fallback implementation of the ``httpx`` API.

This module provides the minimum surface area required for ``starlette``'s
``TestClient`` to operate inside environments where the real ``httpx`` package
cannot be installed (for example, offline execution sandboxes).

It intentionally implements only the subset of functionality exercised by our
test-suite: synchronous requests routed through a custom transport, header and
cookie handling, and JSON/text helpers on the response object.  The goal is not
to be a drop-in replacement for production usage, but to keep local tests
running when the optional dependency is unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Iterable, Mapping, MutableMapping
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit
import types

__all__ = [
    "BaseTransport",
    "ByteStream",
    "Client",
    "Request",
    "Response",
]


# ---------------------------------------------------------------------------
# Minimal ``httpx._types`` compatibility layer
# ---------------------------------------------------------------------------

_types = types.ModuleType("httpx._types")
_types.URLTypes = Any
_types.RequestContent = Any
_types.RequestFiles = Any
_types.QueryParamTypes = Any
_types.HeaderTypes = Any
_types.CookieTypes = Any
_types.AuthTypes = Any
_types.TimeoutTypes = Any


# ---------------------------------------------------------------------------
# Minimal ``httpx._client`` compatibility layer
# ---------------------------------------------------------------------------

_client = types.ModuleType("httpx._client")


class UseClientDefault:
    """Sentinel that mirrors httpx's UseClientDefault type."""


_client.UseClientDefault = UseClientDefault
_client.USE_CLIENT_DEFAULT = UseClientDefault()


# ---------------------------------------------------------------------------
# Helper classes
# ---------------------------------------------------------------------------


class Headers:
    """Very small header container with case-insensitive lookups."""

    def __init__(self, initial: Mapping[str, str] | Iterable[tuple[str, str]] | None = None) -> None:
        self._items: list[tuple[str, str]] = []
        if initial:
            if isinstance(initial, Mapping):
                iterable: Iterable[tuple[str, str]] = initial.items()
            else:
                iterable = initial
            for key, value in iterable:
                self.add(key, value)

    def add(self, key: str, value: str) -> None:
        self._items.append((str(key), str(value)))

    def get(self, key: str, default: str | None = None) -> str | None:
        key_lower = key.lower()
        for existing, value in reversed(self._items):
            if existing.lower() == key_lower:
                return value
        return default

    def get_all(self, key: str) -> list[str]:
        key_lower = key.lower()
        return [value for existing, value in self._items if existing.lower() == key_lower]

    def multi_items(self) -> list[tuple[str, str]]:
        return list(self._items)

    def items(self) -> list[tuple[str, str]]:
        return list(self._items)

    def as_dict(self) -> dict[str, str]:
        data: dict[str, str] = {}
        for key, value in self._items:
            data[key] = value
        return data

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):  # pragma: no cover - defensive
            return False
        return self.get(key) is not None

    def __getitem__(self, key: str) -> str:
        value = self.get(key)
        if value is None:
            raise KeyError(key)
        return value


class URL:
    """Simplified URL container that mimics the attributes used by Starlette."""

    def __init__(self, value: str) -> None:
        if isinstance(value, bytes):
            value = value.decode("ascii")
        if not value:
            value = "/"
        self._split = urlsplit(value)

    def __str__(self) -> str:  # pragma: no cover - debugging helper
        return urlunsplit(self._split)

    def replace(self, **parts: str) -> URL:
        split = list(self._split)
        indices = {"scheme": 0, "netloc": 1, "path": 2, "query": 3, "fragment": 4}
        for key, idx in indices.items():
            if key in parts:
                split[idx] = parts[key]
        return URL(urlunsplit(split))

    @property
    def scheme(self) -> str:
        return self._split.scheme or "http"

    @property
    def netloc(self) -> bytes:
        return (self._split.netloc or "").encode("ascii")

    @property
    def path(self) -> str:
        return self._split.path or "/"

    @property
    def raw_path(self) -> bytes:
        return self.path.encode("ascii")

    @property
    def query(self) -> bytes:
        return (self._split.query or "").encode("ascii")


@dataclass
class Request:
    """Simplified HTTP request object passed to transports."""

    method: str
    url: URL
    headers: Headers
    content: bytes

    def read(self) -> bytes:
        return self.content


class ByteStream:
    """Stream wrapper used by Starlette's TestClient."""

    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class Response:
    """Simplified HTTP response compatible with the tests."""

    def __init__(
        self,
        status_code: int,
        *,
        headers: Iterable[tuple[str, str]] | Mapping[str, str] | None = None,
        stream: ByteStream | bytes | None = None,
        request: Request | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = Headers(headers)
        if isinstance(stream, ByteStream):
            self._content = stream.read()
        elif hasattr(stream, "read"):
            self._content = stream.read()
        else:
            self._content = stream or b""
        self.request = request

    @property
    def content(self) -> bytes:
        return self._content

    @property
    def text(self) -> str:
        try:
            return self._content.decode("utf-8")
        except UnicodeDecodeError:
            return self._content.decode("latin-1", errors="replace")

    def json(self) -> Any:
        if not self._content:
            return None
        return json.loads(self.text)


class BaseTransport:
    """Base transport class.  Custom transports should override ``handle_request``."""

    def handle_request(self, request: Request) -> Response:  # pragma: no cover - interface only
        raise NotImplementedError


class _CookieJar:
    def __init__(self, initial: Mapping[str, str] | Iterable[tuple[str, str]] | None = None) -> None:
        self._cookies: dict[str, str] = {}
        if initial:
            self.update(initial)

    def update(self, cookies: Mapping[str, str] | Iterable[tuple[str, str]]) -> None:
        if isinstance(cookies, Mapping):
            iterable: Iterable[tuple[str, str]] = cookies.items()
        else:
            iterable = cookies
        for name, value in iterable:
            if value is None:
                continue
            self._cookies[str(name)] = str(value)

    def extract_from_headers(self, headers: Headers) -> None:
        for key, value in headers.multi_items():
            if key.lower() == "set-cookie":
                parts = value.split(";", 1)[0]
                if "=" in parts:
                    name, cookie_value = parts.split("=", 1)
                else:
                    name, cookie_value = parts, ""
                self._cookies[name.strip()] = cookie_value.strip()

    def build_header(self, extra: Mapping[str, str] | None = None) -> str:
        cookie_map = dict(self._cookies)
        if extra:
            for key, value in extra.items():
                if value is not None:
                    cookie_map[str(key)] = str(value)
        if not cookie_map:
            return ""
        return "; ".join(f"{key}={value}" for key, value in cookie_map.items())


class Client:
    """Extremely small subset of the ``httpx.Client`` API used in tests."""

    def __init__(
        self,
        *,
        base_url: str = "",
        headers: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | Iterable[tuple[str, str]] | None = None,
        transport: BaseTransport | None = None,
        follow_redirects: bool = True,
    ) -> None:
        if transport is None:
            raise RuntimeError("A transport implementation is required for the httpx stub client")
        self.base_url = base_url
        self._transport = transport
        self._default_headers = Headers(headers)
        self._cookie_jar = _CookieJar(cookies)
        self.follow_redirects = follow_redirects

    # ------------------------------------------------------------------
    # Context manager helpers
    # ------------------------------------------------------------------

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def close(self) -> None:  # pragma: no cover - nothing to clean up
        pass

    # ------------------------------------------------------------------
    # Request helpers
    # ------------------------------------------------------------------

    def _merge_url(self, url: Any) -> URL:
        if isinstance(url, URL):
            return url
        if isinstance(url, bytes):
            url = url.decode("ascii")
        if not url:
            url = "/"
        if "//" in url:
            full_url = url
        else:
            base = self.base_url or "http://testserver"
            if not base.endswith("/") and not url.startswith("/"):
                base = base + "/"
            full_url = urljoin(base, url)
        return URL(full_url)

    def build_request(
        self,
        method: str,
        url: Any,
        *,
        params: Mapping[str, Any] | Iterable[tuple[str, Any]] | None = None,
        headers: Mapping[str, str] | None = None,
        content: Any = None,
        data: Mapping[str, Any] | Iterable[tuple[str, Any]] | None = None,
        json_data: Any = None,
    ) -> Request:
        url_obj = self._merge_url(url)
        if params:
            if isinstance(params, Mapping):
                iterable: Iterable[tuple[str, Any]] = params.items()
            else:
                iterable = params
            query = urlencode(list(iterable), doseq=True)
            url_obj = url_obj.replace(query=query)

        body: bytes
        final_headers = Headers(self._default_headers.items())
        if headers:
            for key, value in headers.items():
                final_headers.add(key, value)

        content_type_set = final_headers.get("content-type") is not None

        if json_data is not None:
            body = json.dumps(json_data).encode("utf-8")
            if not content_type_set:
                final_headers.add("content-type", "application/json")
        elif data is not None:
            if isinstance(data, Mapping):
                iterable = data.items()
            else:
                iterable = data
            body = urlencode(list(iterable)).encode("utf-8")
            if not content_type_set:
                final_headers.add("content-type", "application/x-www-form-urlencoded")
        elif content is not None:
            if isinstance(content, str):
                body = content.encode("utf-8")
            else:
                body = bytes(content)
        else:
            body = b""

        return Request(method=method.upper(), url=url_obj, headers=final_headers, content=body)

    def _prepare_cookie_header(
        self, cookies: Mapping[str, str] | Iterable[tuple[str, str]] | None
    ) -> str:
        extra: dict[str, str] | None = None
        if cookies:
            if isinstance(cookies, Mapping):
                extra = {str(k): str(v) for k, v in cookies.items() if v is not None}
            else:
                extra = {str(k): str(v) for k, v in cookies}
        return self._cookie_jar.build_header(extra)

    def request(
        self,
        method: str,
        url: Any,
        *,
        content: Any = None,
        data: Mapping[str, Any] | Iterable[tuple[str, Any]] | None = None,
        files: Any = None,  # pragma: no cover - unsupported
        json: Any = None,
        params: Mapping[str, Any] | Iterable[tuple[str, Any]] | None = None,
        headers: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | Iterable[tuple[str, str]] | None = None,
        auth: Any = None,  # pragma: no cover - unsupported
        follow_redirects: bool | None = None,
        timeout: Any = None,  # pragma: no cover - unsupported
        extensions: dict[str, Any] | None = None,  # pragma: no cover - unsupported
    ) -> Response:
        request = self.build_request(
            method,
            url,
            params=params,
            headers=headers,
            content=content,
            data=data,
            json_data=json,
        )

        cookie_header = self._prepare_cookie_header(cookies)
        if cookie_header:
            request.headers.add("cookie", cookie_header)

        response = self._transport.handle_request(request)
        self._cookie_jar.extract_from_headers(response.headers)
        return response

    # Convenience wrappers -------------------------------------------------

    def get(self, url: Any, **kwargs: Any) -> Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: Any, **kwargs: Any) -> Response:
        return self.request("POST", url, **kwargs)

    def put(self, url: Any, **kwargs: Any) -> Response:
        return self.request("PUT", url, **kwargs)

    def delete(self, url: Any, **kwargs: Any) -> Response:
        return self.request("DELETE", url, **kwargs)

    def head(self, url: Any, **kwargs: Any) -> Response:
        return self.request("HEAD", url, **kwargs)

    def options(self, url: Any, **kwargs: Any) -> Response:
        return self.request("OPTIONS", url, **kwargs)

    def patch(self, url: Any, **kwargs: Any) -> Response:
        return self.request("PATCH", url, **kwargs)


# Re-export modules so ``sitecustomize`` can register them when needed.
modules: dict[str, types.ModuleType] = {
    "httpx._types": _types,
    "httpx._client": _client,
}

