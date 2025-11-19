"""Tests for validation service functions."""

from pathlib import Path

import pytest

from llm_trading_system.api.services.validation import (
    sanitize_error_message,
    validate_data_path,
    validate_strategy_name,
)


class TestValidateDataPath:
    """Tests for validate_data_path function."""

    def test_valid_data_path(self, tmp_path):
        """Test that valid data paths are accepted."""
        # Create a test data directory
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        test_file = data_dir / "test.csv"
        test_file.write_text("test data")

        # This should work (file in data dir)
        result = validate_data_path(str(test_file))
        assert result == test_file.resolve()

    def test_path_traversal_blocked(self):
        """Test that path traversal attempts are blocked."""
        # Attempt path traversal
        with pytest.raises(ValueError, match="outside allowed directories"):
            validate_data_path("../etc/passwd")

        with pytest.raises(ValueError, match="outside allowed directories"):
            validate_data_path("../../secret.txt")

    def test_absolute_path_outside_data_blocked(self):
        """Test that absolute paths outside data/ are blocked."""
        with pytest.raises(ValueError, match="outside allowed directories"):
            validate_data_path("/etc/passwd")

        with pytest.raises(ValueError, match="outside allowed directories"):
            validate_data_path("/tmp/secret.txt")

    def test_invalid_path_raises_error(self):
        """Test that invalid path strings raise ValueError."""
        # Extremely long path that might cause OSError
        long_path = "a/" * 1000 + "test.csv"
        with pytest.raises(ValueError):
            validate_data_path(long_path)


class TestSanitizeErrorMessage:
    """Tests for sanitize_error_message function."""

    def test_removes_unix_paths(self):
        """Test that Unix file paths are removed."""
        error = Exception("/home/user/secret/file.txt not found")
        result = sanitize_error_message(error)
        assert "/home/user/secret/file.txt" not in result
        assert "[path]" in result

    def test_removes_windows_paths(self):
        """Test that Windows file paths are removed."""
        error = Exception("Cannot access C:\\Users\\Secret\\file.txt")
        result = sanitize_error_message(error)
        assert "C:\\Users\\Secret\\file.txt" not in result
        assert "[path]" in result

    def test_removes_passwords(self):
        """Test that passwords are redacted."""
        error = Exception("Auth failed: password=secretpass123")
        result = sanitize_error_message(error)
        assert "secretpass123" not in result
        assert "password=[REDACTED]" in result

    def test_removes_tokens(self):
        """Test that tokens are redacted."""
        error = Exception("Invalid token: token=abc123xyz")
        result = sanitize_error_message(error)
        assert "abc123xyz" not in result
        assert "token=[REDACTED]" in result

    def test_removes_keys(self):
        """Test that API keys are redacted."""
        error = Exception("API key invalid: key=sk-1234567890")
        result = sanitize_error_message(error)
        assert "sk-1234567890" not in result
        assert "key=[REDACTED]" in result

    def test_removes_secrets(self):
        """Test that secrets are redacted."""
        error = Exception("Secret mismatch: secret=mysecretvalue")
        result = sanitize_error_message(error)
        assert "mysecretvalue" not in result
        assert "secret=[REDACTED]" in result

    def test_preserves_safe_messages(self):
        """Test that safe error messages are preserved."""
        error = ValueError("Invalid input: expected number")
        result = sanitize_error_message(error)
        assert "Invalid input" in result

class TestValidateStrategyName:
    """Tests for validate_strategy_name function."""

    def test_valid_names_accepted(self):
        """Test that valid strategy names are accepted."""
        assert validate_strategy_name("momentum_strategy") == "momentum_strategy"
        assert validate_strategy_name("mean-reversion") == "mean-reversion"
        assert validate_strategy_name("strategy_v2.1") == "strategy_v2.1"
        assert validate_strategy_name("UPPER_CASE") == "UPPER_CASE"
        assert validate_strategy_name("mixed123") == "mixed123"

    def test_path_traversal_blocked(self):
        """Test that path traversal attempts are blocked."""
        with pytest.raises(ValueError, match="path traversal"):
            validate_strategy_name("../evil")

        with pytest.raises(ValueError, match="path traversal"):
            validate_strategy_name("strategy/../other")

    def test_absolute_paths_blocked(self):
        """Test that absolute paths are blocked."""
        with pytest.raises(ValueError, match="path traversal"):
            validate_strategy_name("/etc/passwd")

        with pytest.raises(ValueError, match="path traversal"):
            validate_strategy_name("\\windows\\system32")

    def test_invalid_characters_blocked(self):
        """Test that invalid characters are blocked."""
        with pytest.raises(ValueError, match="Invalid strategy name"):
            validate_strategy_name("strategy with spaces")

        with pytest.raises(ValueError, match="Invalid strategy name"):
            validate_strategy_name("strategy;injection")

        with pytest.raises(ValueError, match="Invalid strategy name"):
            validate_strategy_name("strategy<script>")

        with pytest.raises(ValueError, match="Invalid strategy name"):
            validate_strategy_name("strategy&command")

        with pytest.raises(ValueError, match="Invalid strategy name"):
            validate_strategy_name("strategy|pipe")
