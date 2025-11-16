import json
from typing import Any, Dict

from llm_trading_system.core.regime_engine import evaluate_regime_and_size


class DummyClient:
    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
    ) -> str:
        return json.dumps(
            {
                "horizon_hours": 4,
                "base_asset": "BTCUSDT",
                "prob_bull": 0.55,
                "prob_bear": 0.45,
                "regime_label": "bull",
                "confidence_level": "medium",
                "scores": {
                    "global_sentiment": 0.2,
                    "btc_sentiment": 0.3,
                    "altcoin_sentiment": 0.0,
                    "onchain_pressure": 0.1,
                    "liquidity_risk": 0.4,
                    "news_risk": 0.3,
                    "trend_strength": 0.6,
                },
                "factors_summary": [
                    "dummy factor 1",
                    "dummy factor 2",
                    "dummy factor 3",
                ],
                "reasoning_short": "dummy reasoning",
                "timestamp_utc": "2025-01-01T00:00:00Z",
            }
        )


def make_mock_snapshot() -> Dict[str, Any]:
    return {
        "timestamp_utc": "2025-01-01T00:00:00Z",
        "base_asset": "BTCUSDT",
        "horizon_hours": 4,
        "market": {
            "spot_price": 45000.0,
            "change_24h_pct": 1.0,
            "volume_24h_usd": 10_000_000_000,
            "realized_vol": 0.4,
            "funding_rate": 0.0001,
            "open_interest": 5_000_000_000,
            "btc_dominance": 50.0,
            "stablecoin_flows_ex": 100_000_000,
            "perp_spot_basis_bps": 2.0,
            "spread_bps": 0.8,
            "ob_imbalance": 0.1,
        },
        "onchain": {
            "exchange_netflows_btc": -1000,
            "whale_transfers": None,
            "new_addresses_vs_30d": 0.05,
            "active_addresses_vs_30d": 0.07,
            "stablecoin_supply_change_pct": 0.01,
        },
        "news": [],
        "macro_context": "",
    }


def test_evaluate_regime_and_size_with_dummy_client():
    snapshot = make_mock_snapshot()
    client = DummyClient()
    result = evaluate_regime_and_size(
        snapshot=snapshot,
        client=client,
        base_size=0.01,
        k_max=2.0,
        temperature=0.1,
    )

    assert "llm_output" in result
    assert "k_long" in result and "k_short" in result
    assert result["pos_long"] >= 0.0
    assert result["pos_short"] >= 0.0
