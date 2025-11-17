# LLM Trading System - Торговая система с индикаторами и LLM

Полнофункциональная торговая система для бэктестинга стратегий на основе технических индикаторов с опциональной интеграцией LLM (Large Language Model).

## 🚀 Возможности

### Технические индикаторы
- **EMA/SMA** - Экспоненциальная и простая скользящие средние
- **RSI** - Индекс относительной силы с зонами перекупленности/перепроданности
- **MACD** - Схождение/расхождение скользящих средних
- **Bollinger Bands** - Полосы Боллинджера
- **ATR** - Average True Range для управления рисками
- **ADX** - Average Directional Index для определения силы тренда

### Три режима работы стратегий
- **QUANT_ONLY** - Только технические индикаторы (без LLM)
- **LLM_ONLY** - Только сигналы LLM на основе анализа рынка
- **HYBRID** - Комбинированный режим: индикаторы + LLM-фильтрация

### Декларативный движок правил
- JSON-конфигурация торговых правил
- Операторы: `>`, `<`, `>=`, `<=`, `==`, `cross_above`, `cross_below`
- Раздельные правила для входа/выхода по long/short позициям
- Полная сериализация в JSON

### Система бэктестинга
- CSV-данные с OHLCV барами
- Реалистичная симуляция сделок с комиссиями и проскальзыванием
- Детальная статистика: P&L, макс. просадка, win rate, equity curve
- Потоковая обработка без загрузки всех данных в память

### HTTP JSON API
- RESTful API на FastAPI
- CRUD операции для стратегий
- Запуск бэктестов через API
- Автоматическая документация Swagger/ReDoc

### Web UI
- Интуитивный веб-интерфейс для управления стратегиями
- Визуальный редактор параметров индикаторов
- Форма настройки бэктеста
- График equity curve в результатах
- Адаптивный дизайн (mobile-friendly)

### CLI инструменты
- Запуск бэктестов из командной строки
- JSON-конфигурация стратегий
- Интеграция с LLM через Ollama

## 📋 Требования

### Для запуска без Docker
- Python 3.12+
- pip
- (Опционально) Ollama для LLM режима

### Для запуска с Docker
- Docker >= 20.10
- Docker Compose >= 2.0

## 🔧 Установка и запуск

### Вариант 1: Запуск без Docker

#### 1. Клонирование репозитория

```bash
git clone https://github.com/Lje3apb/LLM_traiding_system.git
cd LLM_traiding_system
```

#### 2. Создание виртуального окружения

```bash
# Создать виртуальное окружение
python3.12 -m venv venv

# Активировать (Linux/Mac)
source venv/bin/activate

# Активировать (Windows)
venv\Scripts\activate
```

#### 3. Установка зависимостей

```bash
pip install -r requirements.txt
```

#### 4. Настройка конфигурации (опционально)

```bash
# Скопировать пример конфигурации
cp .env.example .env

# Отредактировать .env файл (опционально добавить API ключи для LLM режима)
nano .env
```

#### 5. Запуск

##### A. Запуск Web UI (рекомендуется для начинающих)

```bash
# Запустить FastAPI сервер с Web UI
python -m llm_trading_system.api.server

# Открыть в браузере:
# http://localhost:8000/ui/          - Web интерфейс
# http://localhost:8000/docs         - API документация Swagger
# http://localhost:8000/redoc        - API документация ReDoc
```

**Web UI позволяет:**
- Создавать и редактировать стратегии через визуальный интерфейс
- Настраивать все параметры индикаторов (EMA, RSI, ATR и т.д.)
- Запускать бэктесты с кастомными параметрами
- Просматривать результаты с графиками equity curve

##### B. Запуск бэктеста через CLI

```bash
# Пример: бэктест стратегии EMA crossover
python -m llm_trading_system.cli.backtest_strategy \
    --config examples/ema_crossover.json \
    --data data/BTCUSDT_1h.csv \
    --initial-equity 10000 \
    --fee-rate 0.001

# С использованием LLM (требуется Ollama)
python -m llm_trading_system.cli.backtest_strategy \
    --config examples/hybrid_strategy.json \
    --data data/BTCUSDT_1h.csv \
    --use-llm \
    --llm-model llama3.2 \
    --llm-url http://localhost:11434
```

##### C. Запуск тестов

```bash
# Запустить все тесты
python -m pytest tests/ -v

# Запустить только тесты индикаторов
python -m pytest tests/test_indicators.py -v

# Запустить только API тесты
python -m pytest tests/test_api_smoke.py tests/test_ui_smoke.py -v
```

### Вариант 2: Запуск с Docker

#### 1. Клонирование репозитория

```bash
git clone https://github.com/Lje3apb/LLM_traiding_system.git
cd LLM_traiding_system
```

#### 2. Настройка конфигурации

