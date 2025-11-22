# ✅ ИСПРАВЛЕНО: Checkbox контролы и параметры Martingale/TP/SL

**Дата:** 2025-11-22
**Статус:** ✅ **ПОЛНОСТЬЮ ИСПРАВЛЕНО**

---

## 🚨 Проблемы

### 1. Ошибка валидации при использовании модального окна

```
Error: Recalculate failed: martingale_mult must be >= 1.0, got 0.0
```

**Когда возникала:**
- При редактировании через всплывающее окно "Edit Strategy Parameters"
- Когда checkbox "Use Martingale" был выключен
- Значение 0.0 передавалось вместо корректного дефолтного значения

### 2. Checkbox не управляли видимостью полей

**В основной форме (`/ui/strategies/*/edit`):**
- ✅ Time Filter checkbox работал (уже был исправлен)
- ❌ Use Martingale checkbox не скрывал поле Martingale Multiplier
- ❌ Enable TP/SL checkbox не скрывал поля TP/SL

**В модальном окне:**
- ❌ Все checkbox не управляли видимостью связанных полей
- ❌ Поля всегда были видимы

### 3. Martingale Multiplier не влиял на торговлю

**На самом деле ВЛИЯЕТ!** Пользователь мог не заметить эффект из-за других проблем.

---

## ✅ Исправления

### Исправление 1: Основная форма редактирования

**Файл:** `llm_trading_system/api/templates/strategy_form.html`

**Что сделано:**

1. **Реструктурирован HTML для Martingale:**
```html
<!-- БЫЛО: поле всегда видимо -->
<div class="form-row">
    <div class="form-group">
        <input type="checkbox" name="use_martingale"> Use Martingale
    </div>
    <div class="form-group">
        <input type="number" name="martingale_mult"> Martingale Multiplier
    </div>
</div>

<!-- СТАЛО: checkbox управляет видимостью -->
<div class="form-group">
    <input type="checkbox" id="use_martingale" name="use_martingale"> Use Martingale
</div>
<div id="martingale_settings" style="display: none;">
    <input type="number" name="martingale_mult"> Martingale Multiplier
</div>
```

2. **Реструктурирован HTML для TP/SL:**
```html
<!-- Checkbox сначала -->
<div class="form-group">
    <input type="checkbox" id="use_tp_sl" name="use_tp_sl"> Enable TP/SL
</div>

<!-- Потом все поля в контейнере -->
<div id="tp_sl_settings" style="display: none;">
    <div class="form-row">...</div>
    <div class="form-row">...</div>
</div>
```

3. **Универсальный JavaScript для всех checkbox:**
```javascript
function setupCheckboxToggle(checkboxId, settingsId, displayStyle) {
    // Generic toggle function
}

setupCheckboxToggle('use_martingale', 'martingale_settings', 'flex');
setupCheckboxToggle('use_tp_sl', 'tp_sl_settings', 'block');
setupCheckboxToggle('time_filter_enabled', 'time_filter_settings', 'flex');
```

4. **Валидация TP/SL очищает ошибки:**
```javascript
function validateTPSL() {
    if (!use_tp_sl) {
        // Clear all validation errors
        ['tp_long_pct', 'sl_long_pct', ...].forEach(id => {
            el.setCustomValidity('');
        });
        return true;
    }
    // ... validate only when enabled
}
```

**Commit:** `0c59378` - "✅ Fix checkbox controls for Martingale and TP/SL settings"

---

### Исправление 2: Модальное окно

**Файл:** `llm_trading_system/api/templates/backtest_result.html`

**Проблема в collectFormParams():**
```javascript
// БЫЛО: пустые значения → 0
params[key] = parseFloat(value) || 0;  // ❌ martingale_mult: NaN → 0
```

**Решение 1: Система дефолтных значений**
```javascript
// СТАЛО: правильные значения по умолчанию
const defaults = {
    'martingale_mult': 1.5,  // ✅ Вместо 0
    'tp_long_pct': 2.0,
    'sl_long_pct': 2.0,
    // ... все числовые поля
};

params[key] = isNaN(parsedValue) ? (defaults[key] || 0) : parsedValue;
```

**Решение 2: Реструктуризация HTML**

