# 🚨 КРИТИЧЕСКИЕ БАГИ: Time Filter и Trades Table

**Дата обнаружения:** 2025-11-21
**Приоритет:** 🔴 **КРИТИЧЕСКИЙ**
**Статус:** ❌ **ТРЕБУЕТ НЕМЕДЛЕННОГО ИСПРАВЛЕНИЯ**

---

## Executive Summary

Обнаружены **КРИТИЧЕСКИЕ БАГИ** в функциональности Time Filter (Start Hour UTC / End Hour UTC), которые приводят к:
1. ❌ **Потере параметров** time_filter при редактировании стратегии
2. ❌ **Некорректной работе торговли** (стратегия торгует в неправильное время)
3. ❌ **Не обновлению таблицы Trades** из-за ошибок в стратегии

---

## 🐛 Баг #1: Time Filter поля отсутствуют в UI форме

### Описание
В файле `llm_trading_system/api/templates/strategy_form.html` **отсутствуют поля ввода** для параметров Time Filter.

### Местоположение
📁 `llm_trading_system/api/templates/strategy_form.html`
Строки: 1-277 (поля отсутствуют во всей форме)

### Воспроизведение
```bash
# 1. Открыть стратегию с time_filter
curl http://localhost:8000/ui/strategies/night_cat_samurai_strategy/edit

# 2. Проверить HTML исходник
# РЕЗУЛЬТАТ: Нет полей для time_filter_enabled, time_filter_start_hour, time_filter_end_hour
```

### Ожидаемое поведение
Форма должна содержать:
```html
<div class="form-section">
    <h3>Time Filter (Trading Hours)</h3>

    <div class="form-group">
        <label>
            <input type="checkbox" name="time_filter_enabled" {% if config.get('time_filter_enabled', False) %}checked{% endif %}>
            Enable Time Filter
        </label>
    </div>

    <div class="form-row">
        <div class="form-group">
            <label for="time_filter_start_hour">Start Hour (UTC)</label>
            <input type="number" id="time_filter_start_hour" name="time_filter_start_hour"
                   value="{{ config.get('time_filter_start_hour', 0) }}"
                   min="0" max="23" required>
        </div>

        <div class="form-group">
            <label for="time_filter_end_hour">End Hour (UTC)</label>
            <input type="number" id="time_filter_end_hour" name="time_filter_end_hour"
                   value="{{ config.get('time_filter_end_hour', 23) }}"
                   min="0" max="23" required>
        </div>
    </div>
</div>
```

### Текущее поведение
- ❌ Поля отсутствуют в форме
- ❌ Пользователь не может редактировать time_filter через UI
- ❌ Существующие значения time_filter не отображаются

