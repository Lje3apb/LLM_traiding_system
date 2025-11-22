# ✅ ИСПРАВЛЕНО: Валидация параметров стратегии

**Дата:** 2025-11-21
**Статус:** ✅ **ИСПРАВЛЕНО И ПРОТЕСТИРОВАНО**

---

## Ошибка которую вы обнаружили

```
Error: Recalculate failed: rsi_ovs must be < rsi_ovb, got ovs=30, ovb=20
```

**Причина:**
Пользователь ввел некорректные значения RSI (перепутал местами oversold и overbought), но валидация срабатывала только на уровне `IndicatorStrategyConfig`, после отправки формы в `ui_recalculate_backtest()`.

---

## Что было сделано

### 1. ✅ Добавлена валидация на API уровне

#### **ui_save_strategy()** (`ui_routes.py:549-605`)

```python
# Validate strategy parameters before processing
# RSI thresholds
if rsi_ovs >= rsi_ovb:
    raise HTTPException(
        status_code=400,
        detail=f"RSI Oversold must be less than RSI Overbought. Got ovs={rsi_ovs}, ovb={rsi_ovb}"
    )

# Time filter parameters
if time_filter_enabled:
    if not (0 <= time_filter_start_hour <= 23):
        raise HTTPException(status_code=400, detail="...")
    if not (0 <= time_filter_end_hour <= 23):
        raise HTTPException(status_code=400, detail="...")

# TP/SL validation
if use_tp_sl:
    if tp_long_pct <= 0:
        raise HTTPException(status_code=400, detail="...")
    if sl_long_pct <= 0:
        raise HTTPException(status_code=400, detail="...")
    if tp_short_pct <= 0:
        raise HTTPException(status_code=400, detail="...")
    if sl_short_pct <= 0:
        raise HTTPException(status_code=400, detail="...")

# Pyramiding validation
if pyramiding < 1:
    raise HTTPException(status_code=400, detail="...")

# Base position validation
if base_position_pct <= 0 or base_position_pct > 100:
    raise HTTPException(status_code=400, detail="...")
```

---

#### **ui_recalculate_backtest()** (`ui_routes.py:1563-1611`)

```python
# Validate strategy parameters before running backtest
# RSI thresholds
rsi_ovs = config.get("rsi_ovs", 30)
rsi_ovb = config.get("rsi_ovb", 70)
if rsi_ovs >= rsi_ovb:
    raise HTTPException(
        status_code=400,
        detail=f"RSI Oversold must be less than RSI Overbought. Got ovs={rsi_ovs}, ovb={rsi_ovb}"
    )

# (... аналогичные проверки для всех параметров)
```

**Результат:**
- Теперь ошибки валидации обнаруживаются **ДО** запуска бэктеста
- Понятное сообщение об ошибке с фактическими значениями
- Ошибка возвращается как HTTP 400 Bad Request

---

### 2. ✅ Добавлена валидация на UI уровне

#### **JavaScript валидация в strategy_form.html** (строки 350-496)

```javascript
// Client-side validation for strategy parameters
(function() {
    const form = document.querySelector('.strategy-form');

    // Validate RSI thresholds
    function validateRSI() {
        const rsi_ovs = parseFloat(document.getElementById('rsi_ovs').value) || 0;
        const rsi_ovb = parseFloat(document.getElementById('rsi_ovb').value) || 0;
        const ovs_input = document.getElementById('rsi_ovs');
        const ovb_input = document.getElementById('rsi_ovb');

        if (rsi_ovs >= rsi_ovb) {
            ovs_input.setCustomValidity('RSI Oversold must be less than RSI Overbought');
            ovb_input.setCustomValidity('RSI Overbought must be greater than RSI Oversold');
            return false;
        } else {
            ovs_input.setCustomValidity('');
            ovb_input.setCustomValidity('');
            return true;
        }
    }

    // Validate TP/SL values when enabled
    function validateTPSL() { /* ... */ }

    // Validate base position percentage
    function validateBasePosition() { /* ... */ }

    // Validate pyramiding
    function validatePyramiding() { /* ... */ }

    // Add event listeners for real-time validation
    ['rsi_ovs', 'rsi_ovb'].forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener('input', validateRSI);
            el.addEventListener('blur', validateRSI);
        }
    });

    // Form submit validation
    form.addEventListener('submit', function(e) {
        const valid = validateRSI() && validateTPSL() &&
                      validateBasePosition() && validatePyramiding();

        if (!valid) {
            e.preventDefault();
            alert('Please fix validation errors before saving the strategy.');
            return false;
        }
    });

    // Run initial validation
    validateRSI();
    validateTPSL();
    validateBasePosition();
    validatePyramiding();
})();
```

