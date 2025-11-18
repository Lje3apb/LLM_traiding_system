"""Tests for list_ollama_models function."""

import pytest
import requests
from unittest.mock import Mock, patch

from llm_trading_system.infra.llm_infra.providers_ollama import list_ollama_models


class TestListOllamaModels:
    """Test suite for list_ollama_models function."""

    def test_list_models_success(self):
        """Test successful retrieval of models from Ollama API."""
        # Mock response with typical Ollama format
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": [
                {"name": "llama3.2", "size": 1000000},
                {"name": "deepseek-v3.1:671b-cloud", "size": 2000000},
                {"name": "mistral:latest", "size": 1500000},
            ]
        }

        with patch("requests.get", return_value=mock_response) as mock_get:
            result = list_ollama_models("http://localhost:11434")

            # Verify correct endpoint was called
            mock_get.assert_called_once_with(
                "http://localhost:11434/api/tags",
                timeout=10
            )

            # Verify returned model names
            assert result == [
                "llama3.2",
                "deepseek-v3.1:671b-cloud",
                "mistral:latest",
            ]

    def test_list_models_strips_trailing_slash(self):
        """Test that trailing slash in base_url is handled correctly."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": [{"name": "llama3.2"}]
        }

        with patch("requests.get", return_value=mock_response) as mock_get:
            result = list_ollama_models("http://localhost:11434/")

            # Should strip trailing slash
            mock_get.assert_called_once_with(
                "http://localhost:11434/api/tags",
                timeout=10
            )
            assert result == ["llama3.2"]

    def test_list_models_connection_error(self):
        """Test handling of connection errors."""
        with patch("requests.get", side_effect=requests.exceptions.ConnectionError()):
            result = list_ollama_models("http://localhost:11434")

            # Should return empty list on connection error
            assert result == []

    def test_list_models_timeout(self):
        """Test handling of timeout errors."""
        with patch("requests.get", side_effect=requests.exceptions.Timeout()):
            result = list_ollama_models("http://localhost:11434")

            # Should return empty list on timeout
            assert result == []

    def test_list_models_http_error(self):
        """Test handling of HTTP errors (4xx, 5xx)."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError()

        with patch("requests.get", return_value=mock_response):
            result = list_ollama_models("http://localhost:11434")

            # Should return empty list on HTTP error
            assert result == []

    def test_list_models_invalid_json(self):
        """Test handling of invalid JSON response."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")

        with patch("requests.get", return_value=mock_response):
            result = list_ollama_models("http://localhost:11434")

            # Should return empty list on invalid JSON
            assert result == []

    def test_list_models_missing_models_key(self):
        """Test handling of response missing 'models' key."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"error": "something went wrong"}

        with patch("requests.get", return_value=mock_response):
            result = list_ollama_models("http://localhost:11434")

            # Should return empty list when 'models' key is missing
            assert result == []

    def test_list_models_models_not_list(self):
        """Test handling of 'models' value that is not a list."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"models": "not a list"}

        with patch("requests.get", return_value=mock_response):
            result = list_ollama_models("http://localhost:11434")

            # Should return empty list when 'models' is not a list
            assert result == []

    def test_list_models_empty_list(self):
        """Test handling of empty models list."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"models": []}

        with patch("requests.get", return_value=mock_response):
            result = list_ollama_models("http://localhost:11434")

            # Should return empty list
            assert result == []

    def test_list_models_malformed_model_entries(self):
        """Test handling of malformed model entries in the list."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": [
                {"name": "llama3.2"},  # Valid
                {"size": 1000000},  # Missing 'name' key
                "invalid_entry",  # Not a dict
                {"name": "mistral:latest"},  # Valid
            ]
        }

        with patch("requests.get", return_value=mock_response):
            result = list_ollama_models("http://localhost:11434")

            # Should only include valid entries
            assert result == ["llama3.2", "mistral:latest"]

    def test_list_models_with_different_base_urls(self):
        """Test function works with different base URLs."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": [{"name": "test-model"}]
        }

        with patch("requests.get", return_value=mock_response) as mock_get:
            # Test with custom host
            result = list_ollama_models("http://192.168.1.100:11434")

            mock_get.assert_called_once_with(
                "http://192.168.1.100:11434/api/tags",
                timeout=10
            )
            assert result == ["test-model"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
