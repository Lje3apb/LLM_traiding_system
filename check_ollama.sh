#!/bin/bash
# Quick Ollama status checker

echo "=========================================="
echo "Ollama Status Checker"
echo "=========================================="
echo

# Check if ollama is installed
echo "[1/4] Checking if Ollama is installed..."
if command -v ollama &> /dev/null; then
    VERSION=$(ollama --version 2>&1)
    echo "✓ Ollama is installed: $VERSION"
else
    echo "✗ Ollama is NOT installed"
    echo "  Install with: curl -fsSL https://ollama.com/install.sh | sh"
    exit 1
fi
echo

# Check if ollama service is running
echo "[2/4] Checking if Ollama service is running..."
if pgrep -x "ollama" > /dev/null; then
    echo "✓ Ollama service is running (PID: $(pgrep -x ollama))"
elif curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "✓ Ollama API is responding on localhost:11434"
else
    echo "✗ Ollama service is NOT running"
    echo "  Start with: ollama serve"
    echo "  Or in background: nohup ollama serve > ollama.log 2>&1 &"
    exit 1
fi
echo

# Check available models
echo "[3/4] Checking available models..."
MODELS=$(ollama list 2>/dev/null)
if [ $? -eq 0 ]; then
    echo "$MODELS"
    MODEL_COUNT=$(echo "$MODELS" | tail -n +2 | wc -l)
    if [ $MODEL_COUNT -eq 0 ]; then
        echo "⚠ No models installed"
        echo "  Pull a model with: ollama pull gpt-oss:20b"
    else
        echo "✓ Found $MODEL_COUNT model(s)"
    fi
else
    echo "✗ Could not list models"
    exit 1
fi
echo

# Test API
echo "[4/4] Testing Ollama API..."
API_RESPONSE=$(curl -s http://localhost:11434/api/tags)
if [ $? -eq 0 ]; then
    echo "✓ API is responding"
    echo "  Endpoint: http://localhost:11434"
else
    echo "✗ API is not responding"
    exit 1
fi
echo

echo "=========================================="
echo "✓ Ollama is ready to use!"
echo "=========================================="
echo
echo "Next steps:"
echo "  1. Make sure you have a model: ollama pull gpt-oss:20b"
echo "  2. Run the test script: python3 test_ollama.py"
echo
