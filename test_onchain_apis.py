"""Test script to verify free on-chain API accessibility and functionality."""

import logging
import sys

import requests


def test_coinmetrics_api() -> bool:
    """Test CoinMetrics Community API."""
    print("\n" + "="*70)
    print("Testing CoinMetrics Community API")
    print("="*70)

    try:
        url = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
        params = {
            "assets": "btc",
            "metrics": "AdrActCnt,AdrNewCnt",
            "frequency": "1d",
            "limit_per_asset": 3,
        }

        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if "data" in data and len(data["data"]) > 0:
            print(f"✅ CoinMetrics API доступен")
            print(f"   Получено записей: {len(data['data'])}")

            # Show sample data
            sample = data["data"][0]
            print(f"   Пример данных:")
            print(f"     - time: {sample.get('time', 'N/A')}")
            print(f"     - AdrActCnt: {sample.get('AdrActCnt', 'N/A')}")
            print(f"     - AdrNewCnt: {sample.get('AdrNewCnt', 'N/A')}")
            return True
        else:
            print("❌ CoinMetrics API: некорректный формат ответа")
            print(f"   Response: {data}")
            return False

    except requests.RequestException as exc:
        print(f"❌ CoinMetrics API недоступен: {exc}")
        return False
    except Exception as exc:
        print(f"❌ Ошибка при обработке CoinMetrics данных: {exc}")
        return False


def test_blockchain_com_api() -> bool:
    """Test Blockchain.com Charts API."""
    print("\n" + "="*70)
    print("Testing Blockchain.com Charts API")
    print("="*70)

    try:
        url = "https://api.blockchain.info/charts/n-unique-addresses"
        params = {
            "timespan": "7days",
            "format": "json",
        }

        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if "values" in data and len(data["values"]) > 0:
            print(f"✅ Blockchain.com API доступен")
            print(f"   Получено записей: {len(data['values'])}")

            # Show sample data
            sample = data["values"][-1]
            print(f"   Последние данные:")
            print(f"     - timestamp: {sample.get('x', 'N/A')}")
            print(f"     - unique addresses: {sample.get('y', 'N/A'):.0f}")
            return True
        else:
            print("❌ Blockchain.com API: некорректный формат ответа")
            print(f"   Response: {data}")
            return False

    except requests.RequestException as exc:
        print(f"❌ Blockchain.com API недоступен: {exc}")
        return False
    except Exception as exc:
        print(f"❌ Ошибка при обработке Blockchain.com данных: {exc}")
        return False


def test_coinmetrics_stablecoins() -> bool:
    """Test CoinMetrics API for stablecoin data."""
    print("\n" + "="*70)
    print("Testing CoinMetrics Stablecoin Data")
    print("="*70)

    try:
        url = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
        params = {
            "assets": "usdt,usdc",
            "metrics": "SplyCur",
            "frequency": "1d",
            "limit_per_asset": 2,
        }

        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if "data" in data and len(data["data"]) > 0:
            print(f"✅ CoinMetrics Stablecoin данные доступны")
            print(f"   Получено записей: {len(data['data'])}")

            # Group by asset
            for item in data["data"][-2:]:  # Show last 2 entries
                asset = item.get("asset", "unknown").upper()
                supply = item.get("SplyCur")
                time = item.get("time")
                if supply:
                    print(f"     - {asset}: {float(supply):,.0f} (time: {time})")
            return True
        else:
            print("❌ CoinMetrics Stablecoin: некорректный формат ответа")
            return False

    except requests.RequestException as exc:
        print(f"❌ CoinMetrics Stablecoin API недоступен: {exc}")
        return False
    except Exception as exc:
        print(f"❌ Ошибка при обработке stablecoin данных: {exc}")
        return False


def test_binance_api() -> bool:
    """Test Binance API (for completeness)."""
    print("\n" + "="*70)
    print("Testing Binance API")
    print("="*70)

    try:
        url = "https://api.binance.com/api/v3/ticker/24hr"
        params = {"symbol": "BTCUSDT"}

        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if "lastPrice" in data:
            print(f"✅ Binance API доступен")
            print(f"   BTC цена: ${float(data['lastPrice']):,.2f}")
            print(f"   24h изменение: {float(data['priceChangePercent']):.2f}%")
            print(f"   24h объём: ${float(data['quoteVolume']):,.0f}")
            return True
        else:
            print("❌ Binance API: некорректный формат ответа")
            return False

    except requests.RequestException as exc:
        print(f"❌ Binance API недоступен: {exc}")
        return False
    except Exception as exc:
        print(f"❌ Ошибка при обработке Binance данных: {exc}")
        return False


def main() -> None:
    """Run all API tests."""
    logging.basicConfig(level=logging.WARNING)

    print("="*70)
    print("ПРОВЕРКА ДОСТУПНОСТИ БЕСПЛАТНЫХ API ДЛЯ ON-CHAIN ДАННЫХ")
    print("="*70)

    results = {
        "CoinMetrics BTC Metrics": test_coinmetrics_api(),
        "CoinMetrics Stablecoins": test_coinmetrics_stablecoins(),
        "Blockchain.com Charts": test_blockchain_com_api(),
        "Binance Market Data": test_binance_api(),
    }

    print("\n" + "="*70)
    print("ИТОГИ ТЕСТИРОВАНИЯ")
    print("="*70)

    for name, success in results.items():
        status = "✅ PASSED" if success else "❌ FAILED"
        print(f"{status} - {name}")

    all_passed = all(results.values())

    print("\n" + "="*70)
    if all_passed:
        print("✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ УСПЕШНО!")
        print("   Все бесплатные API доступны и работают корректно.")
        print("   market_snapshot.py может быть запущен без API ключей.")
    else:
        print("⚠️  НЕКОТОРЫЕ ТЕСТЫ НЕ ПРОЙДЕНЫ")
        print("   Проверьте соединение с интернетом или доступность API.")
        sys.exit(1)
    print("="*70)


if __name__ == "__main__":
    main()
