"""FastAPI server for the LLM Trading System."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from llm_trading_system.engine.backtest_service import run_backtest_from_config_dict
from llm_trading_system.strategies import storage

# Create FastAPI app
app = FastAPI(
    title="LLM Trading System API",
    version="0.1.0",
    description="HTTP JSON API for backtesting and strategy management",
)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint.

    Returns:
        Status dictionary
    """
    return {"status": "ok"}


@app.get("/strategies")
async def list_strategies() -> dict[str, list[str]]:
    """List all available strategy configurations.

    Returns:
        Dictionary with "items" key containing list of config names
    """
    try:
        configs = storage.list_configs()
        return {"items": configs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list configs: {e}")


@app.get("/strategies/{name}")
async def get_strategy(name: str) -> dict[str, Any]:
    """Load a strategy configuration by name.

    Args:
        name: Strategy config name

    Returns:
        Strategy configuration dictionary

    Raises:
        HTTPException: If config not found (404) or error loading (500)
    """
    try:
        config = storage.load_config(name)
        return config
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Config '{name}' not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load config: {e}")


@app.post("/strategies/{name}")
async def save_strategy(name: str, config: dict[str, Any]) -> dict[str, str]:
    """Save or update a strategy configuration.

    Args:
        name: Strategy config name
        config: Strategy configuration dictionary

    Returns:
        Status dictionary with "status" and "name"

    Raises:
        HTTPException: If validation fails (400) or save error (500)
    """
    # Basic validation
    if "strategy_type" not in config:
        raise HTTPException(
            status_code=400, detail="Config must contain 'strategy_type' field"
        )

    if "mode" not in config:
        raise HTTPException(status_code=400, detail="Config must contain 'mode' field")

    try:
        storage.save_config(name, config)
        return {"status": "saved", "name": name}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save config: {e}")


@app.delete("/strategies/{name}")
async def delete_strategy(name: str) -> dict[str, str]:
    """Delete a strategy configuration.

    Args:
        name: Strategy config name

    Returns:
        Status dictionary

    Raises:
        HTTPException: If config not found (404) or error deleting (500)
    """
    try:
        storage.delete_config(name)
        return {"status": "deleted", "name": name}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Config '{name}' not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete config: {e}")


class BacktestRequest:
    """Request model for backtest endpoint."""

    def __init__(
        self,
        config: dict[str, Any],
        data_path: str,
        use_llm: bool = False,
        llm_model: str | None = None,
        llm_url: str | None = None,
        initial_equity: float = 10_000.0,
        fee_rate: float = 0.001,
        slippage_bps: float = 1.0,
    ):
        self.config = config
        self.data_path = data_path
        self.use_llm = use_llm
        self.llm_model = llm_model
        self.llm_url = llm_url
        self.initial_equity = initial_equity
        self.fee_rate = fee_rate
        self.slippage_bps = slippage_bps


@app.post("/backtest")
async def run_backtest(request: dict[str, Any]) -> dict[str, Any]:
    """Run a backtest for a given configuration and data.

    Request body should contain:
        - config: dict (strategy configuration)
        - data_path: str (path to CSV file)
        - use_llm: bool (optional, default: false)
        - llm_model: str (optional, default: llama3.2)
        - llm_url: str (optional, default: http://localhost:11434)
        - initial_equity: float (optional, default: 10000)
        - fee_rate: float (optional, default: 0.001)
        - slippage_bps: float (optional, default: 1.0)

    Returns:
        Backtest summary dictionary with metrics

    Raises:
        HTTPException: If validation fails (400) or backtest error (500)
    """
    # Validate required fields
    if "config" not in request:
        raise HTTPException(status_code=400, detail="Missing 'config' field")

    if "data_path" not in request:
        raise HTTPException(status_code=400, detail="Missing 'data_path' field")

    # Extract parameters with defaults
    config = request["config"]
    data_path = request["data_path"]
    use_llm = request.get("use_llm", False)
    llm_model = request.get("llm_model")
    llm_url = request.get("llm_url")
    initial_equity = request.get("initial_equity", 10_000.0)
    fee_rate = request.get("fee_rate", 0.001)
    slippage_bps = request.get("slippage_bps", 1.0)

    try:
        # Run backtest using service layer
        summary = run_backtest_from_config_dict(
            config=config,
            data_path=data_path,
            use_llm=use_llm,
            llm_model=llm_model,
            llm_url=llm_url,
            initial_equity=initial_equity,
            fee_rate=fee_rate,
            slippage_bps=slippage_bps,
        )

        return summary

    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Backtest failed: {type(e).__name__}: {e}"
        )


def main() -> None:
    """Run the API server for local development."""
    import uvicorn

    uvicorn.run(
        "llm_trading_system.api.server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )


if __name__ == "__main__":
    main()
