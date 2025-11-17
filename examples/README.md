# Examples / Примеры

Эта директория содержит примеры стратегий и скрипты для их запуска.

## Night Cat Samurai Strategy

**Файлы**:
- `night_cat_samurai_strategy.json` — конфигурация стратегии "ETH-5m ОХОТА НОЧНОГО КОТА САМУРАЯ"
- `run_night_cat_samurai.py` — скрипт для запуска бэктеста

### Описание стратегии

Индикаторная стратегия с следующими характеристиками:

- **Индикаторы**: RSI, Bollinger Bands, Volume MA
- **Временной фильтр**: торговля только с 00:00 до 07:00 UTC
- **Вход в лонг**: RSI < 22 AND low <= нижняя полоса BB AND volume > vol_ma * 0.5
- **Вход в шорт**: RSI > 80 AND high >= верхняя полоса BB AND volume > vol_ma * 0.5
- **Пирамидинг**: до 4 позиций
- **Мартингейл**: множитель 1.5 (размер позиции растет как 1, 1.5, 2.25, 3.375...)
- **TP/SL**: 2% для лонгов и шортов

### Как запустить

1. Подготовьте данные:
   ```bash
   # Создайте директорию для данных
   mkdir -p data

   # Поместите туда CSV файл с данными ETHUSDT 5m
   # Формат: timestamp,open,high,low,close,volume
   ```

2. Запустите бэктест:
   ```bash
   python examples/run_night_cat_samurai.py
   ```

3. Результат будет выведен в консоль:
   ```
   Loading strategy: eth_5m_night_cat_samurai
   Symbol: ETHUSDT
   Pyramiding: 4
   Martingale multiplier: 1.5

   Running backtest...

   ============================================================
   BACKTEST RESULTS
   ============================================================
   Final equity:     $12,345.67
   Total return:     23.46%
   Max drawdown:     -8.92%
   Number of trades: 42
   ...
   ```

### Адаптация для других стратегий

Вы можете использовать этот пример как шаблон:

1. Скопируйте `night_cat_samurai_strategy.json` → `my_strategy.json`
2. Измените параметры:
   - `rsi_len`, `bb_len`, `bb_mult`, `vol_ma_len`, `vol_mult`
   - `pyramiding`, `martingale_mult`
   - `tp_long_pct`, `sl_long_pct`, etc.
3. Измените правила в секции `rules`:
   - `long_entry`, `short_entry`
   - `long_exit`, `short_exit` (если нужны правила выхода помимо TP/SL)
4. Обновите `run_night_cat_samurai.py` для загрузки вашего конфига

### Дополнительная документация

См. [STRATEGIES.md](../STRATEGIES.md) для полного руководства по созданию индикаторных стратегий.
