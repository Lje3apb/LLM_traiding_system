# Full Cycle Integration Test

Полный end-to-end тест торговой системы от сбора данных до принятия торгового решения.

## Что тестируется

Тест проходит через все этапы работы системы:

```
[1. Сбор данных] → [2. Формирование промптов] → [3. Запрос к LLM] →
[4. Парсинг ответа] → [5. Расчет позиции] → [6. Торговое решение]
```

### Компоненты

1. **market_snapshot.py** - сбор и агрегация данных
   - Рыночные данные с Binance (цена, объем, волатильность)
   - On-chain метрики (адреса, потоки на биржи)
   - Новости (CryptoPanic, NewsAPI)

2. **llm_infra** - работа с LLM
   - OllamaProvider для локальных моделей
   - Retry с экспоненциальной задержкой
   - Парсинг JSON ответов

3. **position_sizing.py** - расчет размера позиции (AGGRESSIVE режим)
   - Конвертация prob_bull/prob_bear в мультипликаторы
   - Non-linear edge amplification (EDGE_GAIN=2.5, EDGE_GAMMA=0.7)
   - Confidence-based scaling (low: 0.7x, medium: 1.0x, high: 1.3x)
   - Trend strength alignment (0.8-1.2x boost)
   - Учет рисков (liquidity, news) с penalty до 30%
   - Финальный размер позиции

## Быстрый старт

### 1. Убедитесь, что Ollama запущена

```bash
# Проверка статуса
./check_ollama.sh

# Если не запущена:
ollama serve

# В другом терминале загрузите модель (если нет):
ollama pull gpt-oss:20b
```

### 2. Запустите тест с mock данными

```bash
# Базовый тест (без реальных API)
python3 test_full_cycle.py

# С указанием модели
python3 test_full_cycle.py --model llama3.2
```

### 3. Запустите с реальными данными

```bash
# Требует API ключи в переменных окружения
export CRYPTOPANIC_API_KEY="your_key"
export NEWSAPI_KEY="your_key"

python3 test_full_cycle.py --real-data
```

## Параметры запуска

```bash
python3 test_full_cycle.py [OPTIONS]

Опции:
  --real-data              Использовать реальные данные с API
  --model MODEL            Модель Ollama (по умолчанию: gpt-oss:20b)
  --ollama-url URL         URL Ollama API (по умолчанию: http://localhost:11434)
  -h, --help               Показать справку
```

## Примеры использования

### Тест с маленькой моделью (быстро)

```bash
python3 test_full_cycle.py --model llama3.2
```

### Тест с большой моделью (лучшее качество)

```bash
python3 test_full_cycle.py --model gpt-oss:20b
```

### Полный тест с реальными данными

```bash
# Установите переменные окружения
export BASE_ASSET="BTCUSDT"
export HORIZON_HOURS="4"
export CRYPTOPANIC_API_KEY="your_cryptopanic_key"
export NEWSAPI_KEY="your_newsapi_key"

# Запустите тест
python3 test_full_cycle.py --real-data --model gpt-oss:20b
```

### Тест с удаленным Ollama

```bash
python3 test_full_cycle.py --ollama-url http://192.168.1.100:11434
```

## Что вы увидите

### Вывод теста

```
================================================================================
FULL CYCLE INTEGRATION TEST
================================================================================

[STEP 1] Collecting market data...
--------------------------------------------------------------------------------
Using MOCK market data for testing...
✓ Data collected for BTCUSDT, horizon: 4h
  Timestamp: 2025-01-15T10:30:00+00:00
  Spot price: 45230.5
  24h change: 2.35%
  News items: 3

[STEP 2] Building prompts for LLM...
--------------------------------------------------------------------------------
✓ System prompt length: 5102 chars
✓ User prompt length: 2341 chars

[STEP 3] Sending request to LLM...
--------------------------------------------------------------------------------
Model: gpt-oss:20b
Endpoint: http://localhost:11434
Waiting for LLM response (this may take 10-60 seconds)...
✓ Received response from LLM
  Response length: 847 chars

[STEP 4] Parsing LLM response...
--------------------------------------------------------------------------------
✓ Successfully parsed JSON response
  Regime: bull
  Confidence: medium
  Bull probability: 68.00%
  Bear probability: 32.00%

[STEP 5] Calculating position sizing...
--------------------------------------------------------------------------------
✓ Position sizing calculated (AGGRESSIVE mode)
  Long multiplier (k_long):  1.3370
  Short multiplier (k_short): 0.0000
  Long position size:  0.013370 (1.34% capital)
  Short position size: 0.000000 (0.00% capital)

Note: New aggressive position sizing with non-linear edge amplification
      Multipliers can now range from 0.0 to k_max (default 2.0)

================================================================================
FINAL RESULTS
================================================================================

Asset: BTCUSDT
Timestamp: 2025-01-15T10:30:00+00:00
Horizon: 4 hours

REGIME ASSESSMENT:
  Regime:      BULL
  Confidence:  HIGH (now encouraged: 0.6-0.85 probabilities)
  Bull prob:   75.0% (less conservative than before)
  Bear prob:   25.0%

MARKET SCORES:
  Global sentiment:   +0.42
  BTC sentiment:      +0.55
  Onchain pressure:   +0.23
  Trend strength:     0.68
  Liquidity risk:     0.25
  News risk:          0.18

POSITION SIZING (AGGRESSIVE):
  Base size:          1.0% capital
  Neutral baseline:   0.5 (BASE_K)
  Long multiplier:    1.34x (aggressive amplification)
  Short multiplier:   0.00x (strong directional bias)
  → LONG position:    1.34% capital
  → SHORT position:   0.00% capital

  Algorithm: edge_eff = (|prob_bull - 0.5| * 2.5) ^ 0.7
             edge_eff *= confidence_scale * trend_scale
             k_long = 0.5 + edge_eff (if bullish)
             k_short = 0.5 - edge_eff (if bullish)

REASONING:
  Positive institutional flows and strong network metrics support bullish outlook.
  Moderate liquidity and low news risk allow for increased position sizing.

KEY FACTORS:
  1. Major institutional BTC allocation announced
  2. Network hashrate at all-time high
  3. Stablecoin inflows increasing

================================================================================
TRADING RECOMMENDATION:
================================================================================
FAVOR LONG positions (multiplier: 1.34x)
AVOID SHORT positions (multiplier: 0.00x - strong bullish bias)
================================================================================

NOTE: New aggressive regime estimator produces:
- More confident probabilities (0.6-0.85 instead of ~0.5)
- Non-linear position sizing amplification
- Stronger directional bias (shorts disabled in bull regime)

✓ Full cycle test completed successfully!
```

