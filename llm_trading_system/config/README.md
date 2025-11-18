# Unified Configuration Service

Этот пакет предоставляет единый сервис для управления конфигурацией проекта LLM Trading System.

## Обзор

Вместо разрозненных вызовов `os.getenv()` по всему коду, теперь используется централизованный объект `AppConfig`, который:

- **Типобезопасен** - использует Pydantic модели с валидацией
- **Персистентен** - автоматически сохраняется в `~/.llm_trading/config.json`
- **Кэшируется** - загружается один раз за процесс
- **Обратносовместим** - при первом запуске создается из переменных окружения

## Структура конфигурации

```python
AppConfig
├── api: ApiConfig           # API endpoints и ключи
├── llm: LlmConfig           # Настройки LLM провайдера
├── market: MarketConfig     # Параметры рыночных данных
├── risk: RiskConfig         # Управление рисками
├── exchange: ExchangeConfig # Настройки биржи
└── ui: UiDefaultsConfig     # Дефолты для UI
```

## Использование

### Базовое использование

```python
from llm_trading_system.config import load_config

# Загрузка конфигурации
cfg = load_config()

# Доступ к настройкам
print(cfg.api.newsapi_key)
print(cfg.llm.default_model)
print(cfg.market.base_asset)
print(cfg.risk.k_max)
```

### Изменение и сохранение

```python
from llm_trading_system.config import load_config, save_config

# Загрузка
cfg = load_config()

# Изменение
cfg.llm.temperature = 0.2
cfg.llm.default_model = "llama3.2"
cfg.risk.k_max = 3.0

# Сохранение
save_config(cfg)
```

### Перезагрузка после внешних изменений

```python
from llm_trading_system.config import reload_config

# Перезагрузить конфиг из файла (игнорируя кэш)
cfg = reload_config()
```

### Получение пути к файлу конфигурации

```python
from llm_trading_system.config import get_config_path

config_path = get_config_path()
print(f"Config file: {config_path}")  # ~/.llm_trading/config.json
```

## Секции конфигурации

### ApiConfig

Эндпоинты API и учетные данные:

```python
cfg.api.newsapi_key            # NewsAPI ключ
cfg.api.newsapi_base_url       # NewsAPI URL
cfg.api.cryptopanic_api_key    # CryptoPanic ключ
cfg.api.coinmetrics_base_url   # CoinMetrics URL
cfg.api.binance_base_url       # Binance Spot URL
cfg.api.binance_fapi_url       # Binance Futures URL
```

### LlmConfig

Настройки LLM провайдера:

```python
cfg.llm.llm_provider      # "ollama" | "openai" | "router"
cfg.llm.default_model     # Имя модели по умолчанию
cfg.llm.ollama_base_url   # URL Ollama сервера
cfg.llm.temperature       # Температура сэмплирования (0.0-2.0)
cfg.llm.timeout_seconds   # Таймаут запроса
```

### MarketConfig

Конфигурация рыночных данных:

```python
cfg.market.base_asset      # Торговый символ (BTCUSDT)
cfg.market.horizon_hours   # Горизонт прогноза (часы)
cfg.market.use_news        # Использовать новости
cfg.market.use_onchain     # Использовать on-chain метрики
cfg.market.use_funding     # Использовать funding rates
```

### RiskConfig

Параметры управления рисками:

```python
cfg.risk.base_long_size   # Базовый размер long позиции (0.0-1.0)
cfg.risk.base_short_size  # Базовый размер short позиции (0.0-1.0)
cfg.risk.k_max            # Максимальный множитель позиции
cfg.risk.edge_gain        # Усиление края (2.5)
cfg.risk.edge_gamma       # Нелинейное сжатие (0.7)
cfg.risk.base_k           # Базовый множитель для нейтрального режима (0.5)
```

### ExchangeConfig

Настройки подключения к бирже:

```python
cfg.exchange.exchange_name        # Имя биржи
cfg.exchange.api_key              # API ключ
cfg.exchange.api_secret           # API секрет
cfg.exchange.use_testnet          # Использовать testnet
cfg.exchange.live_trading_enabled # Флаг live торговли
cfg.exchange.default_symbol       # Символ по умолчанию
cfg.exchange.default_timeframe    # Таймфрейм по умолчанию
```

### UiDefaultsConfig

Дефолтные значения для UI:

```python
cfg.ui.default_initial_deposit  # Начальный депозит
cfg.ui.default_backtest_equity  # Капитал для бэктеста
cfg.ui.default_commission       # Комиссия (%)
cfg.ui.default_slippage         # Проскальзывание (%)
```

## Приоритет загрузки

1. **Кэш в памяти** - если конфиг уже загружен в текущем процессе
2. **Файл config.json** - если существует `~/.llm_trading/config.json`
3. **Переменные окружения** - если файла нет, создается из `.env` и сохраняется

