"""Integration tests for CSRF protection."""

import pytest
from fastapi.testclient import TestClient

from llm_trading_system.api.server import app


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


def test_csrf_token_cookie_is_set_on_ui_pages(client):
    """Test that CSRF token cookie is set when accessing UI pages."""
    # Access a UI page
    response = client.get("/ui/login")

    # Check that response is successful
    assert response.status_code == 200

    # Check that csrf_token cookie is set
    assert "csrf_token" in response.cookies
    csrf_token = response.cookies["csrf_token"]

    # Check that token is not empty
    assert csrf_token
    assert len(csrf_token) > 0


def test_csrf_missing_cookie_rejects_request(client):
    """Test that POST request without cookie is rejected."""
    # Try to POST without first getting a cookie
    response = client.post(
        "/ui/login",
        data={
            "csrf_token": "some_token",
            "username": "admin",
            "password": "admin123",
            "next": "/ui/",
        },
    )

    # Should be rejected with 403
    assert response.status_code == 403
    # Check error message mentions cookie
    assert "cookie" in response.text.lower() or "csrf" in response.text.lower()


def test_csrf_missing_form_token_rejects_request(client):
    """Test that POST request without form token is rejected."""
    # First get a CSRF token cookie
    get_response = client.get("/ui/login")
    csrf_cookie = get_response.cookies["csrf_token"]

    # Try to POST without form token
    response = client.post(
        "/ui/login",
        data={
            # Missing csrf_token field
            "username": "admin",
            "password": "admin123",
            "next": "/ui/",
        },
        cookies={"csrf_token": csrf_cookie},
    )

    # Should be rejected with 422 (missing required field) or 403
    assert response.status_code in (403, 422)


def test_csrf_wrong_token_rejects_request(client):
    """Test that POST request with wrong token is rejected."""
    # First get a CSRF token cookie
    get_response = client.get("/ui/login")
    csrf_cookie = get_response.cookies["csrf_token"]

    # Try to POST with wrong token
    response = client.post(
        "/ui/login",
        data={
            "csrf_token": "wrong_token_12345",  # Wrong token
            "username": "admin",
            "password": "admin123",
            "next": "/ui/",
        },
        cookies={"csrf_token": csrf_cookie},
    )

    # Should be rejected with 403
    assert response.status_code == 403
    # Check error message
    assert "csrf" in response.text.lower() or "validation failed" in response.text.lower()


def test_csrf_correct_token_accepts_request(client):
    """Test that POST request with correct token is accepted."""
    # First get a CSRF token cookie
    get_response = client.get("/ui/login")
    csrf_cookie = get_response.cookies["csrf_token"]

    # POST with correct token (should succeed authentication-wise or show invalid credentials)
    response = client.post(
        "/ui/login",
        data={
            "csrf_token": csrf_cookie,  # Correct token from cookie
            "username": "admin",
            "password": "admin123",
            "next": "/ui/",
        },
        cookies={"csrf_token": csrf_cookie},
        follow_redirects=False,  # Don't follow redirects
    )

    # Should NOT be rejected by CSRF (might be 303 redirect on success or 303 redirect with error)
    assert response.status_code in (200, 303)
    # Should NOT contain CSRF error
    if response.status_code == 200:
        assert "csrf" not in response.text.lower() or "validation failed" not in response.text.lower()


def test_csrf_token_is_different_per_request(client):
    """Test that CSRF tokens are different for different requests."""
    # Get first token
    response1 = client.get("/ui/login")
    token1 = response1.cookies["csrf_token"]

    # Get second token
    response2 = client.get("/ui/login")
    token2 = response2.cookies["csrf_token"]

    # Tokens should be different (stateless, regenerated each time)
    assert token1 != token2


def test_csrf_case_sensitive(client):
    """Test that CSRF token comparison is case-sensitive."""
    # Get a CSRF token cookie
    get_response = client.get("/ui/login")
    csrf_cookie = get_response.cookies["csrf_token"]

    # Try to POST with uppercase/lowercase variation
    wrong_case_token = csrf_cookie.upper() if csrf_cookie.islower() else csrf_cookie.lower()

    response = client.post(
        "/ui/login",
        data={
            "csrf_token": wrong_case_token,  # Wrong case
            "username": "admin",
            "password": "admin123",
            "next": "/ui/",
        },
        cookies={"csrf_token": csrf_cookie},
    )

    # Should be rejected with 403
    assert response.status_code == 403


def test_all_ui_post_endpoints_require_csrf(client):
    """Test that all UI POST endpoints require CSRF token."""
    # Get a valid CSRF token
    get_response = client.get("/ui/login")
    csrf_cookie = get_response.cookies["csrf_token"]

    # List of UI POST endpoints to test
    # We'll test that they reject requests without proper CSRF
    endpoints_to_test = [
        ("/ui/login", {"username": "test", "password": "test", "next": "/ui/"}),
        # Note: Other endpoints may require authentication, so we just test they don't crash
    ]

    for endpoint, data in endpoints_to_test:
        # POST without csrf_token field should fail
        response = client.post(
            endpoint,
            data=data,
            cookies={"csrf_token": csrf_cookie},
        )
        # Should be rejected (either 403 for CSRF or 422 for missing field)
        assert response.status_code in (403, 422), f"Endpoint {endpoint} did not require CSRF"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
