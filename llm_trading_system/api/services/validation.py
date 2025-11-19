"""Validation and security helper functions."""

from __future__ import annotations

from pathlib import Path


def validate_data_path(path_str: str) -> Path:
    """Validate and resolve data path to prevent path traversal attacks.

    This function ensures that user-provided file paths cannot escape
    the allowed directories, preventing path traversal attacks.

    Args:
        path_str: User-provided path string

    Returns:
        Resolved absolute Path object within allowed directories

    Raises:
        ValueError: If path contains traversal attempts or is outside allowed directories

    Example:
        >>> path = validate_data_path("data/BTCUSDT.csv")
        >>> path = validate_data_path("../etc/passwd")  # Raises ValueError
    """
    # Define allowed base directories
    # Use Path(__file__) to find project root (3 levels up from this file)
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    allowed_dirs = [
        project_root / "data",
        project_root / "temp",
        Path.cwd() / "data",
    ]

    # Resolve the path (converts relative to absolute, follows symlinks)
    try:
        user_path = Path(path_str).resolve()
    except (ValueError, OSError) as e:
        raise ValueError(f"Invalid path: {e}")

    # Check if path is within any allowed directory
    for allowed_dir in allowed_dirs:
        try:
            allowed_dir_resolved = allowed_dir.resolve()
            # Check if user_path is relative to allowed_dir
            # This will raise ValueError if user_path is not a subpath
            user_path.relative_to(allowed_dir_resolved)
            # Path is safe, return it
            return user_path
        except (ValueError, OSError):
            # Not relative to this allowed_dir, try next
            continue

    # If we get here, path is not in any allowed directory
    raise ValueError(
        f"Path '{path_str}' is outside allowed directories. "
        f"Data files must be in 'data/' or 'temp/' directories."
    )


def sanitize_error_message(e: Exception) -> str:
    """Sanitize exception message to avoid leaking sensitive information.

    Removes file paths, passwords, and other sensitive data from error messages
    before sending them to the client.

    Args:
        e: The exception to sanitize

    Returns:
        Sanitized error message safe for client display

    Example:
        >>> try:
        ...     open("/secret/path/file.txt")
        ... except Exception as e:
        ...     msg = sanitize_error_message(e)
        ...     # msg won't contain "/secret/path"
    """
    msg = str(e)

    # Remove absolute paths (Unix and Windows)
    import re
    # Match Unix paths: /path/to/file
    msg = re.sub(r'/[\w/.-]+', '[path]', msg)
    # Match Windows paths: C:\path\to\file
    msg = re.sub(r'[A-Z]:\\[\w\\.-]+', '[path]', msg)

    # Remove common sensitive patterns
    msg = re.sub(r'password[=:]\s*\S+', 'password=[REDACTED]', msg, flags=re.IGNORECASE)
    msg = re.sub(r'token[=:]\s*\S+', 'token=[REDACTED]', msg, flags=re.IGNORECASE)
    msg = re.sub(r'key[=:]\s*\S+', 'key=[REDACTED]', msg, flags=re.IGNORECASE)
    msg = re.sub(r'secret[=:]\s*\S+', 'secret=[REDACTED]', msg, flags=re.IGNORECASE)

    return msg


def validate_strategy_name(name: str) -> str:
    """Validate strategy name to prevent injection attacks.

    Args:
        name: Strategy name to validate

    Returns:
        Validated strategy name

    Raises:
        ValueError: If name contains invalid characters

    Example:
        >>> validate_strategy_name("my_strategy")
        'my_strategy'
        >>> validate_strategy_name("../evil")  # Raises ValueError
    """
    # Allow alphanumeric, underscore, hyphen, dot
    import re
    if not re.match(r'^[a-zA-Z0-9_.-]+$', name):
        raise ValueError(
            "Invalid strategy name. Only alphanumeric characters, "
            "underscores, hyphens, and dots are allowed."
        )

    # Prevent path traversal
    if '..' in name or name.startswith('/') or name.startswith('\\'):
        raise ValueError("Strategy name cannot contain path traversal sequences")

    return name
