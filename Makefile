.PHONY: help build up down test clean run-position run-market run-integration logs shell

# Default target
help:
	@echo "LLM Trading System - Makefile Commands"
	@echo ""
	@echo "Основные команды:"
	@echo "  make build            - Собрать Docker образ"
	@echo "  make up               - Запустить контейнер (position sizing)"
	@echo "  make down             - Остановить и удалить контейнеры"
	@echo "  make test             - Запустить unit-тесты"
	@echo "  make run-integration  - Запустить интеграционный тест"
	@echo "  make run-position     - Запустить примеры position sizing"
	@echo "  make run-market       - Запустить market snapshot (требуются API ключи)"
	@echo "  make logs             - Показать логи контейнера"
	@echo "  make shell            - Открыть shell в контейнере"
	@echo "  make clean            - Очистить контейнеры и образы"
	@echo ""
	@echo "Локальные команды (без Docker):"
	@echo "  make local-test       - Запустить тесты локально"
	@echo "  make local-run        - Запустить position sizing локально"
	@echo "  make local-integration - Запустить интеграционный тест локально"
	@echo ""
	@echo "Утилиты:"
	@echo "  make setup            - Создать .env из .env.example"
	@echo "  make check-env        - Проверить переменные окружения"

# Docker commands
build:
	docker-compose build

up:
	docker-compose up

up-d:
	docker-compose up -d

down:
	docker-compose down

test:
	docker-compose --profile test up test

run-position:
	docker-compose run --rm llm-trading python -m llm_trading_system.core.position_sizing

run-market:
	docker-compose --profile market up market-snapshot

run-integration:
	docker-compose run --rm llm-trading python -m llm_trading_system.cli.full_cycle_cli

logs:
	docker-compose logs -f

shell:
	docker-compose run --rm llm-trading /bin/bash

clean:
	docker-compose down -v
	docker-compose rm -f
	@echo "Очистка завершена"

# Local commands (without Docker)
local-test:
	python -m pytest tests/ -v

local-run:
	python -m llm_trading_system.core.position_sizing

local-integration:
	python -m llm_trading_system.cli.full_cycle_cli

local-market:
	python -m llm_trading_system.core.market_snapshot

# Setup commands
setup:
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "✅ Файл .env создан из .env.example"; \
		echo "⚠️  Отредактируйте .env и добавьте свои API ключи"; \
	else \
		echo "⚠️  Файл .env уже существует"; \
	fi

check-env:
	@echo "Проверка переменных окружения:"
	@if [ -f .env ]; then \
		echo "✅ .env файл найден"; \
		echo ""; \
		echo "BASE_ASSET: $$(grep ^BASE_ASSET .env | cut -d '=' -f2)"; \
		echo "HORIZON_HOURS: $$(grep ^HORIZON_HOURS .env | cut -d '=' -f2)"; \
		echo "CRYPTOQUANT_API_KEY: $$(if [ -n \"$$(grep ^CRYPTOQUANT_API_KEY .env | cut -d '=' -f2)\" ]; then echo \"установлен\"; else echo \"не установлен\"; fi)"; \
		echo "CRYPTOPANIC_API_KEY: $$(if [ -n \"$$(grep ^CRYPTOPANIC_API_KEY .env | cut -d '=' -f2)\" ]; then echo \"установлен\"; else echo \"не установлен\"; fi)"; \
		echo "NEWSAPI_KEY: $$(if [ -n \"$$(grep ^NEWSAPI_KEY .env | cut -d '=' -f2)\" ]; then echo \"установлен\"; else echo \"не установлен\"; fi)"; \
	else \
		echo "❌ .env файл не найден"; \
		echo "Запустите: make setup"; \
	fi

# Quick start
quickstart: setup build test
	@echo ""
	@echo "✅ Быстрый старт завершён!"
	@echo ""
	@echo "Следующие шаги:"
	@echo "  1. Отредактируйте .env и добавьте API ключи (опционально)"
	@echo "  2. Запустите: make up"
	@echo "  или"
	@echo "  2. Запустите: make local-run"