## Переменные окружения

При первом запуске конфиг создается из следующих переменных окружения:

**API:**
- `NEWSAPI_KEY`, `NEWSAPI_BASE_URL`
- `CRYPTOPANIC_API_KEY`, `CRYPTOPANIC_BASE_URL`
- `BINANCE_BASE_URL`, `BINANCE_FAPI_URL`
- `COINMETRICS_BASE_URL`, `BLOCKCHAIN_COM_BASE_URL`

**LLM:**
- `LLM_PROVIDER`, `DEFAULT_OLLAMA_MODEL`
- `OLLAMA_BASE_URL`
- `OPENAI_API_BASE`, `OPENAI_API_KEY`
- `LLM_TEMPERATURE`, `LLM_TIMEOUT_SECONDS`

**Market:**
- `BASE_ASSET`, `HORIZON_HOURS`
- `USE_NEWS`, `USE_ONCHAIN`, `USE_FUNDING`

**Risk:**
- `BASE_LONG_SIZE`, `BASE_SHORT_SIZE`
- `K_MAX`, `EDGE_GAIN`, `EDGE_GAMMA`, `BASE_K`

**Exchange:**
- `EXCHANGE_NAME`
- `EXCHANGE_API_KEY`, `EXCHANGE_API_SECRET`
- `EXCHANGE_USE_TESTNET`, `EXCHANGE_LIVE_ENABLED`
- `DEFAULT_SYMBOL`, `DEFAULT_TIMEFRAME`

**UI:**
- `DEFAULT_INITIAL_DEPOSIT`, `DEFAULT_BACKTEST_EQUITY`
- `DEFAULT_COMMISSION`, `DEFAULT_SLIPPAGE`

## Интеграция с существующим кодом

### market_snapshot.py

Функция `load_settings()` теперь использует AppConfig:

```python
from llm_trading_system.core.market_snapshot import load_settings

settings = load_settings()  # Внутренне использует load_config()
```

### full_cycle_cli.py

CLI использует AppConfig для настроек LLM и риск-менеджмента:

```python
from llm_trading_system.config import load_config

cfg = load_config()

# Используются значения из конфига
model = cfg.llm.default_model
base_url = cfg.llm.ollama_base_url
temperature = cfg.llm.temperature
base_size = cfg.risk.base_long_size
k_max = cfg.risk.k_max
```

## Файл конфигурации

Формат: `~/.llm_trading/config.json`

```json
{
  "api": {
    "newsapi_key": null,
    "newsapi_base_url": "https://newsapi.org/v2",
    "cryptopanic_api_key": null,
    "cryptopanic_base_url": "https://cryptopanic.com/api/v1",
    "coinmetrics_base_url": "https://community-api.coinmetrics.io/v4",
    "blockchain_com_base_url": "https://api.blockchain.info",
    "binance_base_url": "https://api.binance.com",
    "binance_fapi_url": "https://fapi.binance.com"
  },
  "llm": {
    "llm_provider": "ollama",
    "default_model": "llama3.2",
    "ollama_base_url": "http://localhost:11434",
    "openai_api_base": null,
    "openai_api_key": null,
    "temperature": 0.1,
    "timeout_seconds": 60
  },
  "market": {
    "base_asset": "BTCUSDT",
    "horizon_hours": 4,
    "use_news": true,
    "use_onchain": true,
    "use_funding": true
  },
  "risk": {
    "base_long_size": 0.01,
    "base_short_size": 0.01,
    "k_max": 2.0,
    "edge_gain": 2.5,
    "edge_gamma": 0.7,
    "base_k": 0.5
  },
  "exchange": {
    "exchange_name": "binance",
    "api_key": null,
    "api_secret": null,
    "use_testnet": true,
    "live_trading_enabled": false,
    "default_symbol": "BTCUSDT",
    "default_timeframe": "5m"
  },
  "ui": {
    "default_initial_deposit": 1000.0,
    "default_backtest_equity": 1000.0,
    "default_commission": 0.04,
    "default_slippage": 0.0
  }
}
```

## Преимущества

1. **Единый источник истины** - вся конфигурация в одном месте
2. **Типобезопасность** - Pydantic валидация на лету
3. **Персистентность** - конфиг сохраняется между запусками
4. **Простота изменения** - можно редактировать JSON файл напрямую
5. **Обратная совместимость** - старый код продолжает работать
6. **Кэширование** - производительность (один раз за процесс)

## Миграция

Старый код с `os.getenv()` продолжит работать через обратную совместимость в `load_settings()`.

Для нового кода рекомендуется использовать напрямую:

```python
from llm_trading_system.config import load_config

cfg = load_config()
# Используйте cfg вместо os.getenv()
```