```bash
# Скопировать пример конфигурации
cp .env.example .env

# Отредактировать .env при необходимости
nano .env
```

#### 3. Запуск с Docker Compose

##### A. Запуск Web UI и API сервера

```bash
# Собрать образ и запустить API сервер
docker-compose build
docker-compose run --rm -p 8000:8000 llm-trading python -m llm_trading_system.api.server

# Открыть в браузере:
# http://localhost:8000/ui/    - Web интерфейс
# http://localhost:8000/docs   - API документация
```

##### B. Запуск бэктеста через Docker

```bash
# Запустить бэктест с конфигом из файла
docker-compose run --rm llm-trading \
    python -m llm_trading_system.cli.backtest_strategy \
    --config examples/ema_crossover.json \
    --data data/BTCUSDT_1h.csv
```

##### C. Запуск тестов

```bash
# Запустить все тесты
docker-compose --profile test up test

# Посмотреть результаты
docker-compose logs test
```

##### D. Интерактивный режим для разработки

```bash
# Запустить контейнер в интерактивном режиме
docker-compose run --rm llm-trading bash

# Внутри контейнера можно запускать любые команды:
python -m pytest tests/ -v
python -m llm_trading_system.api.server
```

## 📁 Структура проекта

```
LLM_traiding_system/
├── llm_trading_system/          # Основной пакет
│   ├── api/                     # HTTP API и Web UI
│   │   ├── server.py            # FastAPI сервер
│   │   ├── templates/           # HTML шаблоны (Jinja2)
│   │   │   ├── base.html
│   │   │   ├── index.html
│   │   │   ├── strategy_form.html
│   │   │   ├── backtest_form.html
│   │   │   └── backtest_result.html
│   │   └── static/              # CSS стили
│   │       └── style.css
│   ├── cli/                     # CLI инструменты
│   │   └── backtest_strategy.py # Запуск бэктестов
│   ├── core/                    # Базовая логика
│   │   ├── position_sizing.py   # LLM position sizing
│   │   └── market_snapshot.py   # Сбор рыночных данных
│   ├── engine/                  # Движок бэктестинга
│   │   ├── backtester.py        # Основной бэктестер
│   │   ├── backtest_service.py  # Сервисный слой
│   │   └── data_feed.py         # Чтение CSV данных
│   ├── indicators/              # Технические индикаторы
│   │   ├── __init__.py
│   │   └── indicators.py        # EMA, RSI, MACD, BB, ATR, ADX
│   └── strategies/              # Торговые стратегии
│       ├── configs.py           # Конфигурация стратегий
│       ├── factory.py           # Фабрика стратегий
│       ├── storage.py           # Хранение конфигов
│       ├── rules.py             # Движок правил
│       ├── indicator_strategy.py # Стратегия на индикаторах
│       └── combined_strategy.py  # Гибридная стратегия
├── tests/                       # Тесты
│   ├── test_indicators.py       # Тесты индикаторов
│   ├── test_combined_strategy.py
│   ├── test_backtest_from_config.py
│   ├── test_api_smoke.py        # API smoke tests
│   └── test_ui_smoke.py         # UI smoke tests
├── examples/                    # Примеры конфигураций
│   ├── ema_crossover.json
│   └── hybrid_strategy.json
├── strategies_configs/          # Сохраненные стратегии (создается автоматически)
├── data/                        # CSV данные для бэктестов
├── Dockerfile                   # Docker образ
├── docker-compose.yml           # Docker Compose конфигурация
├── requirements.txt             # Python зависимости
├── .env.example                # Пример конфигурации
├── PROJECT_STRUCTURE.md         # Детальная документация проекта
└── README.md                   # Этот файл
```

## 🎯 Быстрый старт: Создание первой стратегии

### Через Web UI

1. Запустите сервер:
   ```bash
   python -m llm_trading_system.api.server
   ```

2. Откройте браузер: http://localhost:8000/ui/

3. Нажмите "Create New Strategy"

4. Заполните форму:
   - **Name**: my_first_strategy
   - **Mode**: Quant Only (только индикаторы)
   - **Symbol**: BTCUSDT
   - **Indicator Parameters**: настройте EMA fast=12, slow=26
   - **Rules**: задайте правила входа/выхода

5. Сохраните стратегию

6. Нажмите "Run Backtest" и укажите путь к CSV файлу

### Через JSON конфигурацию

Создайте файл `my_strategy.json`:

```json
{
  "strategy_type": "indicator",
  "mode": "quant_only",
  "symbol": "BTCUSDT",
  "base_size": 0.1,
  "allow_long": true,
  "allow_short": false,
  "ema_fast_len": 12,
  "ema_slow_len": 26,
  "rsi_len": 14,
  "rsi_ovb": 70,
  "rsi_ovs": 30,
  "rules": {
    "long_entry": [
      {"left": "ema_fast", "op": "cross_above", "right": "ema_slow"},
      {"left": "rsi", "op": "<", "right": 70}
    ],
    "long_exit": [
      {"left": "ema_fast", "op": "cross_below", "right": "ema_slow"}
    ],
    "short_entry": [],
    "short_exit": []
  }
}
```

