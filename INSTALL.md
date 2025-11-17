# Быстрая установка / Quick Installation

## Русский

### Требования
- Python 3.12 или выше
- pip (менеджер пакетов Python)

### Установка

1. **Клонируйте репозиторий**:
   ```bash
   git clone https://github.com/Lje3apb/LLM_traiding_system.git
   cd LLM_traiding_system
   ```

2. **Создайте виртуальное окружение** (рекомендуется):
   ```bash
   python -m venv venv

   # Windows
   venv\Scripts\activate

   # Linux/Mac
   source venv/bin/activate
   ```

3. **Установите зависимости**:
   ```bash
   pip install -r requirements.txt
   ```

   Или установите пакет в режиме разработки:
   ```bash
   pip install -e .
   ```

### Проверка установки

Запустите сервер API:
```bash
python -m llm_trading_system.api.server
```

Откройте браузер: http://localhost:8000

Документация API: http://localhost:8000/docs

### Запуск примера стратегии

```bash
# Убедитесь, что у вас есть данные в data/ETHUSDT_5m.csv
python examples/run_night_cat_samurai.py
```

### Устранение проблем

**ModuleNotFoundError: No module named 'fastapi'**

Решение: Установите зависимости через pip:
```bash
pip install -r requirements.txt
```

**ModuleNotFoundError: No module named 'numpy'** или **'pandas'**

Решение: Убедитесь, что установлены все зависимости:
```bash
pip install numpy pandas
```

---

## English

### Requirements
- Python 3.12 or higher
- pip (Python package manager)

### Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/Lje3apb/LLM_traiding_system.git
   cd LLM_traiding_system
   ```

2. **Create virtual environment** (recommended):
   ```bash
   python -m venv venv

   # Windows
   venv\Scripts\activate

   # Linux/Mac
   source venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

   Or install in development mode:
   ```bash
   pip install -e .
   ```

### Verify Installation

Run the API server:
```bash
python -m llm_trading_system.api.server
```

Open browser: http://localhost:8000

API documentation: http://localhost:8000/docs

### Run Example Strategy

```bash
# Make sure you have data in data/ETHUSDT_5m.csv
python examples/run_night_cat_samurai.py
```

### Troubleshooting

**ModuleNotFoundError: No module named 'fastapi'**

Solution: Install dependencies via pip:
```bash
pip install -r requirements.txt
```

**ModuleNotFoundError: No module named 'numpy'** or **'pandas'**

Solution: Make sure all dependencies are installed:
```bash
pip install numpy pandas
```
