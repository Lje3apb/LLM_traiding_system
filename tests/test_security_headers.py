"""Integration tests for HTTP security headers and CORS configuration."""

import pytest
from fastapi.testclient import TestClient

from llm_trading_system.api.server import app


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


def test_x_frame_options_header(client):
    """Test that X-Frame-Options header is set to DENY."""
    response = client.get("/health")

    assert "X-Frame-Options" in response.headers
    assert response.headers["X-Frame-Options"] == "DENY"


def test_x_content_type_options_header(client):
    """Test that X-Content-Type-Options header is set to nosniff."""
    response = client.get("/health")

    assert "X-Content-Type-Options" in response.headers
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_referrer_policy_header(client):
    """Test that Referrer-Policy header is set to same-origin."""
    response = client.get("/health")

    assert "Referrer-Policy" in response.headers
    assert response.headers["Referrer-Policy"] == "same-origin"


def test_x_xss_protection_header(client):
    """Test that X-XSS-Protection header is set."""
    response = client.get("/health")

    assert "X-XSS-Protection" in response.headers
    assert response.headers["X-XSS-Protection"] == "1; mode=block"


def test_content_security_policy_header(client):
    """Test that Content-Security-Policy header is set."""
    response = client.get("/health")

    assert "Content-Security-Policy" in response.headers
    csp = response.headers["Content-Security-Policy"]

    # Check key CSP directives
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "script-src" in csp
    assert "style-src" in csp


def test_hsts_header_not_set_in_development(client):
    """Test that HSTS header is NOT set in development (ENV != production)."""
    response = client.get("/health")

    # In development, HSTS should not be set
    # (This test assumes ENV is not set to "production")
    assert "Strict-Transport-Security" not in response.headers


def test_security_headers_on_all_endpoints(client):
    """Test that security headers are set on all endpoints."""
    endpoints = [
        "/health",
        "/",  # Root redirect
    ]

    for endpoint in endpoints:
        response = client.get(endpoint, follow_redirects=False)

        # All responses should have security headers
        assert "X-Frame-Options" in response.headers, f"Missing X-Frame-Options on {endpoint}"
        assert "X-Content-Type-Options" in response.headers, f"Missing X-Content-Type-Options on {endpoint}"
        assert "Referrer-Policy" in response.headers, f"Missing Referrer-Policy on {endpoint}"


def test_security_headers_on_ui_pages(client):
    """Test that security headers are set on UI pages."""
    response = client.get("/ui/login")

    assert response.status_code == 200
    assert "X-Frame-Options" in response.headers
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "X-Content-Type-Options" in response.headers
    assert "Referrer-Policy" in response.headers
    assert "Content-Security-Policy" in response.headers


def test_security_headers_on_api_endpoints(client):
    """Test that security headers are set on API endpoints."""
    response = client.get("/strategies")

    assert "X-Frame-Options" in response.headers
    assert "X-Content-Type-Options" in response.headers
    assert "Referrer-Policy" in response.headers


def test_cors_configuration_default(client):
    """Test that CORS is configured with default settings (no allowed origins)."""
    # Make a request with an Origin header
    response = client.get(
        "/health",
        headers={"Origin": "http://example.com"}
    )

    # With empty allow_origins, CORS headers should not be present
    # (or Access-Control-Allow-Origin should not include the requesting origin)
    # FastAPI's CORSMiddleware doesn't add headers when origin not allowed
    assert "Access-Control-Allow-Origin" not in response.headers or \
           response.headers.get("Access-Control-Allow-Origin") != "http://example.com"


def test_cors_preflight_request(client):
    """Test CORS preflight OPTIONS request."""
    # Preflight request
    response = client.options(
        "/health",
        headers={
            "Origin": "http://example.com",
            "Access-Control-Request-Method": "GET",
        }
    )

    # Preflight should be handled (200 or 204)
    # But origin should not be allowed (empty allow_origins)
    assert response.status_code in (200, 204, 403, 400)


def test_clickjacking_protection(client):
    """Test that clickjacking protection is in place."""
    response = client.get("/ui/login")

    # X-Frame-Options: DENY prevents page from being loaded in iframe
    assert response.headers["X-Frame-Options"] == "DENY"

    # CSP frame-ancestors 'none' also prevents framing
    csp = response.headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in csp


def test_mime_sniffing_protection(client):
    """Test that MIME sniffing protection is in place."""
    response = client.get("/health")

    # X-Content-Type-Options: nosniff prevents MIME sniffing
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_referrer_information_leakage_protection(client):
    """Test that referrer information leakage is prevented."""
    response = client.get("/health")

    # Referrer-Policy: same-origin prevents leaking referrer to external sites
    assert response.headers["Referrer-Policy"] == "same-origin"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
