# Listing Available Ollama Models

## Overview

The `list_ollama_models()` function retrieves a list of available models from your Ollama server. This is useful for:

- Discovering which models are installed
- Validating model availability before use
- Building UI dropdowns for model selection
- Checking if Ollama server is accessible

## Usage

### Basic Usage

```python
from llm_trading_system.infra.llm_infra import list_ollama_models

# List models from default Ollama server
models = list_ollama_models("http://localhost:11434")

print(f"Found {len(models)} models:")
for model in models:
    print(f"  - {model}")
```

### With AppConfig Integration

```python
from llm_trading_system.config import load_config
from llm_trading_system.infra.llm_infra import list_ollama_models

# Load config to get Ollama URL
cfg = load_config()

# Fetch models from configured server
models = list_ollama_models(cfg.llm.ollama_base_url)

if models:
    print(f"Available models: {', '.join(models)}")
else:
    print("No models found or server is unreachable")
```

### Error Handling

The function handles all errors gracefully and returns an empty list on failure:

```python
models = list_ollama_models("http://invalid-server:11434")
# Returns: []
# Logs: WARNING - Connection error while connecting to Ollama API...
```

## Function Signature

```python
def list_ollama_models(base_url: str) -> list[str]:
    """Retrieve list of available models from Ollama server.

    Args:
        base_url: Base URL for Ollama API (e.g., "http://localhost:11434")

    Returns:
        List of model names available on the server.
        Returns empty list if request fails or server is unreachable.
    """
```

## API Endpoint

The function calls the Ollama Tags API:

```
GET {base_url}/api/tags
```

Expected response format:

```json
{
  "models": [
    {
      "name": "llama3.2",
      "size": 1234567890,
      "modified_at": "2025-01-15T10:30:00Z"
    },
    {
      "name": "deepseek-v3.1:671b-cloud",
      "size": 2345678901,
      "modified_at": "2025-01-14T15:20:00Z"
    }
  ]
}
```

## Error Handling

The function handles these error cases:

| Error Type | Behavior | Log Level |
|------------|----------|-----------|
| Connection Error | Returns `[]` | WARNING |
| Timeout | Returns `[]` | WARNING |
| HTTP Error (4xx, 5xx) | Returns `[]` | WARNING |
| Invalid JSON | Returns `[]` | WARNING |
| Missing 'models' key | Returns `[]` | WARNING |
| Malformed entries | Skips invalid, returns valid | INFO |

## Example Script

Run the example script to see available models:

```bash
python examples/list_ollama_models.py
```

Output:

```
================================================================================
Ollama Models List
================================================================================

Fetching models from: http://localhost:11434

✓ Found 3 model(s):

  1. llama3.2
  2. deepseek-v3.1:671b-cloud
  3. mistral:latest

================================================================================

To use a model in your config:

  1. Edit ~/.llm_trading/config.json
  2. Set "default_model" to one of the models above

Example:
  "llm": {
    "llm_provider": "ollama",
    "default_model": "llama3.2",
    ...
  }
```

## Testing

Run the test suite:

```bash
python -m pytest tests/test_ollama_models_list.py -v
```

All 11 tests cover:
- ✓ Success cases with valid responses
- ✓ Error handling (timeout, connection, HTTP errors)
- ✓ Invalid JSON responses
- ✓ Malformed data structures
- ✓ Edge cases (empty lists, missing keys)

## Future UI Integration

This function is designed to support future UI features:

```javascript
// Future: Fetch models via API endpoint
fetch('/api/llm/models')
  .then(res => res.json())
  .then(models => {
    // Populate dropdown
    models.forEach(model => {
      const option = document.createElement('option');
      option.value = model;
      option.text = model;
      modelSelect.appendChild(option);
    });
  });
```

Backend API endpoint (future):

```python
@app.get("/api/llm/models")
async def get_llm_models():
    """Get available LLM models."""
    cfg = load_config()
    models = list_ollama_models(cfg.llm.ollama_base_url)
    return {"models": models}
```
