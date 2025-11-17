# Руководство по индикаторным стратегиям

## Содержание

1. [Обзор архитектуры стратегий](#1-обзор-архитектуры-стратегий)
2. [Библиотека индикаторов](#2-библиотека-индикаторов)
3. [Формат JSON-правил (Trading Rules)](#3-формат-json-правил-trading-rules)
4. [Пример: перенос стратегии из TradingView (Pine Script)](#4-пример-перенос-стратегии-из-tradingview-pine-script)
5. [Как добавить новую стратегию](#5-как-добавить-новую-стратегию)
6. [Совместное использование с LLM-режимом](#6-совместное-использование-с-llm-режимом)

---

## 1. Обзор архитектуры стратегий

Система поддерживает три основных уровня торговых стратегий:

### 1.1 LLM-режимы (llm_regime_strategy.py, regime_engine.py)

**Назначение**: Определение "ветра рынка" с помощью больших языковых моделей.

- Анализирует рыночные снимки (market snapshots) с помощью LLM
- Выдает вероятности бычьего/медвежьего режима: `prob_bull`, `prob_bear`
- Вычисляет коэффициенты размера позиции: `k_long`, `k_short`
- Может работать самостоятельно или влиять на размер позиций индикаторных стратегий

**Файлы**:
- `llm_trading_system/core/regime_engine.py` — логика определения режима
- `llm_trading_system/strategies/llm_regime_strategy.py` — стратегия на основе LLM

### 1.2 Индикаторные стратегии (indicator_strategy.py, indicators.py)

**Назначение**: Чистая механика по ценам и объемам (технический анализ).

- Использует технические индикаторы (RSI, SMA, EMA, Bollinger Bands, ATR и др.)
- Определяет условия входа/выхода через декларативные JSON-правила
- Поддерживает пирамидинг (pyramiding) и мартингейл
- Поддерживает Take Profit / Stop Loss
- Поддерживает временные фильтры (торговля в определённые часы)

**Файлы**:
- `llm_trading_system/strategies/indicator_strategy.py` — основная логика стратегии
- `llm_trading_system/strategies/indicators.py` — библиотека индикаторов
- `llm_trading_system/strategies/rules.py` — движок правил (DSL)
- `llm_trading_system/strategies/configs.py` — конфигурация стратегий

### 1.3 Backtester и портфель (backtester.py, portfolio.py)

**Назначение**: Исполнение сделок и расчёт результатов.

- `backtester.py` — запускает стратегию на исторических данных
- `portfolio.py` — симулирует выполнение ордеров, ведёт учёт позиций и эквити
- Учитывает комиссии, проскальзывание (slippage)
- Возвращает кривую капитала, список сделок, итоговую доходность и максимальную просадку

**Файлы**:
- `llm_trading_system/engine/backtester.py`
- `llm_trading_system/engine/portfolio.py`
- `llm_trading_system/engine/data_feed.py`

### 1.4 Как они взаимодействуют

```
┌─────────────────────────────────────────────────────────────┐
│                     ДАННЫЕ (data_feed)                      │
│              OHLCV bars → Backtester                        │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                   СТРАТЕГИЯ (Strategy)                      │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  LLM Режим (опционально)                             │  │
│  │  • Анализ рынка через LLM                            │  │
│  │  • Коэффициенты k_long, k_short                      │  │
│  └───────────────────────────────────────────────────────┘  │
│                       ↓ (опционально)                       │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Индикаторная стратегия                              │  │
│  │  • Вычисляет индикаторы (RSI, BB, SMA, vol_ma...)    │  │
│  │  • Проверяет JSON-правила входа/выхода               │  │
│  │  • Проверяет TP/SL, временные фильтры                │  │
│  │  • Применяет пирамидинг и мартингейл                  │  │
│  └───────────────────────────────────────────────────────┘  │
│                              ↓                              │
│                   Генерирует Order                          │
│              (long/short/flat + size)                       │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│               ПОРТФЕЛЬ (PortfolioSimulator)                 │
│  • Исполняет ордера                                         │
│  • Отслеживает позицию, эквити, сделки                      │
│  • Учитывает комиссии и проскальзывание                     │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                  РЕЗУЛЬТАТЫ (BacktestResult)                │
│  • Кривая капитала                                          │
│  • Список сделок                                            │
│  • Итоговая доходность, максимальная просадка               │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Библиотека индикаторов

### 2.1 Расположение

Все индикаторы находятся в модуле:
```
llm_trading_system/strategies/indicators.py
```

### 2.2 Реализованные индикаторы

#### SMA (Simple Moving Average)

```python
def sma(values: Sequence[float], length: int) -> float | None
```

**Параметры**:
- `values` — список цен (от старых к новым)
- `length` — период скользящей средней

**Возвращает**: значение SMA или `None`, если недостаточно данных.

**Пример использования в конфиге**:
```json
{
  "ema_fast_len": 50,
  "ema_slow_len": 200
}
```

#### EMA (Exponential Moving Average)

```python
def ema(values: Sequence[float], length: int) -> float | None
```

**Параметры**:
- `values` — список цен
- `length` — период EMA

**Возвращает**: значение EMA или `None`.

#### RSI (Relative Strength Index)

```python
def rsi(values: Sequence[float], length: int = 14) -> float | None
```

**Параметры**:
- `values` — список цен закрытия
- `length` — период RSI (по умолчанию 14)

**Возвращает**: значение RSI (0-100) или `None`.

**Пример в конфиге**:
```json
{
  "rsi_len": 14,
  "rsi_ovb": 70,
  "rsi_ovs": 30
}
```

#### Bollinger Bands

```python
def bollinger(
    values: Sequence[float],
    length: int = 20,
    mult: float = 2.0
) -> tuple[float | None, float | None, float | None]
```

**Параметры**:
- `values` — список цен
- `length` — период для скользящей средней
- `mult` — множитель стандартного отклонения

**Возвращает**: кортеж `(middle, upper, lower)` или `(None, None, None)`.

**Доступные индикаторы в правилах**:
- `bb_middle` или `bb_basis` — средняя линия (SMA)
- `bb_upper`, `upper_bb`, `upperBB` — верхняя полоса (три алиаса)
- `bb_lower`, `lower_bb`, `lowerBB` — нижняя полоса (три алиаса)

**Пример в конфиге**:
```json
{
  "bb_len": 20,
  "bb_mult": 2.0
}
```

#### ATR (Average True Range)

```python
def atr(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    length: int = 14
) -> float | None
```

**Параметры**:
- `highs` — список максимумов
- `lows` — список минимумов
- `closes` — список цен закрытия
- `length` — период ATR

**Возвращает**: значение ATR или `None`.

**Пример в конфиге**:
```json
{
  "atr_len": 14,
  "atr_stop_mult": 1.5,
  "atr_tp_mult": 2.8
}
```

#### Volume MA (SMA по объёму)

Вычисляется автоматически как `sma(volume, vol_ma_len)`.

**Доступные индикаторы**:
- `vol_ma` — SMA объёма
- `vol_ma_scaled` или `vol_threshold` — `vol_ma * vol_mult` (для фильтров объёма, два алиаса)

**Пример в конфиге**:
```json
{
  "vol_ma_len": 21,
  "vol_mult": 0.5
}
```

### 2.3 Доступные поля в правилах

Помимо индикаторов, в правилах можно использовать следующие поля текущего бара:

- `open` — цена открытия
- `high` — максимальная цена
- `low` — минимальная цена
- `close` — цена закрытия
- `volume` — объём
- `hour` — час бара (0-23) — полезно для временных фильтров

### 2.4 Полная таблица доступных индикаторов и алиасов

| Индикатор | Основное имя | Алиасы | Описание |
|-----------|--------------|--------|----------|
| RSI | `rsi` | — | Relative Strength Index (0-100) |
| SMA fast | `sma_fast` | — | SMA с периодом `ema_fast_len` |
| SMA slow | `sma_slow` | — | SMA с периодом `ema_slow_len` |
| EMA fast | `ema_fast` | — | EMA с периодом `ema_fast_len` |
| EMA slow | `ema_slow` | — | EMA с периодом `ema_slow_len` |
| BB middle | `bb_middle` | `bb_basis` | Средняя линия Bollinger Bands |
| BB upper | `bb_upper` | `upper_bb`, `upperBB` | Верхняя полоса Bollinger Bands |
| BB lower | `bb_lower` | `lower_bb`, `lowerBB` | Нижняя полоса Bollinger Bands |
| ATR | `atr` | — | Average True Range |
| Volume MA | `vol_ma` | — | SMA объёма с периодом `vol_ma_len` |
| Volume threshold | `vol_ma_scaled` | `vol_threshold` | `vol_ma * vol_mult` |
| OHLCV | `open`, `high`, `low`, `close`, `volume` | — | Текущие значения бара |
| Hour | `hour` | — | Час из timestamp (0-23) |

**Примечания**:
- Алиасы полностью взаимозаменяемы (например, `lowerBB` = `lower_bb` = `bb_lower`)
- Используйте тот вариант, который вам удобнее или привычнее (TradingView-style, snake_case и т.д.)

### 2.5 Как движок вычисляет индикаторы

1. **Данные от data_feed/backtester**: движок получает бары (OHLCV + timestamp) через интерфейс `Bar`.

2. **Накопление истории**: стратегия накапливает историю баров в буферах (`deque`) для каждого поля (close, high, low, volume).

3. **Вычисление индикаторов**: на каждом новом баре стратегия вызывает функции индикаторов из `indicators.py`.

4. **Результаты**: индикаторы возвращают одно значение (для текущего бара) или `None`, если недостаточно данных.

5. **Использование в правилах**: значения индикаторов доступны в словаре `indicators`, который передаётся в движок правил.

**Пример**:
```python
indicators = {
    "rsi": 25.3,
    "lowerBB": 50000.5,
    "upperBB": 52000.2,
    "vol_ma": 1500000,
    "vol_ma_scaled": 750000,  # vol_ma * 0.5
    "close": 51000,
    "volume": 2000000,
    "hour": 3.0
}
```

---

## 3. Формат JSON-правил (Trading Rules)

### 3.1 Обзор DSL (Domain Specific Language)

Система использует простой декларативный DSL для определения условий входа и выхода. Правила описываются в формате JSON и состоят из **условий** (Condition) и **групп правил** (RuleSet).

### 3.2 Структура условия (Condition)

Каждое условие имеет три поля:

```json
{
  "left": "название_индикатора_или_поля",
  "op": "оператор_сравнения",
  "right": "название_индикатора_или_число_или_выражение"
}
```

**Поле `left`**:
- Имя индикатора или поля: `"rsi"`, `"close"`, `"volume"`, `"lowerBB"`, `"hour"` и т.д.

**Поле `op`** (оператор):
- `"<"` — меньше
- `">"` — больше
- `"<="` — меньше или равно
- `">="` — больше или равно
- `"=="` — равно
- `"cross_above"` — пересечение снизу вверх (требует предыдущие значения)
- `"cross_below"` — пересечение сверху вниз

**Поле `right`**:
- Число: `30`, `22`, `80`, `0.5` и т.д.
- Имя индикатора: `"lowerBB"`, `"upperBB"`, `"ema_fast"` и т.д.
- Выражение: `"vol_ma * 0.5"`, `"atr * 2"`, `"bb_middle + 100"` и т.д.

### 3.3 Группы правил (RuleSet)

RuleSet состоит из четырёх списков условий:

```json
{
  "long_entry": [ /* условия для входа в лонг */ ],
  "short_entry": [ /* условия для входа в шорт */ ],
  "long_exit": [ /* условия для выхода из лонга */ ],
  "short_exit": [ /* условия для выхода из шорта */ ]
}
```

**Логика**:
- Все условия в списке объединяются через **логическое И** (AND).
- Если список пустой, сигнал считается `False` (нет входа/выхода).

### 3.4 Примеры условий

#### Простое сравнение с числом

```json
{
  "left": "rsi",
  "op": "<",
  "right": 30
}
```

Означает: `rsi < 30`

#### Сравнение индикаторов

```json
{
  "left": "close",
  "op": ">",
  "right": "bb_upper"
}
```

Означает: `close > bb_upper`

#### Сравнение с выражением

```json
{
  "left": "volume",
  "op": ">",
  "right": "vol_ma * 1.5"
}
```

Означает: `volume > (vol_ma * 1.5)`

#### Временной фильтр

```json
{
  "left": "hour",
  "op": ">=",
  "right": 0
}
```

Означает: `hour >= 0` (час >= 0)

#### Пересечение

```json
{
  "left": "ema_fast",
  "op": "cross_above",
  "right": "ema_slow"
}
```

Означает: EMA быстрая пересекла EMA медленную снизу вверх.

### 3.5 Пример полного RuleSet

```json
{
  "long_entry": [
    {"left": "rsi", "op": "<", "right": 30},
    {"left": "close", "op": "<=", "right": "lowerBB"},
    {"left": "volume", "op": ">", "right": "vol_ma * 1.2"}
  ],
  "short_entry": [
    {"left": "rsi", "op": ">", "right": 70},
    {"left": "close", "op": ">=", "right": "upperBB"}
  ],
  "long_exit": [
    {"left": "rsi", "op": ">", "right": 70}
  ],
  "short_exit": [
    {"left": "rsi", "op": "<", "right": 30}
  ]
}
```

**Логика**:
- **Вход в лонг**: RSI < 30 И цена <= нижняя полоса Боллинджера И объём > vol_ma * 1.2
- **Вход в шорт**: RSI > 70 И цена >= верхняя полоса Боллинджера
- **Выход из лонга**: RSI > 70
- **Выход из шорта**: RSI < 30

### 3.6 Как вставить JSON-правила в веб-интерфейс

В веб-интерфейсе создания стратегии есть поле **"Trading Rules"** (или **"Правила торговли"**).

1. Скопируйте JSON-конфиг правил (RuleSet).
2. Вставьте его в текстовое поле "Trading Rules".
3. Сохраните стратегию.

Система автоматически распарсит JSON и создаст объект `RuleSet`, который будет использоваться стратегией.

---

## 4. Пример: перенос стратегии из TradingView (Pine Script)

### 4.1 Исходная стратегия на Pine Script

```pinescript
//@version=5
strategy("ETH-5m ОХОТА НОЧНОГО КОТА САМУРАЯ", overlay=true,
     initial_capital=50,
     default_qty_type=strategy.percent_of_equity,
     default_qty_value=10, // 10% equity за 1-й вход
     pyramiding=4, // 4 ступени усреднения
     commission_value=0.04,
     margin_long=0,
     margin_short=0)

// --------------- Параметры ---------------
rsiPeriod = input.int(14, "RSI период")
bbLen = input.int(20, "Боллинджер")
bbMult = input.float(2.0, "BB отклонение")
tpLongPct = input.float(2.0, "TP long, %")
slLongPct = input.float(2.0, "SL long, %")
tpShPct = input.float(2.0, "TP short, %")
slShPct = input.float(2.0, "SL short, %")
volMult = input.float(0.5, "Объём > x SMA(20)")
mult = input.float(1.5, "Мартингейл-множитель")

// --------------- Индикаторы ---------------
rsi = ta.rsi(close, rsiPeriod)
basis = ta.sma(close, bbLen)
dev = bbMult * ta.stdev(close, bbLen)
lowerBB = basis - dev
upperBB = basis + dev
volMA = ta.sma(volume, 21)

// --------------- Фильтр времени (00-07) ---------------
inTime = (hour >= 0) and (hour <= 7)

// --------------- Условия входа ---------------
longCond = inTime and (rsi < 22) and (low <= lowerBB) and (volume > volMA * volMult)
shortCond = inTime and (rsi > 80) and (high >= upperBB) and (volume > volMA * volMult)

// --------------- Мартингейл-лот ---------------
step = strategy.closedtrades - strategy.opentrades
qty = math.pow(mult, step)

// --------------- Входы ---------------
if longCond and strategy.opentrades < 4
    strategy.entry("Lo", strategy.long, qty=qty)

if shortCond and strategy.opentrades < 4
    strategy.entry("Sh", strategy.short, qty=qty)

// --------------- Выходы (раздельные) ---------------
if strategy.opentrades > 0
    if strategy.position_size > 0
        strategy.exit("ExL", from_entry="Lo",
             limit=strategy.position_avg_price * (1 + tpLongPct/100),
             stop =strategy.position_avg_price * (1 - slLongPct/100))
    if strategy.position_size < 0
        strategy.exit("ExS", from_entry="Sh",
             limit=strategy.position_avg_price * (1 - tpShPct/100),
             stop =strategy.position_avg_price * (1 + slShPct/100))
```

### 4.2 Анализ стратегии

#### Параметры

| Pine Script | Значение | Назначение |
|-------------|----------|------------|
| `rsiPeriod` | 14 | Период RSI |
| `bbLen` | 20 | Период Bollinger Bands |
| `bbMult` | 2.0 | Множитель отклонения BB |
| `volMult` | 0.5 | Множитель для фильтра объёма |
| `tpLongPct` | 2.0 | Take Profit для лонга (%) |
| `slLongPct` | 2.0 | Stop Loss для лонга (%) |
| `tpShPct` | 2.0 | Take Profit для шорта (%) |
| `slShPct` | 2.0 | Stop Loss для шорта (%) |
| `pyramiding` | 4 | Максимум пирамидингов |
| `mult` | 1.5 | Мартингейл-множитель |
| `default_qty_value` | 10 | Базовый размер позиции (% от эквити) |

#### Индикаторы

| Pine | Индикатор | Параметры |
|------|-----------|-----------|
| `rsi` | RSI | period=14 |
| `basis`, `lowerBB`, `upperBB` | Bollinger Bands | length=20, mult=2.0 |
| `volMA` | SMA объёма | length=21 |

#### Временной фильтр

```pinescript
inTime = (hour >= 0) and (hour <= 7)
```

Торговля разрешена только с 00:00 до 07:00 (по бирже).

#### Условия входа

**Лонг**:
```pinescript
longCond = inTime and (rsi < 22) and (low <= lowerBB) and (volume > volMA * volMult)
```

**Шорт**:
```pinescript
shortCond = inTime and (rsi > 80) and (high >= upperBB) and (volume > volMA * volMult)
```

#### Логика пирамидинга и мартингейла

```pinescript
step = strategy.closedtrades - strategy.opentrades
qty = math.pow(mult, step)
```

- `step` = количество закрытых сделок - количество открытых сделок
- `qty` = `mult^step` (1, 1.5, 2.25, 3.375 и т.д.)

#### Take Profit / Stop Loss

- **Лонг**: TP = entry * (1 + tpLongPct/100), SL = entry * (1 - slLongPct/100)
- **Шорт**: TP = entry * (1 - tpShPct/100), SL = entry * (1 + slShPct/100)

### 4.3 Пошаговый перенос в систему

#### Шаг 1: Перенос параметров в конфигурацию

**Параметры индикаторов** → `indicator_params`:

```json
{
  "rsi_len": 14,
  "bb_len": 20,
  "bb_mult": 2.0,
  "vol_ma_len": 21,
  "vol_mult": 0.5
}
```

**Параметры риска** → `risk_params`:

```json
{
  "base_size": 0.10,
  "pyramiding": 4,
  "martingale_mult": 1.5,
  "tp_long_pct": 2.0,
  "sl_long_pct": 2.0,
  "tp_short_pct": 2.0,
  "sl_short_pct": 2.0,
  "use_tp_sl": true
}
```

**Временной фильтр** → `time_filter`:

```json
{
  "time_filter_enabled": true,
  "time_filter_start_hour": 0,
  "time_filter_end_hour": 7
}
```

#### Шаг 2: Перенос индикаторов

| Pine Script | Система | Доступные алиасы |
|-------------|---------|------------------|
| `rsi = ta.rsi(close, rsiPeriod)` | `indicators["rsi"]` | — |
| `basis = ta.sma(close, bbLen)` | `indicators["bb_middle"]` | `bb_basis` |
| `lowerBB = basis - dev` | `indicators["bb_lower"]` | `lower_bb`, `lowerBB` |
| `upperBB = basis + dev` | `indicators["bb_upper"]` | `upper_bb`, `upperBB` |
| `volMA = ta.sma(volume, 21)` | `indicators["vol_ma"]` | — |
| `volMA * volMult` | `indicators["vol_threshold"]` | `vol_ma_scaled` |
| `hour` | `indicators["hour"]` | — |
| `low`, `high`, `close`, `volume` | `indicators["low"]`, `indicators["high"]`, etc. | — |

**Примечания**:
- Все индикаторы вычисляются автоматически на основе параметров в конфигурации.
- Система предоставляет несколько алиасов для совместимости с разными стилями кодирования.
- `vol_threshold` — это предвычисленное значение `vol_ma * vol_mult`, чтобы не использовать выражения в правилах.

#### Шаг 3: Перенос условий входа в JSON-правила

**Исходное условие лонга**:
```pinescript
longCond = inTime and (rsi < 22) and (low <= lowerBB) and (volume > volMA * volMult)
```

**JSON-правила для лонга**:

```json
{
  "long_entry": [
    {"left": "hour", "op": ">=", "right": 0},
    {"left": "hour", "op": "<=", "right": 7},
    {"left": "rsi", "op": "<", "right": 22},
    {"left": "low", "op": "<=", "right": "lowerBB"},
    {"left": "volume", "op": ">", "right": "vol_ma * 0.5"}
  ]
}
```

**Исходное условие шорта**:
```pinescript
shortCond = inTime and (rsi > 80) and (high >= upperBB) and (volume > volMA * volMult)
```

**JSON-правила для шорта**:

```json
{
  "short_entry": [
    {"left": "hour", "op": ">=", "right": 0},
    {"left": "hour", "op": "<=", "right": 7},
    {"left": "rsi", "op": ">", "right": 80},
    {"left": "high", "op": ">=", "right": "upperBB"},
    {"left": "volume", "op": ">", "right": "vol_ma * 0.5"}
  ]
}
```

**Примечание**: Выражение `vol_ma * volMult` переносится как `"vol_ma * 0.5"` (система поддерживает простые арифметические выражения).

**Альтернативный вариант 1**: Можно использовать предвычисленный индикатор `vol_ma_scaled`:

```json
{"left": "volume", "op": ">", "right": "vol_ma_scaled"}
```

**Альтернативный вариант 2**: Можно использовать алиас `vol_threshold`:

```json
{"left": "volume", "op": ">", "right": "vol_threshold"}
```

Все три варианта эквивалентны. `vol_threshold` — это предвычисленное значение `vol_ma * vol_mult`.

#### Шаг 4: Перенос логики пирамидинга и мартингейла

В Pine Script стратегии часто используют динамическое изменение размера позиции в зависимости от количества закрытых и открытых сделок:

```pinescript
step = strategy.closedtrades - strategy.opentrades
qty = math.pow(mult, step)
```

В системе LLM Trading System эта логика **реализована автоматически** в методе `_calculate_position_size()` класса `IndicatorStrategy`.

##### Параметры управления позицией и мартингейлом

Система поддерживает следующие параметры для управления размером позиций (совместимые с TradingView):

**`base_position_pct`** (float, по умолчанию `10.0`)
- Базовый процент эквити для первой входной позиции
- Например, при `base_position_pct = 10.0` и эквити $10000, первая позиция будет $1000 (10%)

**`pyramiding`** (int, по умолчанию `1`)
- Максимальное количество одновременных входов в одном направлении
- Аналог параметра `pyramiding` в TradingView
- `pyramiding = 1` — одна позиция одновременно (без усреднения)
- `pyramiding = 4` — до 4 одновременных позиций

**`use_martingale`** (bool, по умолчанию `False`)
- Включает/выключает мартингейл-скалирование размера позиции
- Если `False`, все позиции будут одинакового размера (`base_position_pct`)
- Если `True`, размер позиции увеличивается по формуле с множителем

**`martingale_mult`** (float, по умолчанию `1.0`)
- Множитель для мартингейла
- Используется только если `use_martingale = True`
- Формула: `size_factor = martingale_mult ** step`, где `step = max(0, closed_trades - open_trades)`
- Примеры:
  - `martingale_mult = 1.0` — без мартингейла, все позиции одинаковые
  - `martingale_mult = 1.5` — каждая позиция в 1.5 раза больше: 1x, 1.5x, 2.25x, 3.375x...
  - `martingale_mult = 2.0` — каждая позиция удваивается: 1x, 2x, 4x, 8x...

##### Формула расчета размера позиции

```python
# TradingView-style: step = closedtrades - opentrades
step = self._closed_trades_count - self._open_positions_count
step = max(0, step)  # Ограничиваем снизу нулем

# Расчет множителя
if self.config.use_martingale:
    size_factor = self.config.martingale_mult ** step
else:
    size_factor = 1.0

# Итоговый размер позиции
position_pct = self.config.base_position_pct * size_factor
size = position_pct / 100.0  # Преобразуем в долю (0.0 - 1.0)
```

##### Пример конфигурации с мартингейлом

```json
{
  "base_position_pct": 10.0,
  "pyramiding": 4,
  "use_martingale": true,
  "martingale_mult": 1.5
}
```

При такой конфигурации:
- Первая позиция: 10% эквити
- Вторая позиция (если первая в убытке): 10% × 1.5 = 15% эквити
- Третья позиция: 10% × 1.5² = 22.5% эквити
- Четвертая позиция: 10% × 1.5³ = 33.75% эквити
- Максимум 4 одновременные позиции (pyramiding = 4)

##### Пример конфигурации без мартингейла (фиксированный размер)

```json
{
  "base_position_pct": 15.0,
  "pyramiding": 3,
  "use_martingale": false,
  "martingale_mult": 1.0
}
```

При такой конфигурации:
- Все позиции будут по 15% эквити
- Максимум 3 одновременные позиции
- Мартингейл отключен — безопаснее для риск-менеджмента

#### Шаг 5: Перенос Take Profit / Stop Loss

В Pine Script:
```pinescript
strategy.exit("ExL", from_entry="Lo",
     limit=strategy.position_avg_price * (1 + tpLongPct/100),
     stop =strategy.position_avg_price * (1 - slLongPct/100))
```

В системе:
```python
self._tp_price = self._entry_price * (1 + self.config.tp_long_pct / 100)
self._sl_price = self._entry_price * (1 - self.config.sl_long_pct / 100)
```

**Это реализовано автоматически** в методах `_set_tp_sl_for_long()` и `_set_tp_sl_for_short()`.

Параметры в конфиге:
```json
{
  "tp_long_pct": 2.0,
  "sl_long_pct": 2.0,
  "tp_short_pct": 2.0,
  "sl_short_pct": 2.0,
  "use_tp_sl": true
}
```

### 4.4 Полный JSON-конфиг стратегии

Объединяя все части, получаем следующий конфиг:

```json
{
  "name": "eth_5m_night_cat_samurai",
  "strategy_type": "indicator",
  "mode": "quant_only",
  "symbol": "ETHUSDT",

  "rsi_len": 14,
  "bb_len": 20,
  "bb_mult": 2.0,
  "vol_ma_len": 21,
  "vol_mult": 0.5,

  "base_size": 0.10,
  "allow_long": true,
  "allow_short": true,

  "base_position_pct": 10.0,
  "pyramiding": 4,
  "use_martingale": true,
  "martingale_mult": 1.5,

  "tp_long_pct": 2.0,
  "sl_long_pct": 2.0,
  "tp_short_pct": 2.0,
  "sl_short_pct": 2.0,
  "use_tp_sl": true,

  "time_filter_enabled": true,
  "time_filter_start_hour": 0,
  "time_filter_end_hour": 7,

  "rules": {
    "long_entry": [
      {"left": "hour", "op": ">=", "right": 0},
      {"left": "hour", "op": "<=", "right": 7},
      {"left": "rsi", "op": "<", "right": 22},
      {"left": "low", "op": "<=", "right": "lower_bb"},
      {"left": "volume", "op": ">", "right": "vol_threshold"}
    ],
    "short_entry": [
      {"left": "hour", "op": ">=", "right": 0},
      {"left": "hour", "op": "<=", "right": 7},
      {"left": "rsi", "op": ">", "right": 80},
      {"left": "high", "op": ">=", "right": "upper_bb"},
      {"left": "volume", "op": ">", "right": "vol_threshold"}
    ],
    "long_exit": [],
    "short_exit": []
  }
}
```

**Примечания**:
- Поля `long_exit` и `short_exit` оставлены пустыми, т.к. в исходной стратегии выход осуществляется только через TP/SL (которые реализованы отдельно).
- Используются алиасы `lower_bb`, `upper_bb` и `vol_threshold` для удобства и читаемости.
- Этот конфиг доступен в файле `examples/night_cat_samurai_strategy.json` в репозитории.

### 4.5 Как использовать конфиг

#### Вариант 1: Через веб-интерфейс

1. Откройте веб-интерфейс создания стратегии.
2. Заполните поля параметров (RSI period, BB length и т.д.).
3. Вставьте JSON правил в поле "Trading Rules":
```json
{
  "long_entry": [...],
  "short_entry": [...],
  "long_exit": [],
  "short_exit": []
}
```
4. Сохраните стратегию.

#### Вариант 2: Программно

```python
from llm_trading_system.strategies.factory import create_strategy_from_config

config = {
    "strategy_type": "indicator",
    "mode": "quant_only",
    "symbol": "ETHUSDT",
    # ... остальные параметры
}

strategy = create_strategy_from_config(config, llm_client=None)
```

#### Вариант 3: Запуск бэктеста

```python
from llm_trading_system.engine.backtester import Backtester
from llm_trading_system.engine.data_feed import CSVDataFeed
from llm_trading_system.strategies.factory import create_strategy_from_config

# Создание стратегии
strategy = create_strategy_from_config(config, llm_client=None)

# Загрузка данных
data_feed = CSVDataFeed(path="data/ETHUSDT_5m.csv", symbol="ETHUSDT")

# Запуск бэктеста
backtester = Backtester(
    strategy=strategy,
    data_feed=data_feed,
    initial_equity=50.0,  # initial_capital из Pine
    fee_rate=0.0004,      # commission_value / 100
    symbol="ETHUSDT"
)

result = backtester.run()

print(f"Final equity: {result.final_equity:.2f}")
print(f"Total return: {result.total_return:.2%}")
print(f"Max drawdown: {result.max_drawdown:.2%}")
print(f"Number of trades: {len(result.trades)}")
```

### 4.6 Отличия от TradingView

#### Пирамидинг

**TradingView**: Поддерживает несколько открытых позиций (entries) одновременно. Каждая позиция может быть закрыта отдельно.

**Эта система**: Текущая реализация `PortfolioSimulator` поддерживает только **одну позицию** на символ. При новом входе предыдущая позиция закрывается.

**Адаптация**: Параметр `pyramiding` используется для ограничения количества попыток входа. Мартингейл-множитель масштабирует размер позиции на основе `step = closedtrades - opentrades`.

**Практическое применение**: Несмотря на ограничение одной позиции, система корректно эмулирует поведение мартингейла:
- При первом входе: `step = 0`, размер = `base_size * 1.5^0 = 0.10`
- После закрытия 1 сделки: `step = 1`, размер = `base_size * 1.5^1 = 0.15`
- После закрытия 2 сделок: `step = 2`, размер = `base_size * 1.5^2 = 0.225`

**Будущее улучшение**: Можно расширить `PortfolioSimulator` для поддержки настоящего пирамидинга (множественных открытых позиций).

#### TP/SL

**TradingView**: Использует `strategy.exit()` с `limit` и `stop`.

**Эта система**: TP/SL проверяются на каждом баре через `_check_tp_sl_hit()`.

**Логика проверки** (консервативный подход, SL первым):
1. Для лонга:
   - Сначала проверяется: `bar.low <= sl_price` → закрытие по стопу
   - Затем проверяется: `bar.high >= tp_price` → закрытие по тейку
2. Для шорта:
   - Сначала проверяется: `bar.high >= sl_price` → закрытие по стопу
   - Затем проверяется: `bar.low <= tp_price` → закрытие по тейку

**Точность**: В реальности TP/SL могут сработать в любой момент внутри бара. В бэктестере используется упрощение: проверка по high/low бара. SL проверяется первым для более консервативной оценки результатов.

#### Комиссии

**TradingView**: `commission_value=0.04` означает 0.04% от номинала сделки.

**Эта система**: Используется параметр `fee_rate` в `Backtester`:
```python
backtester = Backtester(
    strategy=strategy,
    data_feed=data_feed,
    initial_equity=50.0,
    fee_rate=0.0004,  # 0.04% = 0.0004
    symbol="ETHUSDT"
)
```

Комиссия применяется при открытии и закрытии позиции.

---

## 5. Как добавить новую стратегию

### 5.1 Если все индикаторы уже есть

Если ваша стратегия использует только существующие индикаторы (RSI, SMA, EMA, BB, ATR, vol_ma), вам НЕ нужно менять код.

**Шаги**:

1. **Определите параметры индикаторов**: Какие периоды, множители и т.д.
2. **Сформулируйте условия входа/выхода**: В терминах индикаторов и сравнений.
3. **Создайте JSON-правила**: Используя формат RuleSet.
4. **Создайте конфиг стратегии**: Объедините параметры и правила.
5. **Запустите бэктест**: Через веб-интерфейс или программно.

**Пример**: Простая стратегия RSI

```json
{
  "strategy_type": "indicator",
  "mode": "quant_only",
  "symbol": "BTCUSDT",
  "rsi_len": 14,
  "base_size": 0.05,
  "allow_long": true,
  "allow_short": true,
  "rules": {
    "long_entry": [
      {"left": "rsi", "op": "<", "right": 30}
    ],
    "short_entry": [
      {"left": "rsi", "op": ">", "right": 70}
    ],
    "long_exit": [
      {"left": "rsi", "op": ">", "right": 70}
    ],
    "short_exit": [
      {"left": "rsi", "op": "<", "right": 30}
    ]
  }
}
```

### 5.2 Если нужны новые индикаторы

Если ваша стратегия требует индикатор, которого нет в библиотеке (например, Stochastic, CCI, Ichimoku и т.д.), вам нужно:

#### Шаг 1: Реализовать функцию индикатора

Откройте файл `llm_trading_system/strategies/indicators.py` и добавьте новую функцию:

```python
def stochastic(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    k_period: int = 14,
    d_period: int = 3
) -> tuple[float | None, float | None]:
    """Calculate Stochastic Oscillator (%K, %D).

    Args:
        highs: High prices
        lows: Low prices
        closes: Close prices
        k_period: Period for %K
        d_period: Period for %D (SMA of %K)

    Returns:
        Tuple of (%K, %D) or (None, None)
    """
    if len(highs) < k_period or len(lows) < k_period or len(closes) < k_period:
        return None, None

    # %K = (Close - Low(k_period)) / (High(k_period) - Low(k_period)) * 100
    recent_highs = highs[-k_period:]
    recent_lows = lows[-k_period:]
    highest = max(recent_highs)
    lowest = min(recent_lows)

    if highest == lowest:
        return 50.0, None

    k = ((closes[-1] - lowest) / (highest - lowest)) * 100

    # %D = SMA of %K (requires k_history)
    # Для полной реализации нужно накапливать историю %K

    return k, None
```

**Примечание**: Для полноценной реализации Stochastic нужно накапливать историю %K для вычисления %D.

#### Шаг 2: Добавить вычисление индикатора в IndicatorStrategy

Откройте `llm_trading_system/strategies/indicator_strategy.py` и добавьте вычисление в метод `_compute_indicators()`:

```python
def _compute_indicators(self, bar: Bar | None = None) -> dict[str, float | None]:
    # ... существующий код ...

    # Stochastic
    if hasattr(self.config, 'stoch_k_period'):
        stoch_k, stoch_d = stochastic(
            highs_list, lows_list, closes_list,
            self.config.stoch_k_period,
            self.config.stoch_d_period
        )
        indicators["stoch_k"] = stoch_k
        indicators["stoch_d"] = stoch_d

    return indicators
```

#### Шаг 3: Добавить параметры в конфигурацию

Откройте `llm_trading_system/strategies/configs.py` и добавьте поля:

```python
@dataclass
class IndicatorStrategyConfig:
    # ... существующие поля ...

    # Stochastic parameters
    stoch_k_period: int = 14
    stoch_d_period: int = 3
```

#### Шаг 4: Использовать новый индикатор в правилах

Теперь вы можете использовать `stoch_k` и `stoch_d` в JSON-правилах:

```json
{
  "long_entry": [
    {"left": "stoch_k", "op": "<", "right": 20},
    {"left": "stoch_k", "op": "cross_above", "right": "stoch_d"}
  ]
}
```

### 5.3 Создание стратегии через веб-интерфейс

1. Откройте веб-интерфейс (обычно `http://localhost:5000` или аналогичный).
2. Перейдите в раздел "Создать стратегию".
3. Выберите тип стратегии: **Indicator** (или **Combined** для гибридного режима).
4. Заполните параметры:
   - Symbol
   - RSI length, BB length, vol_mult и т.д.
   - Base size, pyramiding, martingale_mult
   - TP/SL параметры
   - Временной фильтр
5. Вставьте JSON-правила в поле "Trading Rules".
6. Нажмите "Save Strategy".

### 5.4 Запуск бэктеста через CLI

```bash
python -m llm_trading_system.cli.full_cycle_cli \
    --config strategies/my_strategy.json \
    --data data/BTCUSDT_5m.csv \
    --symbol BTCUSDT \
    --initial-equity 10000
```

---

## 6. Совместное использование с LLM-режимом

### 6.1 Три режима работы стратегий

Система поддерживает три режима (определяется параметром `mode` в конфиге):

#### QUANT_ONLY

Чисто индикаторная стратегия без использования LLM.

- Использует только технические индикаторы
- Правила входа/выхода через JSON DSL
- LLM не вызывается

**Конфиг**:
```json
{
  "mode": "quant_only",
  "strategy_type": "indicator",
  "rules": { ... }
}
```

#### LLM_ONLY

Стратегия основана только на анализе LLM (без технических индикаторов).

- LLM анализирует рыночные снимки (market snapshots)
- Возвращает `prob_bull`, `prob_bear`, `k_long`, `k_short`
- Размер позиции = `base_size * k_long` (или `k_short`)

**Конфиг**:
```json
{
  "mode": "llm_only",
  "strategy_type": "combined"
}
```

#### HYBRID

Комбинация индикаторной стратегии и LLM.

- Индикаторы определяют точки входа/выхода (через JSON-правила)
- LLM определяет "режим рынка" и коэффициенты `k_long`, `k_short`
- Размер позиции модулируется коэффициентами LLM

**Конфиг**:
```json
{
  "mode": "hybrid",
  "strategy_type": "combined",
  "rules": { ... }
}
```

### 6.2 Как LLM влияет на индикаторную стратегию

В режиме **HYBRID**:

1. **Индикаторная стратегия** генерирует сигнал входа (на основе правил).
2. **LLM-режим** анализирует рынок и возвращает коэффициенты:
   - `k_long` — множитель для лонг-позиций (0.0 - 2.0)
   - `k_short` — множитель для шорт-позиций (0.0 - 2.0)
3. **Итоговый размер позиции**:
   - Для лонга: `size = base_size * k_long`
   - Для шорта: `size = base_size * k_short`

**Примеры**:

- Если `k_long = 0.0` → лонги блокируются (даже если есть сигнал от индикаторов)
- Если `k_long = 2.0` → размер лонг-позиции удваивается
- Если `k_short = 0.5` → размер шорт-позиции уменьшается вдвое

### 6.3 Пример HYBRID стратегии

```json
{
  "mode": "hybrid",
  "strategy_type": "combined",
  "symbol": "BTCUSDT",

  "rsi_len": 14,
  "bb_len": 20,
  "bb_mult": 2.0,

  "base_size": 0.05,
  "k_max": 2.0,

  "llm_refresh_interval_bars": 30,
  "llm_min_prob_edge": 0.05,
  "llm_min_trend_strength": 0.2,

  "rules": {
    "long_entry": [
      {"left": "rsi", "op": "<", "right": 30},
      {"left": "close", "op": "<=", "right": "lowerBB"}
    ],
    "short_entry": [
      {"left": "rsi", "op": ">", "right": 70},
      {"left": "close", "op": ">=", "right": "upperBB"}
    ],
    "long_exit": [
      {"left": "rsi", "op": ">", "right": 70}
    ],
    "short_exit": [
      {"left": "rsi", "op": "<", "right": 30}
    ]
  }
}
```

**Логика**:

- Индикаторы определяют, когда входить (RSI < 30 и цена у нижней полосы BB)
- LLM анализирует рынок каждые 30 баров и решает, насколько агрессивно входить
- Если LLM видит сильный бычий режим → `k_long = 2.0` → удвоенный размер лонга
- Если LLM видит медвежий режим → `k_long = 0.0` → лонги блокируются

### 6.4 Настройка LLM-параметров

**llm_refresh_interval_bars**:
- Как часто обновлять LLM-режим (в барах)
- Например, `30` = обновлять каждые 30 баров (2.5 часа на 5m таймфрейме)

**llm_min_prob_edge**:
- Минимальная разница `|prob_bull - prob_bear|` для применения коэффициентов
- Если разница меньше → `k_long = k_short = 1.0` (нет влияния LLM)

**llm_min_trend_strength**:
- Минимальная сила тренда для применения коэффициентов
- Если `trend_strength < llm_min_trend_strength` → `k_long = k_short = 1.0`

**k_max**:
- Максимальный коэффициент (обычно 2.0)
- Ограничивает максимальное увеличение размера позиции

### 6.5 Когда использовать каждый режим

| Режим | Когда использовать |
|-------|--------------------|
| **QUANT_ONLY** | Чистая техническая стратегия, не нужен анализ LLM |
| **LLM_ONLY** | Полагаетесь только на анализ LLM (экспериментальный подход) |
| **HYBRID** | Хотите объединить точность индикаторов и "понимание" рынка от LLM |

**Рекомендация**: Для большинства случаев начинайте с **QUANT_ONLY**, затем тестируйте **HYBRID** для улучшения.

---

## Заключение

Эта система предоставляет гибкий и расширяемый фреймворк для создания торговых стратегий:

✅ **Библиотека индикаторов** — готовые технические индикаторы (RSI, BB, SMA, EMA, ATR и др.)

✅ **JSON DSL** — простой декларативный язык для описания правил входа/выхода

✅ **Пирамидинг и мартингейл** — поддержка сложных стратегий управления позицией

✅ **TP/SL** — автоматические Take Profit и Stop Loss

✅ **Временные фильтры** — торговля в определённые часы

✅ **LLM-интеграция** — возможность комбинировать индикаторы с анализом LLM

✅ **Бэктестер** — полноценное тестирование на исторических данных

### Следующие шаги

1. **Изучите примеры** в разделе 4 (перенос Pine Script стратегии)
2. **Создайте свою первую стратегию** через веб-интерфейс
3. **Запустите бэктест** и проанализируйте результаты
4. **Добавьте новые индикаторы** по мере необходимости (раздел 5.2)
5. **Экспериментируйте с HYBRID режимом** для улучшения результатов

**Удачи в трейдинге!** 🚀📈