Martingale:
```html
<div class="param-group">
    <input type="checkbox" id="param_use_martingale"> Use Martingale
</div>
<div id="param_martingale_settings" style="display: none;">
    <input type="number" id="param_martingale_mult"> Martingale Multiplier
</div>
```

TP/SL:
```html
<div class="param-group">
    <input type="checkbox" id="param_use_tp_sl"> Use TP/SL
</div>
<div id="param_tp_sl_settings" style="display: none;">
    <div class="param-grid">
        <!-- Все 4 поля TP/SL -->
    </div>
</div>
```

Time Filter: (аналогично)

**Решение 3: JavaScript управление видимостью**
```javascript
function toggleModalCheckboxSettings() {
    // Martingale
    const useMartingale = document.getElementById('param_use_martingale').checked;
    document.getElementById('param_martingale_settings').style.display =
        useMartingale ? 'block' : 'none';

    // TP/SL
    const useTpSl = document.getElementById('param_use_tp_sl').checked;
    document.getElementById('param_tp_sl_settings').style.display =
        useTpSl ? 'block' : 'none';

    // Time Filter
    const timeFilterEnabled = document.getElementById('param_time_filter_enabled').checked;
    document.getElementById('param_time_filter_settings').style.display =
        timeFilterEnabled ? 'block' : 'none';
}

// Event listeners
document.getElementById('param_use_martingale').addEventListener('change', toggleModalCheckboxSettings);
document.getElementById('param_use_tp_sl').addEventListener('change', toggleModalCheckboxSettings);
document.getElementById('param_time_filter_enabled').addEventListener('change', toggleModalCheckboxSettings);

// Update on form load
function populateForm(params) {
    // ... load all values ...
    toggleModalCheckboxSettings();  // ← Update visibility
}
```

**Commit:** `2e75ca3` - "🔧 Fix modal checkbox controls and default values for martingale/TP/SL"

---

## 📊 Как работает Martingale Multiplier

### Код использования (indicator_strategy.py:303)

```python
def _position_size(self, step: int) -> float:
    base_fraction = self._base_position_fraction()

    if self.config.use_martingale:
        size = base_fraction * (self.config.martingale_mult ** step)
    else:
        size = base_fraction

    size = min(size, self.config.max_position_size)
    return size
```

### Пример влияния параметра

**Base Position:** 10% от капитала

**Martingale Multiplier = 1.5:**
```
Step 0 (1st entry): 10% * 1.5^0 = 10%
Step 1 (2nd entry): 10% * 1.5^1 = 15%
Step 2 (3rd entry): 10% * 1.5^2 = 22.5%
```

**Martingale Multiplier = 2.0:**
```
Step 0 (1st entry): 10% * 2.0^0 = 10%  (одинаково)
Step 1 (2nd entry): 10% * 2.0^1 = 20%  (больше!)
Step 2 (3rd entry): 10% * 2.0^2 = 40%  (намного больше!)
```

**Вывод:** Изменение `martingale_mult` **СИЛЬНО влияет** на размер последующих позиций!

---

## 🧪 Как проверить что всё работает

### Тест 1: Checkbox в основной форме

1. Открыть: `/ui/strategies/night_cat_samurai_strategy/edit`
2. Снять галочку "Use Martingale" → поле Martingale Multiplier исчезает
3. Поставить галочку → поле появляется
4. Снять галочку "Enable TP/SL" → 4 поля TP/SL исчезают
5. Поставить галочку → поля появляются
6. Сохранить стратегию → всё работает без ошибок ✅

---

### Тест 2: Checkbox в модальном окне

1. Открыть backtest результат стратегии
2. Нажать кнопку "Edit Strategy Parameters" (открывается модальное окно)
3. **Use Martingale:**
   - Снять галочку → поле Martingale Multiplier исчезает
   - Поставить галочку → поле появляется с значением 1.5
4. **Enable TP/SL:**
   - Снять галочку → все 4 поля TP/SL исчезают
   - Поставить галочку → поля появляются
5. **Enable Time Filter:**
   - Снять галочку → поля часов исчезают
   - Поставить галочку → поля появляются
6. Нажать "Recalculate" → **НЕТ ошибки "got 0.0"** ✅

---

### Тест 3: Влияние Martingale Multiplier на торговлю