Запустите бэктест:

```bash
python -m llm_trading_system.cli.backtest_strategy \
    --config my_strategy.json \
    --data data/BTCUSDT_1h.csv
```

## 📊 HTTP API

### Основные endpoints

```bash
# Health check
curl http://localhost:8000/health

# Получить список стратегий
curl http://localhost:8000/strategies

# Получить конкретную стратегию
curl http://localhost:8000/strategies/my_strategy

# Создать/обновить стратегию
curl -X POST http://localhost:8000/strategies/my_strategy \
  -H "Content-Type: application/json" \
  -d @my_strategy.json

# Удалить стратегию
curl -X DELETE http://localhost:8000/strategies/my_strategy

# Запустить бэктест
curl -X POST http://localhost:8000/backtest \
  -H "Content-Type: application/json" \
  -d '{
    "config": {...},
    "data_path": "data/BTCUSDT_1h.csv",
    "use_llm": false,
    "initial_equity": 10000.0,
    "fee_rate": 0.001,
    "slippage_bps": 1.0
  }'
```

### API Документация

После запуска сервера доступна по адресам:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## 🔬 Примеры использования

### 1. Простая EMA Crossover стратегия

```python
from llm_trading_system.strategies.factory import create_strategy_from_config
from llm_trading_system.strategies.configs import IndicatorStrategyConfig

# Создать конфигурацию
config = IndicatorStrategyConfig(
    symbol="BTCUSDT",
    mode="quant_only",
    ema_fast_len=12,
    ema_slow_len=26,
    base_size=0.1,
    rules={
        "long_entry": [{"left": "ema_fast", "op": "cross_above", "right": "ema_slow"}],
        "long_exit": [{"left": "ema_fast", "op": "cross_below", "right": "ema_slow"}],
        "short_entry": [],
        "short_exit": []
    }
)

# Создать стратегию
strategy = create_strategy_from_config(config.to_dict())

# Использовать в бэктесте
from llm_trading_system.engine.backtester import Backtester

bt = Backtester(
    strategy=strategy,
    data_path="data/BTCUSDT_1h.csv",
    initial_equity=10000.0
)

summary = bt.run()
print(f"Total P&L: {summary['pnl_pct']:.2f}%")
print(f"Max Drawdown: {summary['max_drawdown']:.2f}%")
print(f"Win Rate: {summary['win_rate']:.1f}%")
```

### 2. RSI Mean Reversion стратегия

```json
{
  "strategy_type": "indicator",
  "mode": "quant_only",
  "symbol": "BTCUSDT",
  "base_size": 0.15,
  "rsi_len": 14,
  "rsi_ovb": 70,
  "rsi_ovs": 30,
  "rules": {
    "long_entry": [
      {"left": "rsi", "op": "<", "right": 30}
    ],
    "long_exit": [
      {"left": "rsi", "op": ">", "right": 50}
    ],
    "short_entry": [
      {"left": "rsi", "op": ">", "right": 70}
    ],
    "short_exit": [
      {"left": "rsi", "op": "<", "right": 50}
    ]
  }
}
```

### 3. Гибридная стратегия с LLM

```json
{
  "strategy_type": "combined",
  "mode": "hybrid",
  "symbol": "BTCUSDT",
  "base_size": 0.1,
  "k_max": 2.0,
  "llm_horizon_hours": 24,
  "llm_min_prob_edge": 0.55,
  "llm_min_trend_strength": 0.6,
  "llm_refresh_interval_bars": 60,
  "ema_fast_len": 12,
  "ema_slow_len": 26,
  "rules": {
    "long_entry": [
      {"left": "ema_fast", "op": "cross_above", "right": "ema_slow"}
    ],
    "long_exit": [
      {"left": "ema_fast", "op": "cross_below", "right": "ema_slow"}
    ],
    "short_entry": [],
    "short_exit": []
  }
}
```

Запуск с LLM:

```bash
# Убедитесь, что Ollama запущен
ollama serve

# Запустите бэктест с LLM
python -m llm_trading_system.cli.backtest_strategy \
    --config hybrid_strategy.json \
    --data data/BTCUSDT_1h.csv \
    --use-llm \
    --llm-model llama3.2
```

## 🧪 Тестирование

```bash
# Запустить все тесты
python -m pytest tests/ -v

# Запустить с покрытием
python -m pytest tests/ --cov=llm_trading_system --cov-report=html

# Запустить конкретный тест
python -m pytest tests/test_indicators.py::test_ema_calculation -v
```

### Статистика тестов

