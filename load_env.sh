#!/bin/bash
# Load environment variables from .env.example file
# Usage: source load_env.sh

ENV_FILE="${1:-.env.example}"

if [ ! -f "$ENV_FILE" ]; then
    echo "Error: $ENV_FILE not found"
    return 1 2>/dev/null || exit 1
fi

echo "Loading environment variables from $ENV_FILE..."

# Read file and export variables
while IFS='=' read -r key value; do
    # Skip comments and empty lines
    [[ $key =~ ^#.*$ ]] && continue
    [[ -z $key ]] && continue

    # Remove leading/trailing whitespace
    key=$(echo "$key" | xargs)
    value=$(echo "$value" | xargs)

    # Export variable
    if [ -n "$key" ] && [ -n "$value" ]; then
        export "$key=$value"
        echo "  ✓ $key"
    fi
done < "$ENV_FILE"

echo ""
echo "Environment variables loaded!"
echo ""
echo "Verify with: python3 check_env.py"
echo "Run test with: python3 test_full_cycle.py --real-data"