## Структура LLM ответа

LLM должна вернуть JSON со следующей структурой:

**ВАЖНО**: После обновления системного промпта, LLM теперь поощряется выводить
более уверенные вероятности (0.6-0.85), а не консервативные значения ~0.5.

```json
{
  "horizon_hours": 4,
  "base_asset": "BTCUSDT",
  "prob_bull": 0.75,  // Теперь может быть 0.6-0.85 при aligned signals
  "prob_bear": 0.25,
  "regime_label": "bull",
  "confidence_level": "high",  // "low" (0.7x), "medium" (1.0x), или "high" (1.3x)
  "scores": {
    "global_sentiment": 0.42,
    "btc_sentiment": 0.55,
    "altcoin_sentiment": 0.30,
    "onchain_pressure": 0.23,
    "liquidity_risk": 0.25,
    "news_risk": 0.18,
    "trend_strength": 0.68
  },
  "factors_summary": [
    "Major institutional BTC allocation announced",
    "Network hashrate at all-time high",
    "Stablecoin inflows increasing"
  ],
  "reasoning_short": "Positive institutional flows and strong network metrics support bullish outlook.",
  "timestamp_utc": "2025-01-15T10:30:00+00:00"
}
```

## Возможные проблемы

### "Connection refused"

**Проблема**: Ollama не запущена

**Решение**:
```bash
ollama serve
```

### "Model not found"

**Проблема**: Модель не загружена

**Решение**:
```bash
ollama pull gpt-oss:20b
# или
ollama pull llama3.2
```

### "Invalid JSON in LLM response"

**Проблема**: LLM вернула невалидный JSON

**Решение**:
- Попробуйте другую модель (некоторые модели лучше следуют инструкциям)
- Уменьшите temperature (уже стоит 0.1, но можно попробовать 0.0)
- Проверьте, что модель достаточно большая (рекомендуется >7B параметров)

### Медленная работа

**Проблема**: Запрос к LLM занимает >2 минуты

**Решение**:
- Используйте меньшую модель (llama3.2, mistral)
- Проверьте, что используется GPU (если доступен)
- Увеличьте timeout в коде (параметр timeout в OllamaProvider)

### API ключи не работают

**Проблема**: Ошибки при сборе реальных данных

**Решение**:
- Используйте mock данные (уберите флаг --real-data)
- Проверьте валидность API ключей
- Многие метрики работают без ключей (Binance, Blockchain.com)

## Рекомендуемые модели

| Модель | Размер | Скорость | Качество | Рекомендация |
|--------|--------|----------|----------|--------------|
| phi | ~1.6GB | Очень быстро | Базовое | Для быстрых тестов |
| llama3.2 | ~2GB | Быстро | Хорошее | **Рекомендуется для тестов** |
| mistral | ~4GB | Средне | Очень хорошее | Для продакшена |
| gpt-oss:20b | ~20GB | Медленно | Отличное | Максимальное качество |

## Следующие шаги

После успешного теста вы можете:

1. **Интегрировать в торгового бота**
   - Запускать каждые N минут
   - Использовать результаты для реальных сделок

2. **Добавить бэктестинг**
   - Собрать исторические данные
   - Проверить качество предсказаний
   - Сравнить новую агрессивную стратегию со старой

3. **Настроить мониторинг**
   - Логировать все запросы
   - Отслеживать качество ответов LLM
   - Следить за распределением confidence_level (должно быть больше "medium" и "high")

4. **Оптимизировать параметры агрессивности**
   - **EDGE_GAIN** (default 2.5): увеличить для более агрессивных позиций
   - **EDGE_GAMMA** (default 0.7): уменьшить для более линейного роста
   - **BASE_K** (default 0.5): увеличить до 0.6-0.7 если позиции слишком малы
   - **k_max** (default 2.0): максимальный мультипликатор
   - Настроить risk throttling (liquidity_risk, news_risk)

## Дополнительная информация

- [OLLAMA_SETUP.md](OLLAMA_SETUP.md) - настройка Ollama
- [market_snapshot.py](market_snapshot.py) - сбор данных
- [position_sizing.py](position_sizing.py) - расчет позиций
- [llm_infra/](llm_infra/) - LLM инфраструктура
