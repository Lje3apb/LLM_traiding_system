"""Setup configuration for LLM Trading System package."""

from setuptools import setup, find_packages
from pathlib import Path

# Read README for long description
readme_file = Path(__file__).parent / "README.md"
long_description = readme_file.read_text(encoding="utf-8") if readme_file.exists() else ""

setup(
    name="llm-trading-system",
    version="0.1.0",
    author="LLM Trading System Contributors",
    description="A regime-based trading system using LLM analysis",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/Lje3apb/LLM_traiding_system",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    python_requires=">=3.12",
    install_requires=[
        "requests>=2.32.3",
    ],
    extras_require={
        "dev": [
            "pytest>=8.3.3",
            "pytest-cov>=5.0.0",
            "mypy>=1.11.2",
            "black>=24.8.0",
            "ruff>=0.6.9",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Topic :: Office/Business :: Financial :: Investment",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.12",
    ],
    entry_points={
        "console_scripts": [
            "llm-trading-cli=llm_trading_system.cli.full_cycle_cli:main",
            "llm-trading-check-deps=llm_trading_system.cli.check_dependencies:main",
            "llm-trading-test-ollama=llm_trading_system.cli.quick_test_ollama:main",
        ],
    },
)