- **Индикаторы**: 10+ тестов (EMA, RSI, MACD, Bollinger Bands, ATR, ADX)
- **Стратегии**: 8+ тестов (правила, кросс-детекция, HYBRID режим)
- **API**: 8 smoke tests (CRUD операции, бэктесты)
- **UI**: 6 smoke tests (формы, навигация, результаты)

**Всего**: 30+ тестов, все проходят ✅

## 🔄 Формат данных

### CSV файл с OHLCV данными

```csv
timestamp,open,high,low,close,volume
1609459200000,28923.63,29600.00,28802.26,29374.77,50234.5
1609462800000,29374.77,29580.00,29101.00,29225.61,42156.3
1609466400000,29225.61,29450.00,28850.00,28994.52,48923.1
...
```

**Требования:**
- Timestamp в миллисекундах (Unix time)
- Колонки: timestamp, open, high, low, close, volume
- CSV с заголовком
- Данные отсортированы по времени (возрастание)

## 🐛 Troubleshooting

### Web UI не открывается

```bash
# Проверьте, что сервер запущен
python -m llm_trading_system.api.server

# Проверьте логи на ошибки
# Убедитесь, что порт 8000 не занят другим приложением
lsof -i :8000  # Linux/Mac
netstat -ano | findstr :8000  # Windows
```

### Ошибка "Module not found"

```bash
# Убедитесь, что вы в правильной директории
pwd
# Должно быть: /path/to/LLM_traiding_system

# Убедитесь, что виртуальное окружение активировано
which python  # Должно показать путь к venv/bin/python

# Переустановите зависимости
pip install -r requirements.txt
```

### Тесты падают

```bash
# Установите pytest, если его нет
pip install pytest

# Запустите тесты с подробным выводом
python -m pytest tests/ -v -s

# Проверьте конкретный тест
python -m pytest tests/test_indicators.py -v
```

### Docker контейнер не запускается

```bash
# Проверьте логи
docker-compose logs llm-trading

# Пересоберите образ
docker-compose build --no-cache

# Проверьте, что .env файл существует
ls -la .env
```

### LLM режим не работает

```bash
# Убедитесь, что Ollama запущен
curl http://localhost:11434/api/version

# Проверьте, что модель загружена
ollama list

# Загрузите модель, если нужно
ollama pull llama3.2

# Проверьте подключение в логах
python -m llm_trading_system.cli.backtest_strategy \
    --config hybrid.json \
    --data data/BTCUSDT_1h.csv \
    --use-llm \
    --llm-model llama3.2 \
    --llm-url http://localhost:11434
```

## 🛡️ Безопасность

- ✅ Все данные локальные, ничего не отправляется в облако
- ✅ API ключи в `.env` (не коммитятся в git)
- ✅ Docker контейнеры запускаются от непривилегированного пользователя
- ✅ Валидация всех входных данных
- ✅ Защита от SQL injection (не используется SQL)
- ✅ CORS настраивается в FastAPI при необходимости

## 📈 Production Deployment

### Запуск API сервера в продакшене

```bash
# С uvicorn напрямую
uvicorn llm_trading_system.api.server:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 4 \
    --log-level info

# С Docker
docker-compose up -d llm-trading
docker-compose exec llm-trading \
    uvicorn llm_trading_system.api.server:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 4
```

### Рекомендации для продакшена

1. **Используйте reverse proxy** (nginx, Caddy)
2. **Включите HTTPS** с Let's Encrypt
3. **Настройте логирование** в файл
4. **Мониторинг** с Prometheus/Grafana
5. **Backup** стратегий и данных
6. **Rate limiting** для API endpoints
7. **Аутентификация** для Web UI (если нужно)

## 📝 Лицензия

См. файл [LICENSE](LICENSE)

## 🤝 Вклад в проект

Pull requests приветствуются! Для значительных изменений сначала откройте issue для обсуждения.

### Как внести вклад

1. Fork репозитория
2. Создайте feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit изменений (`git commit -m 'Add some AmazingFeature'`)
4. Push в branch (`git push origin feature/AmazingFeature`)
5. Откройте Pull Request

## 📧 Контакты

- GitHub: [@Lje3apb](https://github.com/Lje3apb)
- Issues: [GitHub Issues](https://github.com/Lje3apb/LLM_traiding_system/issues)

## 🙏 Благодарности

- **FastAPI** - за отличный веб-фреймворк
- **Jinja2** - за мощный шаблонизатор
- **Ollama** - за локальный LLM inference
- **Python Community** - за экосистему инструментов

---

**⚠️ Disclaimer**: Эта система предназначена только для образовательных и исследовательских целей. Используйте на свой страх и риск. Автор не несёт ответственности за финансовые потери при использовании данной системы в реальной торговле.

**Бэктест результаты не гарантируют будущую прибыльность.**