**Результат:**
- **Мгновенная обратная связь** при вводе параметров
- Использует нативную браузерную валидацию (`setCustomValidity`)
- Подсвечивает некорректные поля
- Блокирует отправку формы при наличии ошибок
- Запускается автоматически при загрузке страницы

---

### 3. ✅ Добавлены подсказки в UI

**strategy_form.html** (строки 86, 92):

```html
<div class="form-group">
    <label for="rsi_ovb">RSI Overbought</label>
    <input type="number" id="rsi_ovb" name="rsi_ovb" value="{{ config.get('rsi_ovb', 70) }}"
           min="0" max="100" required>
    <small class="help-text" style="color: #6b7280;">Must be greater than RSI Oversold</small>
</div>

<div class="form-group">
    <label for="rsi_ovs">RSI Oversold</label>
    <input type="number" id="rsi_ovs" name="rsi_ovs" value="{{ config.get('rsi_ovs', 30) }}"
           min="0" max="100" required>
    <small class="help-text" style="color: #6b7280;">Must be less than RSI Overbought</small>
</div>
```

**Результат:**
- Визуальные подсказки под каждым полем
- Понятное объяснение требований

---

## Покрытие валидации

### ✅ Параметры с полной валидацией

| Параметр | UI Валидация | API Валидация | Dataclass Валидация |
|----------|--------------|---------------|---------------------|
| `rsi_ovs < rsi_ovb` | ✅ JavaScript | ✅ ui_save_strategy()<br>✅ ui_recalculate_backtest() | ✅ IndicatorStrategyConfig |
| `time_filter hours [0-23]` | ❌ (HTML min/max) | ✅ ui_save_strategy()<br>✅ ui_recalculate_backtest() | ✅ IndicatorStrategyConfig |
| `tp/sl > 0` | ✅ JavaScript | ✅ ui_save_strategy()<br>✅ ui_recalculate_backtest() | ✅ IndicatorStrategyConfig |
| `pyramiding >= 1` | ✅ JavaScript | ✅ ui_save_strategy()<br>✅ ui_recalculate_backtest() | ✅ IndicatorStrategyConfig |
| `base_position_pct [0-100]` | ✅ JavaScript | ✅ ui_save_strategy()<br>✅ ui_recalculate_backtest() | ✅ IndicatorStrategyConfig |

**Итого:** 3 уровня защиты от некорректных параметров!

---

## Тестирование

### Сценарий 1: RSI ovs >= ovb (ваша ошибка)

**Действие:**
```
1. Открыть стратегию в UI
2. Установить RSI Oversold = 30, RSI Overbought = 20 (некорректно!)
3. Нажать "Recalculate"
```

**БЫЛО:**
```
Error: Recalculate failed: rsi_ovs must be < rsi_ovb, got ovs=30, ovb=20
(ошибка из IndicatorStrategyConfig после запуска бэктеста)
```

**СТАЛО:**

**UI Уровень (мгновенно при вводе):**
```
Browser validation:
  RSI Oversold field: "RSI Oversold must be less than RSI Overbought"
  RSI Overbought field: "RSI Overbought must be greater than RSI Oversold"
```

**API Уровень (если обойти UI):**
```json
{
  "detail": "RSI Oversold must be less than RSI Overbought. Got ovs=30, ovb=20"
}
HTTP 400 Bad Request
```

---

### Сценарий 2: Negative TP/SL

**Действие:**
```
1. Включить Enable TP/SL
2. Установить TP Long % = -5
3. Попытаться сохранить
```

**СТАЛО:**

**UI Уровень:**
```
Browser validation:
  TP Long % field: "TP Long % must be greater than 0"
Form submit blocked!
```

**API Уровень:**
```json
{
  "detail": "TP Long % must be greater than 0, got -5.0"
}
HTTP 400 Bad Request
```

---

### Сценарий 3: Invalid Time Filter

**Действие:**
```
1. Включить Enable Time Filter
2. Установить Start Hour = 25 (некорректно!)
3. Попытаться сохранить
```

**СТАЛО:**

**HTML Валидация:**
```html
<input type="number" min="0" max="23">
(браузер не позволит ввести 25)
```

**API Уровень (если обойти HTML):**
```json
{
  "detail": "time_filter_start_hour must be in [0, 23], got 25"
}
HTTP 400 Bad Request
```

---

## Сравнение: ДО и ПОСЛЕ

| Аспект | ДО | ПОСЛЕ |
|--------|-----|-------|
| **Обнаружение ошибки** | При создании IndicatorStrategyConfig | Сразу при вводе в UI / на уровне API |
| **Сообщение об ошибке** | Техническое, из Python traceback | Понятное, с фактическими значениями |
| **Время обратной связи** | После отправки формы + запуска бэктеста | Мгновенно при вводе |
| **Блокировка некорректных данных** | Нет (только exception) | 3 уровня защиты |
| **UX** | Плохой (ошибка после долгого ожидания) | Отличный (мгновенная обратная связь) |

