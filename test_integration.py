"""Integration test for position sizing module."""

from position_sizing import compute_position_multipliers

# Тестовый LLM output
llm_output = {
    "prob_bull": 0.65,
    "prob_bear": 0.35,
    "scores": {
        "btc_sentiment": 0.4,
        "onchain_pressure": 0.2,
        "trend_strength": 0.7,
        "liquidity_risk": 0.3,
        "news_risk": 0.2,
        "global_sentiment": 0.3,
        "altcoin_sentiment": 0.2,
    }
}

# Расчёт
pos_size, k_long, k_short = compute_position_multipliers(
    llm_output,
    side="long",
    base_long_size=0.01,
    base_short_size=0.01,
    k_max=2.0
)

print(f"Position size: {pos_size:.6f}")
print(f"Long multiplier: {k_long:.4f}")
print(f"Short multiplier: {k_short:.4f}")

# Проверки
assert k_long > 1.0, "В бычьем режиме k_long должен быть > 1.0"
assert k_short < 1.0, "В бычьем режиме k_short должен быть < 1.0"
assert abs(pos_size - 0.01 * k_long) < 1e-10, "Position size должен равняться base_size * k"
assert 0 <= k_long <= 2.0, "k_long должен быть в пределах [0, k_max]"
assert 0 <= k_short <= 2.0, "k_short должен быть в пределах [0, k_max]"

print("\n✅ Все проверки пройдены!")
print("\nДетальные результаты:")
print(f"  - Режим: Бычий (prob_bull={llm_output['prob_bull']})")
print(f"  - Множитель для длинных позиций увеличен на {(k_long - 1.0) * 100:.1f}%")
print(f"  - Множитель для коротких позиций уменьшен на {(1.0 - k_short) * 100:.1f}%")
print(f"  - Итоговая позиция для LONG: {pos_size:.6f} (= {pos_size * 100:.2f}% капитала)")