**Предварительное условие:**
- Стратегия должна генерировать больше 1 сделки на одной стороне (long или short)
- Пример: стратегия с частыми входами или с pyramiding > 1

**Шаги:**

1. **Тест с martingale_mult = 1.5:**
```
1. Открыть Edit Strategy Parameters
2. Включить "Use Martingale"
3. Установить Martingale Multiplier = 1.5
4. Нажать Recalculate
5. Посмотреть на Trades таблицу
6. Записать размеры последовательных позиций (qty)
```

2. **Тест с martingale_mult = 2.0:**
```
1. Изменить Martingale Multiplier = 2.0
2. Нажать Recalculate
3. Посмотреть на Trades таблицу
4. Сравнить размеры позиций
```

**Ожидаемый результат:**
```
При mult=1.5:
Trade 1: qty=0.001 BTC
Trade 2: qty=0.0015 BTC  (0.001 * 1.5)
Trade 3: qty=0.00225 BTC (0.001 * 1.5^2)

При mult=2.0:
Trade 1: qty=0.001 BTC
Trade 2: qty=0.002 BTC   (0.001 * 2.0)  ← БОЛЬШЕ!
Trade 3: qty=0.004 BTC   (0.001 * 2.0^2) ← НАМНОГО БОЛЬШЕ!
```

**Если размеры одинаковые:**
- Проверьте что "Use Martingale" включен ✅
- Проверьте что pyramiding > 1
- Проверьте что стратегия делает несколько входов подряд

---

### Тест 4: Отключение Martingale

1. Снять галочку "Use Martingale"
2. Recalculate
3. Все позиции должны быть одинакового размера (base_position_pct)

```
Trade 1: qty=0.001 BTC
Trade 2: qty=0.001 BTC  (одинаковые!)
Trade 3: qty=0.001 BTC  (одинаковые!)
```

---

## 📁 Коммиты

### Основная форма
- **0c59378** - ✅ Fix checkbox controls for Martingale and TP/SL settings
  - Файл: `llm_trading_system/api/templates/strategy_form.html`
  - Реструктуризация HTML
  - Универсальный JavaScript для checkbox
  - Очистка валидации при выключении checkbox

### Модальное окно
- **2e75ca3** - 🔧 Fix modal checkbox controls and default values for martingale/TP/SL
  - Файл: `llm_trading_system/api/templates/backtest_result.html`
  - Система дефолтных значений (martingale_mult: 1.5 вместо 0)
  - Реструктуризация HTML модального окна
  - toggleModalCheckboxSettings() функция

---

## 🎯 Итоги

### ✅ Что работает сейчас

1. **Основная форма:**
   - ✅ Use Martingale checkbox скрывает/показывает Martingale Multiplier
   - ✅ Enable TP/SL checkbox скрывает/показывает все поля TP/SL
   - ✅ Enable Time Filter checkbox скрывает/показывает поля времени
   - ✅ Валидация работает только для включенных функций

2. **Модальное окно:**
   - ✅ Все checkbox управляют видимостью связанных полей
   - ✅ Дефолтные значения корректные (martingale_mult = 1.5)
   - ✅ НЕТ ошибки "martingale_mult must be >= 1.0, got 0.0"
   - ✅ Recalculate работает без ошибок

3. **Функциональность:**
   - ✅ Martingale Multiplier **РЕАЛЬНО ВЛИЯЕТ** на размер позиций
   - ✅ Формула: `size = base * (martingale_mult ** step)`
   - ✅ Разные значения mult → разные размеры позиций
   - ✅ Можно тестировать разные стратегии мартингейла

### 📊 UI/UX улучшения

- **До:** Все поля всегда видимы, неиспользуемые функции мешают
- **После:** Только релевантные поля показаны, чище и понятнее
- **До:** Ошибки валидации для выключенных функций
- **После:** Валидация только для включенных функций
- **До:** Непонятно какие параметры влияют на торговлю
- **После:** Ясная связь между checkbox и параметрами

---

## 🔗 Связанные документы

- **PARAMETER_EVALUATION_FIX.md** - Исправление оценки параметров в правилах
- **USING_PARAMETERS_IN_RULES.md** - Использование параметров в правилах
- **VALIDATION_FIX_SUMMARY.md** - Валидация на всех уровнях

---

**Всё готово к использованию!** 🚀