### Влияние
**🔴 КРИТИЧЕСКОЕ:**
- Пользователь не видит настройки времени торговли
- При сохранении стратегии time_filter параметры теряются (см. Баг #2)

---

## 🐛 Баг #2: Time Filter параметры НЕ обрабатываются при сохранении

### Описание
В функции `ui_save_strategy()` отсутствует обработка параметров time_filter, что приводит к их потере при сохранении стратегии.

### Местоположение
📁 `llm_trading_system/api/ui_routes.py`
Функция: `ui_save_strategy()` (строки 481-611)

### Проблемный код
```python
@router.post("/ui/strategies/{name}/save")
async def ui_save_strategy(
    # ... другие параметры ...
    vol_mult: float = Form(0.5),
    # LLM parameters
    k_max: float = Form(2.0),
    # ... остальные параметры ...

    # ❌ ОТСУТСТВУЮТ:
    # time_filter_enabled: bool = Form(False),
    # time_filter_start_hour: int = Form(0),
    # time_filter_end_hour: int = Form(23),
) -> RedirectResponse:
    # Build config dictionary
    config = {
        "vol_mult": vol_mult,
        # LLM parameters
        "k_max": k_max,
        # ...

        # ❌ ОТСУТСТВУЮТ в config dict:
        # "time_filter_enabled": time_filter_enabled,
        # "time_filter_start_hour": time_filter_start_hour,
        # "time_filter_end_hour": time_filter_end_hour,
    }
```

### Воспроизведение
```python
# 1. Создать стратегию с time_filter
config = {
    "time_filter_enabled": True,
    "time_filter_start_hour": 0,
    "time_filter_end_hour": 7,
    # ... другие параметры
}
storage.save_config("test_strategy", config)

# 2. Открыть стратегию в UI и нажать "Save Strategy"
# POST /ui/strategies/test_strategy/save

# 3. Проверить сохраненную конфигурацию
config = storage.load_config("test_strategy")
print(config.get("time_filter_enabled"))  # None или False (дефолт)
print(config.get("time_filter_start_hour"))  # None или 0 (дефолт)

# РЕЗУЛЬТАТ: time_filter параметры ПОТЕРЯНЫ!
```

### Ожидаемое поведение
Функция должна принимать и сохранять time_filter параметры:

```python
@router.post("/ui/strategies/{name}/save")
async def ui_save_strategy(
    # ... существующие параметры ...
    vol_mult: float = Form(0.5),

    # ✅ ДОБАВИТЬ:
    # Time filter parameters
    time_filter_enabled: bool = Form(False),
    time_filter_start_hour: int = Form(0),
    time_filter_end_hour: int = Form(23),

    # ... остальные параметры ...
) -> RedirectResponse:
    # Build config dictionary
    config = {
        # ... существующие поля ...
        "vol_mult": vol_mult,

        # ✅ ДОБАВИТЬ:
        # Time filter
        "time_filter_enabled": time_filter_enabled,
        "time_filter_start_hour": time_filter_start_hour,
        "time_filter_end_hour": time_filter_end_hour,

        # ... остальные поля ...
    }
```

### Текущее поведение
- ❌ Параметры time_filter НЕ читаются из формы
- ❌ Параметры time_filter НЕ сохраняются в config
- ❌ При пересохранении стратегии time_filter параметры ТЕРЯЮТСЯ

### Влияние
**🔴 КРИТИЧЕСКОЕ:**
- При любом редактировании стратегии time_filter параметры сбрасываются
- Стратегия с ограниченным временем торговли начинает торговать 24/7
- Это может привести к нежелательным сделкам вне заданного времени

---

## 🐛 Баг #3: Time Filter параметры отсутствуют в ui_recalculate_backtest

### Описание
В функции `ui_recalculate_backtest()` параметры time_filter обрабатываются, но аналогично могут теряться.

### Местоположение
📁 `llm_trading_system/api/ui_routes.py`
Функции:
- `ui_recalculate_backtest()` (строки 1414-1529)
- `ui_save_strategy_params()` (строки 1532-1621)

### Статус
⚠️ Частично реализовано (строки 1492-1494, 1599-1601):
```python
"time_filter_enabled": bool(params.get("time_filter_enabled", ...)),
"time_filter_start_hour": int(params.get("time_filter_start_hour", ...)),
"time_filter_end_hour": int(params.get("time_filter_end_hour", ...)),
```

### Проблема
Хотя параметры обрабатываются в JSON API, они **не связаны с UI формой** из-за Бага #1 и #2.

---

## 🐛 Баг #4: Проблема с обновлением таблицы Trades

### Описание
Из-за багов #1, #2, #3 стратегия работает с некорректными time_filter параметрами, что может приводить к:
- Ошибкам в торговой логике
- Неожиданным сделкам
- Сбоям в обновлении таблицы Trades

### Гипотеза
1. Пользователь создает стратегию с `time_filter_enabled=True, start_hour=0, end_hour=7`
2. Стратегия должна торговать только с 00:00 до 07:00 UTC
3. Пользователь редактирует стратегию через UI (например, меняет RSI параметры)
4. При сохранении time_filter параметры теряются (становятся `False, 0, 23`)
5. Стратегия начинает торговать 24/7
6. Это нарушает логику торговли
7. Возникают ошибки, таблица Trades не обновляется

### Требуется дополнительная проверка
- [ ] Проверить логи ошибок при неправильной работе time_filter
- [ ] Проверить, как ошибки в стратегии влияют на обновление Trades
- [ ] Проверить WebSocket обновления для таблицы Trades

---

## 📊 Анализ затронутых компонентов

### Затронутые файлы
| Файл | Проблема | Приоритет |
|------|----------|-----------|
| `api/templates/strategy_form.html` | Отсутствуют поля time_filter | 🔴 CRITICAL |
| `api/ui_routes.py::ui_save_strategy()` | Не обрабатывает time_filter | 🔴 CRITICAL |
| `strategies/configs.py` | Валидация работает корректно | ✅ OK |
| `strategies/indicator_strategy.py` | Логика time_filter работает корректно | ✅ OK |

### Работающие компоненты
✅ **IndicatorStrategyConfig** - валидация time_filter работает
✅ **_is_in_time_window()** - логика проверки времени корректна
✅ **ui_recalculate_backtest()** - JSON API обрабатывает time_filter
✅ **ui_save_strategy_params()** - JSON API обрабатывает time_filter

### Проблемные компоненты
❌ **strategy_form.html** - нет полей ввода
❌ **ui_save_strategy()** - не читает/не сохраняет параметры

---

## 🔧 Решение

### Исправление #1: Добавить поля в strategy_form.html

**Местоположение вставки:** После секции "Risk / Money Management", перед "LLM Parameters"

```html
<!-- ДОБАВИТЬ в strategy_form.html после строки 204 -->
<div class="form-section">
    <h3>Time Filter (Trading Hours)</h3>
    <p class="help-text" style="margin-bottom: 1rem;">
        <strong>Note:</strong> Time filter allows you to restrict trading to specific hours (UTC timezone).
        When enabled, the strategy will only enter new positions during the specified time window.
        Existing positions will be managed (TP/SL, exit rules) regardless of time.
    </p>

    <div class="form-group">
        <label>
            <input type="checkbox" name="time_filter_enabled" id="time_filter_enabled"
                   {% if config.get('time_filter_enabled', False) %}checked{% endif %}>
            Enable Time Filter
        </label>
        <small class="help-text">Restrict trading to specific hours (UTC)</small>
    </div>

    <div class="form-row" id="time_filter_settings">
        <div class="form-group">
            <label for="time_filter_start_hour">Start Hour (UTC)</label>
            <input type="number" id="time_filter_start_hour" name="time_filter_start_hour"
                   value="{{ config.get('time_filter_start_hour', 0) }}"
                   min="0" max="23" step="1" required>
            <small class="help-text">Trading starts at this hour (0-23, UTC timezone)</small>
        </div>

        <div class="form-group">
            <label for="time_filter_end_hour">End Hour (UTC)</label>
            <input type="number" id="time_filter_end_hour" name="time_filter_end_hour"
                   value="{{ config.get('time_filter_end_hour', 23) }}"
                   min="0" max="23" step="1" required>
            <small class="help-text">Trading ends at this hour (0-23, UTC timezone)</small>
        </div>
    </div>

    <div class="form-group">
        <small class="help-text">
            <strong>Examples:</strong><br>
            • Day trading (09:00-17:00 UTC): Start=9, End=17<br>
            • Night trading (22:00-06:00 UTC): Start=22, End=6 (wrap-around supported)<br>
            • Asian session (00:00-08:00 UTC): Start=0, End=8
        </small>
    </div>

    <script>
        // Show/hide time filter settings based on checkbox
        document.getElementById('time_filter_enabled').addEventListener('change', function() {
            const settings = document.getElementById('time_filter_settings');
            settings.style.display = this.checked ? 'flex' : 'none';
        });

        // Initialize visibility on page load
        document.addEventListener('DOMContentLoaded', function() {
            const checkbox = document.getElementById('time_filter_enabled');
            const settings = document.getElementById('time_filter_settings');
            settings.style.display = checkbox.checked ? 'flex' : 'none';
        });
    </script>
</div>
```

---

### Исправление #2: Добавить параметры в ui_save_strategy()

**Файл:** `llm_trading_system/api/ui_routes.py`

```python
@router.post("/ui/strategies/{name}/save")
async def ui_save_strategy(
    request: Request,
    name: str,
    user=Depends(require_auth),
    csrf_token: str = Form(...),
    strategy_name: str = Form(..., alias="name"),
    strategy_type: str = Form(...),
    mode: str = Form(...),
    symbol: str = Form(...),
    base_size: float = Form(...),
    allow_long: bool = Form(False),
    allow_short: bool = Form(False),
    # Risk / Money Management
    base_position_pct: float = Form(10.0),
    pyramiding: int = Form(1),
    use_martingale: bool = Form(False),
    martingale_mult: float = Form(1.5),
    tp_long_pct: float = Form(2.0),
    sl_long_pct: float = Form(2.0),
    tp_short_pct: float = Form(2.0),
    sl_short_pct: float = Form(2.0),
    use_tp_sl: bool = Form(False),

    # ✅ ДОБАВИТЬ: Time filter parameters
    time_filter_enabled: bool = Form(False),
    time_filter_start_hour: int = Form(0),
    time_filter_end_hour: int = Form(23),

    # Indicator parameters
    ema_fast_len: int = Form(...),
    ema_slow_len: int = Form(...),
    rsi_len: int = Form(...),
    rsi_ovb: int = Form(...),
    rsi_ovs: int = Form(...),
    bb_len: int = Form(...),
    bb_mult: float = Form(...),
    atr_len: int = Form(...),
    adx_len: int = Form(...),
    vol_ma_len: int = Form(21),
    vol_mult: float = Form(0.5),
    # LLM parameters
    k_max: float = Form(2.0),
    llm_horizon_hours: int = Form(24),
    llm_min_prob_edge: float = Form(0.55),
    llm_min_trend_strength: float = Form(0.6),
    llm_refresh_interval_bars: int = Form(60),
    # Trading rules
    rules_long_entry: str = Form("[]"),
    rules_short_entry: str = Form("[]"),
    rules_long_exit: str = Form("[]"),
    rules_short_exit: str = Form("[]"),
) -> RedirectResponse:
    """Web UI: Save a strategy configuration."""

    # CSRF validation
    _verify_csrf_token(request, csrf_token)

    # Use form name if different from URL name
    actual_name = strategy_name if name == "new" else name

    # Parse rules from JSON strings
    try:
        long_entry = json.loads(rules_long_entry)
        short_entry = json.loads(rules_short_entry)
        long_exit = json.loads(rules_long_exit)
        short_exit = json.loads(rules_short_exit)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid rules JSON: {e}")

    # Build config dictionary
    config = {
        "strategy_type": strategy_type,
        "mode": mode,
        "symbol": symbol,
        "base_size": base_size,
        "allow_long": allow_long,
        "allow_short": allow_short,
        # Risk / Money Management
        "base_position_pct": base_position_pct,
        "pyramiding": pyramiding,
        "use_martingale": use_martingale,
        "martingale_mult": martingale_mult,
        "tp_long_pct": tp_long_pct,
        "sl_long_pct": sl_long_pct,
        "tp_short_pct": tp_short_pct,
        "sl_short_pct": sl_short_pct,
        "use_tp_sl": use_tp_sl,

        # ✅ ДОБАВИТЬ: Time filter
        "time_filter_enabled": time_filter_enabled,
        "time_filter_start_hour": time_filter_start_hour,
        "time_filter_end_hour": time_filter_end_hour,

        # Indicator parameters
        "ema_fast_len": ema_fast_len,
        "ema_slow_len": ema_slow_len,
        "rsi_len": rsi_len,
        "rsi_ovb": rsi_ovb,
        "rsi_ovs": rsi_ovs,
        "bb_len": bb_len,
        "bb_mult": bb_mult,
        "atr_len": atr_len,
        "adx_len": adx_len,
        "vol_ma_len": vol_ma_len,
        "vol_mult": vol_mult,
        # LLM parameters
        "k_max": k_max,
        "llm_horizon_hours": llm_horizon_hours,
        "llm_min_prob_edge": llm_min_prob_edge,
        "llm_min_trend_strength": llm_min_trend_strength,
        "llm_refresh_interval_bars": llm_refresh_interval_bars,
        # Trading rules
        "rules": {
            "long_entry": long_entry,
            "short_entry": short_entry,
            "long_exit": long_exit,
            "short_exit": short_exit,
        },
    }

    # Save config
    try:
        storage.save_config(actual_name, config)
        return RedirectResponse(
            url=f"/ui/strategies/{actual_name}/edit", status_code=303
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save config: {e}")
```

---

### Исправление #3: Добавить валидацию на API уровне

**Добавить в ui_save_strategy() после CSRF validation:**

```python
# CSRF validation
_verify_csrf_token(request, csrf_token)

# ✅ ДОБАВИТЬ: Validate time_filter parameters
if time_filter_enabled:
    if not (0 <= time_filter_start_hour <= 23):
        raise HTTPException(
            status_code=400,
            detail=f"time_filter_start_hour must be in [0, 23], got {time_filter_start_hour}"
        )
    if not (0 <= time_filter_end_hour <= 23):
        raise HTTPException(
            status_code=400,
            detail=f"time_filter_end_hour must be in [0, 23], got {time_filter_end_hour}"
        )

# Continue with existing code...
```

---

## 🧪 Тестирование исправлений

### Тест 1: Сохранение time_filter через UI

```python
# 1. Создать стратегию с time_filter
POST /ui/strategies/new/save
{
    "name": "test_time_filter",
    "time_filter_enabled": true,
    "time_filter_start_hour": 0,
    "time_filter_end_hour": 7,
    # ... остальные параметры
}

# 2. Проверить сохранение
config = storage.load_config("test_time_filter")
assert config["time_filter_enabled"] == True
assert config["time_filter_start_hour"] == 0
assert config["time_filter_end_hour"] == 7

# 3. Редактировать стратегию через UI (изменить RSI)
POST /ui/strategies/test_time_filter/save
{
    "rsi_len": 21,  # изменили RSI
    "time_filter_enabled": true,  # должно сохраниться
    "time_filter_start_hour": 0,
    "time_filter_end_hour": 7,
    # ... остальные параметры
}

# 4. Проверить, что time_filter не потерялся
config = storage.load_config("test_time_filter")
assert config["time_filter_enabled"] == True  # ✅ Должно остаться
assert config["time_filter_start_hour"] == 0
assert config["time_filter_end_hour"] == 7
```

### Тест 2: Отображение в UI

```bash
# 1. Открыть стратегию с time_filter в браузере
curl http://localhost:8000/ui/strategies/night_cat_samurai_strategy/edit

# 2. Проверить наличие полей в HTML
grep "time_filter_enabled" response.html  # ✅ Должно найти checkbox
grep "time_filter_start_hour" response.html  # ✅ Должно найти input
grep "time_filter_end_hour" response.html  # ✅ Должно найти input

# 3. Проверить значения
# Для night_cat_samurai_strategy должно быть: enabled=true, start=0, end=7
```

### Тест 3: Валидация границ

```python
# Тест 3.1: Негативный start_hour
POST /ui/strategies/test/save
{
    "time_filter_enabled": true,
    "time_filter_start_hour": 25,  # > 23 - invalid
    "time_filter_end_hour": 23,
}
# ОЖИДАЕМ: HTTPException 400 "time_filter_start_hour must be in [0, 23]"

# Тест 3.2: Отрицательный end_hour
POST /ui/strategies/test/save
{
    "time_filter_enabled": true,
    "time_filter_start_hour": 0,
    "time_filter_end_hour": -5,  # < 0 - invalid
}
# ОЖИДАЕМ: HTTPException 400 "time_filter_end_hour must be in [0, 23]"

# Тест 3.3: Валидный wrap-around
POST /ui/strategies/test/save
{
    "time_filter_enabled": true,
    "time_filter_start_hour": 22,
    "time_filter_end_hour": 6,  # Wrap-around - valid
}
# ОЖИДАЕМ: Сохранение успешно ✅
```

---

## 📋 Чеклист для исправления

### Разработка
- [ ] Добавить поля time_filter в strategy_form.html (после строки 204)
- [ ] Добавить параметры time_filter в ui_save_strategy() (строки 504-505, 575-577)
- [ ] Добавить валидацию time_filter на API уровне (после строки 543)
- [ ] Проверить, что ui_get_strategy_params() возвращает time_filter (строки 1402-1404) ✅ УЖЕ ЕСТЬ
- [ ] Проверить, что ui_recalculate_backtest() обрабатывает time_filter (строки 1492-1494) ✅ УЖЕ ЕСТЬ
- [ ] Проверить, что ui_save_strategy_params() обрабатывает time_filter (строки 1599-1601) ✅ УЖЕ ЕСТЬ

### Тестирование
- [ ] Написать unit-тесты для time_filter валидации
- [ ] Написать интеграционный тест для сохранения/загрузки time_filter
- [ ] Проверить работу time_filter в backtest
- [ ] Проверить работу time_filter в live trading
- [ ] Проверить UI отображение и редактирование

### Документация
- [ ] Обновить STRATEGY_PARAMETERS_VALIDATION_REPORT.md
- [ ] Добавить примеры использования time_filter
- [ ] Обновить описание в STRATEGIES.md

---

## 🎯 Приоритизация

### Фаза 1: Критическое исправление (СЕЙЧАС)
1. ✅ Найти и документировать баг
2. 🔄 Добавить поля в strategy_form.html
3. 🔄 Добавить параметры в ui_save_strategy()
4. 🔄 Добавить валидацию
5. 🔄 Протестировать исправления

### Фаза 2: Проверка влияния на Trades table
1. Проверить, как ошибки time_filter влияют на обновление Trades
2. Добавить обработку ошибок в live_service.py
3. Улучшить логирование ошибок time_filter

### Фаза 3: Улучшения UX
1. Добавить визуальный индикатор активного time_filter
2. Показывать текущее время UTC в UI
3. Добавить предупреждение при изменении time_filter в активной сессии

---

## 📞 Контакты

**Обнаружено:** Claude (Anthropic)
**Подтверждено:** Пользователь (указал на проблему с Start/End Hour UTC и Trades table)
**Дата:** 2025-11-21

---

**КОНЕЦ ОТЧЕТА О КРИТИЧЕСКИХ БАГАХ**
