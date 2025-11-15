"""Market data aggregation and prompt preparation module."""
from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import pstdev
from typing import Any, Dict, Iterable, List, Optional

import requests


@dataclass(slots=True)
class Settings:
    """Application configuration loaded from environment variables."""

    base_asset: str
    horizon_hours: int
    binance_base_url: str
    binance_fapi_url: str
    cryptoquant_api_key: Optional[str]
    cryptoquant_base_url: str
    cryptopanic_api_key: Optional[str]
    cryptopanic_base_url: str
    newsapi_key: Optional[str]
    newsapi_base_url: str


DEFAULT_TIMEOUT: int = 10


def _safe_float(value: Any) -> Optional[float]:
    """Convert value to float when possible."""

    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_binance_market_data(settings: Settings, symbol: str) -> Dict[str, Optional[float]]:
    """Fetch aggregated market metrics for the provided symbol from Binance."""

    spot_price: Optional[float] = None
    change_pct: Optional[float] = None
    volume_usd: Optional[float] = None
    realized_vol: Optional[float] = None
    funding_rate: Optional[float] = None
    open_interest: Optional[float] = None
    spread_bps: Optional[float] = None
    ob_imbalance: Optional[float] = None

    session = requests.Session()

    try:
        ticker_resp = session.get(
            f"{settings.binance_base_url}/api/v3/ticker/24hr",
            params={"symbol": symbol},
            timeout=DEFAULT_TIMEOUT,
        )
        ticker_resp.raise_for_status()
        ticker_data = ticker_resp.json()
        spot_price = _safe_float(ticker_data.get("lastPrice"))
        change_pct = _safe_float(ticker_data.get("priceChangePercent"))
        volume_usd = _safe_float(ticker_data.get("quoteVolume"))
    except requests.RequestException as exc:
        logging.error("Failed to fetch Binance 24h ticker: %s", exc)

    try:
        klines_resp = session.get(
            f"{settings.binance_base_url}/api/v3/klines",
            params={"symbol": symbol, "interval": "1m", "limit": 200},
            timeout=DEFAULT_TIMEOUT,
        )
        klines_resp.raise_for_status()
        klines = klines_resp.json()
        closes = [float(kline[4]) for kline in klines if len(kline) > 4]
        if len(closes) > 1:
            log_returns: List[float] = [
                math.log(curr / prev) for prev, curr in zip(closes[:-1], closes[1:]) if prev > 0
            ]
            if len(log_returns) >= 2:
                # Annualize assuming 1-minute data -> 1440 periods per day, 365 days.
                minute_factor = math.sqrt(1440 * 365)
                realized_vol = pstdev(log_returns) * minute_factor
            elif log_returns:
                realized_vol = abs(log_returns[0])
        else:
            realized_vol = None
    except requests.RequestException as exc:
        logging.error("Failed to fetch Binance klines: %s", exc)

    try:
        funding_resp = session.get(
            f"{settings.binance_fapi_url}/fapi/v1/fundingRate",
            params={"symbol": symbol, "limit": 1},
            timeout=DEFAULT_TIMEOUT,
        )
        funding_resp.raise_for_status()
        funding_data = funding_resp.json()
        if funding_data:
            funding_rate = _safe_float(funding_data[0].get("fundingRate"))
    except requests.RequestException as exc:
        logging.error("Failed to fetch Binance funding rates: %s", exc)

    try:
        oi_resp = session.get(
            f"{settings.binance_fapi_url}/fapi/v1/openInterest",
            params={"symbol": symbol},
            timeout=DEFAULT_TIMEOUT,
        )
        oi_resp.raise_for_status()
        open_interest = _safe_float(oi_resp.json().get("openInterest"))
    except requests.RequestException as exc:
        logging.error("Failed to fetch Binance open interest: %s", exc)

    try:
        depth_resp = session.get(
            f"{settings.binance_base_url}/api/v3/depth",
            params={"symbol": symbol, "limit": 100},
            timeout=DEFAULT_TIMEOUT,
        )
        depth_resp.raise_for_status()
        depth = depth_resp.json()
        bids = depth.get("bids", [])
        asks = depth.get("asks", [])
        if bids and asks:
            top_bid = float(bids[0][0])
            top_ask = float(asks[0][0])
            if top_bid > 0:
                spread_bps = (top_ask - top_bid) / top_bid * 10_000
            sum_bid_vol = sum(float(b[1]) for b in bids if len(b) > 1)
            sum_ask_vol = sum(float(a[1]) for a in asks if len(a) > 1)
            denom = sum_bid_vol + sum_ask_vol
            if denom > 0:
                ob_imbalance = (sum_bid_vol - sum_ask_vol) / denom
    except requests.RequestException as exc:
        logging.error("Failed to fetch Binance orderbook: %s", exc)

    return {
        "spot_price": spot_price,
        "change_24h_pct": change_pct,
        "volume_24h_usd": volume_usd,
        "realized_vol": realized_vol,
        "funding_rate": funding_rate,
        "open_interest": open_interest,
        "btc_dominance": None,
        "stablecoin_flows_ex": None,
        "perp_spot_basis_bps": None,
        "spread_bps": spread_bps,
        "ob_imbalance": ob_imbalance,
    }


