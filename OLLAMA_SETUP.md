# Инструкция по проверке llm_infra с Ollama

## Шаг 1: Убедитесь, что Ollama установлена

```bash
ollama --version
```

Если команда не найдена, установите Ollama:
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

## Шаг 2: Запустите сервис Ollama

Ollama работает как локальный сервер. Запустите его:

```bash
ollama serve
```

Или в фоновом режиме:
```bash
nohup ollama serve > ollama.log 2>&1 &
```

## Шаг 3: Загрузите модель

Выберите и загрузите модель (рекомендуем начать с маленькой):

```bash
# Маленькая и быстрая модель (~1.5GB)
ollama pull llama3.2

# Или другие модели:
ollama pull mistral        # ~4GB
ollama pull llama2         # ~4GB
ollama pull phi            # ~1.6GB
```

Проверьте список доступных моделей:
```bash
ollama list
```

## Шаг 4: Проверьте, что API работает

```bash
curl http://localhost:11434/api/tags
```

Должен вернуть JSON со списком моделей.

## Шаг 5: Запустите тестовый скрипт

```bash
cd /home/user/LLM_traiding_system
python3 test_ollama.py
```

### Возможные проблемы:

**Проблема**: `Connection refused`
**Решение**: Убедитесь, что `ollama serve` запущен

**Проблема**: `model not found`
**Решение**: Загрузите модель с помощью `ollama pull <model_name>`

**Проблема**: Медленная работа
**Решение**: Используйте меньшую модель (llama3.2, phi) или увеличьте timeout в коде

## Шаг 6: Используйте в своём коде

Минимальный пример:

```python
from llm_infra import OllamaProvider

# Создайте провайдер
provider = OllamaProvider(
    base_url="http://localhost:11434",
    model="llama3.2",  # используйте вашу модель
    timeout=120
)

# Получите ответ
response = provider.complete(
    system_prompt="You are a helpful assistant.",
    user_prompt="What is machine learning?",
    temperature=0.0
)

print(response)
```

С использованием клиента и retry:

```python
from llm_infra import OllamaProvider, LLMClientSync, RetryPolicy

provider = OllamaProvider(model="llama3.2")
retry_policy = RetryPolicy(max_retries=3, base_delay=1.0)
client = LLMClientSync(provider=provider, retry_policy=retry_policy)

response = client.complete(
    system_prompt="You are a helpful assistant.",
    user_prompt="Explain Python in one sentence.",
    temperature=0.3
)

print(response)
```

## Полезные команды Ollama

```bash
# Список доступных моделей на ollama.com
ollama list

# Удалить модель
ollama rm llama3.2

# Информация о модели
ollama show llama3.2

# Интерактивный чат с моделью
ollama run llama3.2
```

## Рекомендуемые модели по размеру

| Модель | Размер | Описание |
|--------|--------|----------|
| phi | ~1.6GB | Очень быстрая, подходит для простых задач |
| llama3.2 | ~2GB | Балансирует скорость и качество |
| mistral | ~4GB | Хорошее качество, средняя скорость |
| llama2 | ~4GB | Классическая модель Meta |
| llama3 | ~4.7GB | Улучшенная версия |

Выбирайте модель в зависимости от доступной RAM и требуемого качества ответов.