---

## Итоговая архитектура валидации

```
┌─────────────────────────────────────────────────────────────────┐
│                         USER INPUT                               │
└─────────────────────────┬───────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Level 1: HTML Validation                       │
│  • <input min="0" max="100">                                    │
│  • <input min="0" max="23">                                     │
│  • required, step, type="number"                                │
└─────────────────────────┬───────────────────────────────────────┘
                          │ (can be bypassed)
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                Level 2: JavaScript Validation                    │
│  • Real-time validation on input/blur                           │
│  • setCustomValidity() for native browser UI                    │
│  • Form submit prevention                                       │
│  • Clear error messages                                         │
└─────────────────────────┬───────────────────────────────────────┘
                          │ (can be bypassed via curl/API)
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Level 3: API Validation                        │
│  ui_save_strategy() [ui_routes.py:549-605]                      │
│  ui_recalculate_backtest() [ui_routes.py:1563-1611]             │
│                                                                  │
│  • Validates ALL logical relationships                          │
│  • HTTPException 400 with clear messages                        │
│  • Happens BEFORE expensive operations                          │
└─────────────────────────┬───────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│              Level 4: Dataclass Validation                       │
│  IndicatorStrategyConfig.__post_init__() [configs.py:84-162]    │
│                                                                  │
│  • Final validation before strategy creation                    │
│  • Comprehensive checks (already existed)                       │
│  • Raises ValueError with details                               │
└─────────────────────────┬───────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                    STRATEGY CREATED ✅                           │
└─────────────────────────────────────────────────────────────────┘
```

---

## Что теперь работает правильно

### ✅ Edit Strategy Parameters
- Все параметры редактируются через UI
- Валидация мгновенная и понятная
- Параметры не теряются при сохранении
- Time Filter полностью функционален

### ✅ Recalculate Backtest
- Валидация **ДО** запуска бэктеста
- Понятные сообщения об ошибках
- Не тратится время на некорректные параметры

### ✅ Trades Table
- Обновляется корректно
- Нет ошибок из-за некорректных параметров
- Стратегия работает с правильными настройками

---

## Рекомендации для пользователя

### 1. Проверьте существующие стратегии
```bash
# Убедитесь, что RSI параметры корректны
# ovs должно быть < ovb (например: ovs=30, ovb=70)
```

### 2. Используйте подсказки в UI
- Читайте help-text под полями
- Браузер покажет ошибки при некорректном вводе
- Форма не отправится, пока все параметры не будут валидны

### 3. Типичные значения параметров

**RSI:**
- Oversold: 20-35 (типично 30)
- Overbought: 65-80 (типично 70)
- **ВАЖНО:** ovs всегда должно быть < ovb

**Time Filter:**
- Часы в UTC (0-23)
- Поддерживается wrap-around (22-6 = ночная торговля)

**TP/SL:**
- Всегда > 0 если использование включено
- Типично 1-5% для крипторынка

**Position Sizing:**
- base_position_pct: 5-20% (консервативно)
- pyramiding: 1-3 (избегайте больших значений)

---

## Коммиты

1. **`20dfacf`** - "🐛 CRITICAL FIX: Add missing Time Filter UI fields and API processing"
   - Добавлены поля time_filter в UI
   - Добавлена обработка в ui_save_strategy()
   - Исправлена потеря параметров

2. **`3d59370`** - "✅ Add comprehensive parameter validation at all levels"
   - Валидация RSI, TP/SL, pyramiding, base_position
   - JavaScript real-time валидация
   - API level валидация в обоих endpoints

---

## Файлы изменены

- ✅ `llm_trading_system/api/templates/strategy_form.html`
  - Добавлена секция Time Filter
  - Добавлен JavaScript валидатор
  - Добавлены help-text подсказки

- ✅ `llm_trading_system/api/ui_routes.py`
  - Валидация в ui_save_strategy()
  - Валидация в ui_recalculate_backtest()
  - Time filter параметры в обеих функциях

---

## Заключение

**Все проблемы исправлены:**

1. ✅ Time Filter поля добавлены в UI
2. ✅ Time Filter параметры обрабатываются при сохранении
3. ✅ RSI валидация работает на всех уровнях
4. ✅ Все логические связи параметров проверяются
5. ✅ Мгновенная обратная связь в UI
6. ✅ Понятные сообщения об ошибках

**Теперь система:**
- Предотвращает ввод некорректных параметров
- Дает мгновенную обратную связь
- Защищает на 3 уровнях (HTML → JS → API → Dataclass)
- Не тратит время на запуск бэктестов с невалидными параметрами

---

**Готово к использованию!** 🚀

Ветка: `claude/test-strategy-parameters-0132uZX1TQR9tsNfWohFvXqN`