def _get_cryptoquant_endpoint(settings: Settings, path: str) -> str:
    return f"{settings.cryptoquant_base_url.rstrip('/')}/{path.lstrip('/')}"


def _fetch_cryptoquant_metric(session: requests.Session, url: str, api_key: str) -> Optional[Dict[str, Any]]:
    try:
        response = session.get(url, params={"api_key": api_key}, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        return data
    except requests.RequestException as exc:
        logging.error("CryptoQuant request failed for %s: %s", url, exc)
    except ValueError as exc:
        logging.error("Invalid JSON from CryptoQuant for %s: %s", url, exc)
    return None


def fetch_cryptoquant_onchain_data(settings: Settings) -> Dict[str, Optional[float]]:
    """Retrieve on-chain signals from CryptoQuant's public endpoints."""

    if not settings.cryptoquant_api_key:
        logging.warning("CRYPTOQUANT_API_KEY is missing; returning placeholder on-chain data.")
        return {
            "exchange_netflows_btc": None,
            "whale_transfers": None,
            "new_addresses_vs_30d": None,
            "active_addresses_vs_30d": None,
            "stablecoin_supply_change_pct": None,
        }

    session = requests.Session()
    exchange_netflows: Optional[float] = None
    whale_transfers: Optional[int] = None
    new_addresses: Optional[float] = None
    active_addresses: Optional[float] = None
    stablecoin_supply_change: Optional[float] = None

    # The following endpoints are representative; replace with actual ones when integrating.
    exchange_netflow_url = _get_cryptoquant_endpoint(
        settings, "btc/exchange-flows/netflow"
    )
    whale_transfers_url = _get_cryptoquant_endpoint(
        settings, "btc/whale-tracking/whales-transfers"
    )
    new_addresses_url = _get_cryptoquant_endpoint(
        settings, "btc/network/new-addresses"
    )
    active_addresses_url = _get_cryptoquant_endpoint(
        settings, "btc/network/active-addresses"
    )
    stablecoin_supply_url = _get_cryptoquant_endpoint(
        settings, "stablecoin/marketcap/all-exchanges"
    )

    try:
        netflow_data = _fetch_cryptoquant_metric(
            session, exchange_netflow_url, settings.cryptoquant_api_key
        )
        if netflow_data and "result" in netflow_data:
            latest = netflow_data["result"][-1]
            exchange_netflows = _safe_float(latest.get("value"))
    except (IndexError, KeyError, TypeError):
        logging.error("Unexpected structure for exchange netflows data.")

    try:
        whale_data = _fetch_cryptoquant_metric(
            session, whale_transfers_url, settings.cryptoquant_api_key
        )
        if whale_data and "result" in whale_data:
            latest = whale_data["result"][-1]
            whale_transfers = latest.get("count")
            if whale_transfers is not None:
                whale_transfers = int(whale_transfers)
    except (IndexError, KeyError, TypeError, ValueError):
        logging.error("Unexpected structure for whale transfers data.")

    try:
        new_addresses_data = _fetch_cryptoquant_metric(
            session, new_addresses_url, settings.cryptoquant_api_key
        )
        active_addresses_data = _fetch_cryptoquant_metric(
            session, active_addresses_url, settings.cryptoquant_api_key
        )
        if new_addresses_data and "result" in new_addresses_data:
            latest = new_addresses_data["result"][-1]
            new_addresses = _safe_float(latest.get("value_change_rate"))
        if active_addresses_data and "result" in active_addresses_data:
            latest = active_addresses_data["result"][-1]
            active_addresses = _safe_float(latest.get("value_change_rate"))
    except (IndexError, KeyError, TypeError):
        logging.error("Unexpected structure for address metrics data.")

    try:
        stablecoin_data = _fetch_cryptoquant_metric(
            session, stablecoin_supply_url, settings.cryptoquant_api_key
        )
        if stablecoin_data and "result" in stablecoin_data:
            latest = stablecoin_data["result"][-1]
            stablecoin_supply_change = _safe_float(latest.get("value_change_rate"))
    except (IndexError, KeyError, TypeError):
        logging.error("Unexpected structure for stablecoin data.")

    return {
        "exchange_netflows_btc": exchange_netflows,
        "whale_transfers": whale_transfers,
        "new_addresses_vs_30d": new_addresses,
        "active_addresses_vs_30d": active_addresses,
        "stablecoin_supply_change_pct": stablecoin_supply_change,
    }


def _derive_sentiment_from_votes(votes: Dict[str, Any], tags: Iterable[str]) -> float:
    """Heuristic sentiment score using CryptoPanic vote counts and tags."""

    positive = votes.get("positive", 0) if isinstance(votes, dict) else 0
    negative = votes.get("negative", 0) if isinstance(votes, dict) else 0
    denom = positive + negative
    sentiment = 0.0
    if denom > 0:
        sentiment = (positive - negative) / denom
    if "bullish" in tags:
        sentiment += 0.2
    if "bearish" in tags:
        sentiment -= 0.2
    return max(-1.0, min(1.0, sentiment))


def _derive_impact_score(votes: Dict[str, Any], tags: Iterable[str]) -> float:
    """Simple heuristic for impact score based on importance and vote counts."""

    important_votes = votes.get("important", 0) if isinstance(votes, dict) else 0
    base = min(1.0, important_votes / 5.0)
    if "important" in tags:
        base = max(base, 0.6)
    if "breaking" in tags:
        base = max(base, 0.8)
    return float(round(min(base + 0.1, 1.0), 3))


def fetch_cryptopanic_news(settings: Settings, max_items: int = 10) -> List[Dict[str, Any]]:
    """Fetch curated crypto news from the CryptoPanic API."""

    if not settings.cryptopanic_api_key:
        logging.warning("CRYPTOPANIC_API_KEY is missing; returning empty news list.")
        return []

    try:
        response = requests.get(
            f"{settings.cryptopanic_base_url.rstrip('/')}/posts/",
            params={
                "auth_token": settings.cryptopanic_api_key,
                "filter": "important",
                "public": "true",
            },
            timeout=DEFAULT_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        results = payload.get("results", [])
    except requests.RequestException as exc:
        logging.error("Failed to fetch CryptoPanic news: %s", exc)
        return []
    except ValueError as exc:
        logging.error("Invalid JSON from CryptoPanic: %s", exc)
        return []

    items: List[Dict[str, Any]] = []
    for item in results[:max_items]:
        title = item.get("title") or item.get("description") or ""
        published_at = item.get("published_at") or item.get("created_at")
        source = item.get("source", {}).get("title")
        domain = item.get("domain")
        tags = item.get("tags") or []
        votes = item.get("votes") or {}
        sentiment = _derive_sentiment_from_votes(votes, tags)
        impact_score = _derive_impact_score(votes, tags)
        summary_parts = [part for part in [title, domain] if part]
        summary = " - ".join(summary_parts)
        items.append(
            {
                "source": source or "CryptoPanic",
                "time_utc": published_at,
                "sentiment": sentiment,
                "impact_score": impact_score,
                "text": summary,
            }
        )

    return items


def fetch_newsapi_news(settings: Settings, max_items: int = 10) -> List[Dict[str, Any]]:
    """Fetch additional crypto-related articles from NewsAPI if credentials are available."""

    if not settings.newsapi_key:
        logging.warning("NEWSAPI_KEY missing; skipping NewsAPI source.")
        return []

    try:
        response = requests.get(
            f"{settings.newsapi_base_url.rstrip('/')}/everything",
            params={
                "q": "bitcoin OR crypto",
                "pageSize": max_items,
                "sortBy": "publishedAt",
                "language": "en",
            },
            headers={"X-Api-Key": settings.newsapi_key},
            timeout=DEFAULT_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        articles = payload.get("articles", [])
    except requests.RequestException as exc:
        logging.error("Failed to fetch NewsAPI articles: %s", exc)
        return []
    except ValueError as exc:
        logging.error("Invalid JSON from NewsAPI: %s", exc)
        return []

    items: List[Dict[str, Any]] = []
    for article in articles[:max_items]:
        source = (article.get("source") or {}).get("name") or "NewsAPI"
        published_at = article.get("publishedAt")
        title = article.get("title") or ""
        description = article.get("description") or ""
        text = (title + ": " + description).strip(": ")
        items.append(
            {
                "source": source,
                "time_utc": published_at,
                "sentiment": 0.0,  # Placeholder; integrate sentiment model later.
                "impact_score": 0.4,
                "text": text,
            }
        )

    return items


def build_market_snapshot(settings: Settings) -> Dict[str, Any]:
    """Aggregate market, on-chain, and news data into a single snapshot."""

    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    market = fetch_binance_market_data(settings, settings.base_asset)
    onchain = fetch_cryptoquant_onchain_data(settings)
    news_items = fetch_cryptopanic_news(settings)
    news_items.extend(fetch_newsapi_news(settings))

    snapshot: Dict[str, Any] = {
        "timestamp_utc": timestamp,
        "base_asset": settings.base_asset,
        "horizon_hours": settings.horizon_hours,
        "market": market,
        "onchain": onchain,
        "news": news_items,
        "macro_context": "",
    }
    return snapshot


def build_system_prompt() -> str:
    """Return the system prompt for the regime estimation LLM."""

    return (
        "You are a crypto market regime estimation model.\n\n"
        "Your ONLY task:\n"
        "Given a snapshot of aggregated market data, on-chain data, and a pre-filtered news/narrative summary,\n"
        "estimate the probability of the market being in a bull or bear regime for a specified horizon.\n\n"
        "CRITICAL CONSTRAINTS (MUST FOLLOW):\n\n"
        "1. NO EXTERNAL DATA:\n"
        "   - You do NOT have access to the internet or any real-time feeds.\n"
        "   - You MUST NOT use any facts, prices, events, or news that are not explicitly provided in the user message.\n"
        "   - If something is not present in the input (for example: a specific ETF approval, regulatory action,\n"
        "     exact BTC price, volume, or macro event), you must treat it as UNKNOWN and DO NOT MENTION IT.\n\n"
        "2. INPUT IS THE ONLY SOURCE OF TRUTH:\n"
        "   - If the user input contradicts anything you \"remember\" from training, ALWAYS trust the user input.\n"
        "   - You must never override or \"correct\" the numbers from the input based on your training data.\n"
        "   - You can use your training data ONLY to apply generic domain heuristics\n"
        "     (e.g. \"strong net inflows to exchanges often increase sell pressure\"),\n"
        "     but NOT to inject specific real-world facts, dates, names, or events.\n\n"
        "3. NO HALLUCINATED FACTS:\n"
        "   - Do NOT invent specific news (\"recent ETF approvals\", \"new regulations\", \"exchange hacks\", etc.)\n"
        "     unless they are explicitly present in the News items provided by the user.\n"
        "   - Do NOT refer to any concrete real-world entities (countries, regulators, funds, companies, tokens, ETFs, exchanges)\n"
        "     unless they appear in the input text.\n"
        "   - You may speak only in generic terms when using domain knowledge (e.g. \"regulatory risk\", \"macro uncertainty\"),\n"
        "     unless a specific entity is explicitly mentioned in the input.\n\n"
        "4. UNCERTAINTY HANDLING:\n"
        "   - If the provided data is sparse, low-impact, or contradictory, keep probabilities closer to 0.5\n"
        "     and set confidence_level = \"low\".\n"
        "   - You are a conservative, calibration-oriented estimator:\n"
        "     values near 0.50–0.60 mean weak bias, 0.60–0.75 moderate, >0.75 strong.\n"
        "   - Never output extreme probabilities (e.g. >0.9 or <0.1) without very strong and consistent evidence in the input.\n\n"
        "5. OUTPUT FORMAT:\n"
        "   - Respond with EXACTLY ONE JSON object.\n"
        "   - NO additional text, NO comments, NO markdown.\n"
        "   - JSON must be syntactically valid.\n\n"
        "Definitions:\n\n"
        "- \"Bull regime\": base asset is more likely to trade predominantly higher than the current price over the given horizon.\n"
        "- \"Bear regime\": base asset is more likely to trade predominantly lower than the current price over the given horizon.\n"
        "- \"Neutral regime\": no clear directional edge; however, you must still output prob_bull and prob_bear (summing to 1).\n\n"
        "JSON schema (MUST FOLLOW):\n\n"
        "{\n"
        "  \"horizon_hours\": <number>,\n"
        "  \"base_asset\": \"<string, e.g. 'BTCUSDT'>\",\n\n"
        "  \"prob_bull\": <number between 0 and 1>,\n"
        "  \"prob_bear\": <number between 0 and 1>,\n\n"
        "  \"regime_label\": \"<'bull' | 'bear' | 'neutral'>\",\n"
        "  \"confidence_level\": \"<'low' | 'medium' | 'high'>\",\n\n"
        "  \"scores\": {\n"
        "    \"global_sentiment\": <number from -1 to 1>,\n"
        "    \"btc_sentiment\": <number from -1 to 1>,\n"
        "    \"altcoin_sentiment\": <number from -1 to 1>,\n"
        "    \"onchain_pressure\": <number from -1 to 1>,\n"
        "    \"liquidity_risk\": <number from 0 to 1>,\n"
        "    \"news_risk\": <number from 0 to 1>,\n"
        "    \"trend_strength\": <number from 0 to 1>\n"
        "  },\n\n"
        "  \"factors_summary\": [\n"
        "    \"<short key factor phrase 1>\",\n"
        "    \"<short key factor phrase 2>\",\n"
        "    \"<short key factor phrase 3>\"\n"
        "  ],\n\n"
        "  \"reasoning_short\": \"<1–3 concise sentences explaining the key drivers based ONLY on the provided input>\",\n"
        "  \"timestamp_utc\": \"<ISO8601 string from the input>\"\n"
        "}\n\n"
        "Additional rules:\n\n"
        "- prob_bull + prob_bear MUST equal 1.0 (within 1e-6).\n"
        "- Regime label:\n"
        "  - \"bull\" if prob_bull > 0.6,\n"
        "  - \"bear\" if prob_bear > 0.6,\n"
        "  - otherwise \"neutral\".\n"
        "- reasoning_short must reference only numbers, metrics, or news items that are present in the input.\n"
        "  If you refer to \"ETF flows\", \"regulation fears\", etc., they MUST appear in the News section.\n"
    )


def _format_value(value: Any) -> str:
    if value is None:
        return "None"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def build_user_prompt(snapshot: Dict[str, Any], horizon_hours: int, base_asset: str) -> str:
    """Construct the user prompt containing the market snapshot details."""

    market = snapshot.get("market", {})
    onchain = snapshot.get("onchain", {})
    news = snapshot.get("news", [])
    macro_context = snapshot.get("macro_context", "") or ""

    news_lines = []
    for item in news:
        news_lines.append(
            "- source: \"{source}\"\n"
            "  time_utc: \"{time}\"\n"
            "  sentiment: {sentiment}\n"
            "  impact_score: {impact}\n"
            "  text: \"{text}\"".format(
                source=item.get("source", "N/A"),
                time=item.get("time_utc", "N/A"),
                sentiment=_format_value(item.get("sentiment")),
                impact=_format_value(item.get("impact_score")),
                text=(item.get("text") or "").replace("\n", " "),
            )
        )
    news_block = "\n".join(news_lines) if news_lines else "(no news items)"

    prompt = (
        "IMPORTANT:\n"
        "All numerical values, metrics, and news relevant for this task are already included below.\n"
        "You MUST NOT assume any additional real-time data, prices, or events.\n"
        "If something is not explicitly present in the input, you MUST treat it as unknown and MUST NOT mention it.\n"
        "Do not refer to the internet, real-time feeds, or your training data for current market state.\n\n"
        "Current analysis request.\n\n"
        f"Base asset: {base_asset}\n"
        f"Horizon_hours: {horizon_hours}\n\n"
        f"Current UTC timestamp: {snapshot.get('timestamp_utc', 'N/A')}\n\n"
        "=== 1. Market data (aggregated numbers) ===\n"
        "Timeframe summary:\n"
        f"- Spot price: {_format_value(market.get('spot_price'))}\n"
        f"- 24h change (%): {_format_value(market.get('change_24h_pct'))}\n"
        f"- 24h volume (USD): {_format_value(market.get('volume_24h_usd'))}\n"
        f"- Realized volatility (24h): {_format_value(market.get('realized_vol'))}\n"
        f"- Funding rate (perps): {_format_value(market.get('funding_rate'))}\n"
        f"- Open interest (relative to 30d avg): {_format_value(market.get('open_interest'))}\n"
        f"- BTC dominance (%): {_format_value(market.get('btc_dominance'))}\n"
        f"- Stablecoin netflows to exchanges (24h, USD): {_format_value(market.get('stablecoin_flows_ex'))}\n"
        f"- Perps premium vs spot (bps): {_format_value(market.get('perp_spot_basis_bps'))}\n\n"
        "Orderbook / microstructure summary:\n"
        f"- Top-of-book spread (bps): {_format_value(market.get('spread_bps'))}\n"
        f"- Orderbook imbalance (bid - ask, normalized -1..1): {_format_value(market.get('ob_imbalance'))}\n\n"
        "=== 2. On-chain metrics summary ===\n"
        f"- Exchange netflows (BTC, recent window): {_format_value(onchain.get('exchange_netflows_btc'))}\n"
        f"- Whales large transfers count: {_format_value(onchain.get('whale_transfers'))}\n"
        f"- New addresses (vs 30d avg, %): {_format_value(onchain.get('new_addresses_vs_30d'))}\n"
        f"- Active addresses (vs 30d avg, %): {_format_value(onchain.get('active_addresses_vs_30d'))}\n"
        f"- Stablecoin supply change (%): {_format_value(onchain.get('stablecoin_supply_change_pct'))}\n\n"
        "=== 3. News & narrative summary (pre-filtered) ===\n"
        "Below is a list of key news items and narrative snippets. They are already deduplicated and pre-filtered by relevance.\n\n"
        "Each item format:\n"
        "- source: <short source name>\n"
        "- time_utc: <ISO8601>\n"
        "- sentiment: <estimated sentiment from -1 (very negative) to +1 (very positive)>\n"
        "- impact_score: <0..1, our rough estimate of potential market impact>\n"
        "- text: <short summary>\n\n"
        "News items:\n"
        f"{news_block}\n\n"
        "=== 4. Optional additional context ===\n"
        "Macro context (if provided):\n"
        f"{macro_context if macro_context else 'N/A'}\n\n"
        "You MUST:\n\n"
        "- Base your estimation ONLY on the data explicitly provided above.\n"
        "- NOT introduce any specific external facts (e.g. particular ETF approvals, specific regulatory actions, hacks, etc.)\n"
        "  unless they appear in the News items.\n"
        "- Output EXACTLY ONE JSON object matching the schema defined in the system message.\n"
        "- Do NOT add any extra text before or after the JSON.\n"
    )

    return prompt


def load_settings() -> Settings:
    """Load application settings from environment variables."""

    return Settings(
        base_asset=os.getenv("BASE_ASSET", "BTCUSDT"),
        horizon_hours=int(os.getenv("HORIZON_HOURS", "4")),
        binance_base_url=os.getenv("BINANCE_BASE_URL", "https://api.binance.com"),
        binance_fapi_url=os.getenv("BINANCE_FAPI_URL", "https://fapi.binance.com"),
        cryptoquant_api_key=os.getenv("CRYPTOQUANT_API_KEY"),
        cryptoquant_base_url=os.getenv("CRYPTOQUANT_BASE_URL", "https://api.cryptoquant.com/v1"),
        cryptopanic_api_key=os.getenv("CRYPTOPANIC_API_KEY"),
        cryptopanic_base_url=os.getenv("CRYPTOPANIC_BASE_URL", "https://cryptopanic.com/api/v1"),
        newsapi_key=os.getenv("NEWSAPI_KEY"),
        newsapi_base_url=os.getenv("NEWSAPI_BASE_URL", "https://newsapi.org/v2"),
    )


def main() -> None:
    """Application entry point."""

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = load_settings()
    logging.info("Building market snapshot for %s", settings.base_asset)
    snapshot = build_market_snapshot(settings)
    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt(snapshot, settings.horizon_hours, settings.base_asset)

    print("===== SYSTEM PROMPT =====")
    print(system_prompt)
    print("===== USER PROMPT =====")
    print(user_prompt)


if __name__ == "__main__":
    main()
