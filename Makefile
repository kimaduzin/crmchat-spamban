# Короткие алиасы для частых команд.
#
# Под капотом всё ровно то же, что в README — Makefile просто
# делает короче запуски и автоматически подгружает .env.

PY := ./venv/bin/python

.PHONY: help setup verify list one check check-dry clean

help:
	@echo "spamban — доступные команды:"
	@echo "  make setup       — поставить venv, зависимости и заполнить .env"
	@echo "  make verify      — smoke-test всех кредов"
	@echo "  make list        — таблица аккаунтов воркспейса"
	@echo "  make one         — проверить ОДИН аккаунт (первый active)"
	@echo "  make one Q=@user — проверить аккаунт по username / phone / id"
	@echo "  make check       — полная проверка с алертами в Telegram"
	@echo "  make check-dry   — проверка без отправки /start, только чтение"
	@echo "  make clean       — удалить venv и __pycache__"

setup:
	./setup.sh

# Все runtime-команды грузят .env автоматом.
# В Makefile env берётся через подстановку $$(...), а не через include —
# чтобы не падать, если .env пока нет.

verify:
	@set -a; [ -f .env ] && . ./.env; set +a; \
		$(PY) verify.py

list:
	@set -a; [ -f .env ] && . ./.env; set +a; \
		$(PY) list_accounts.py

one:
	@set -a; [ -f .env ] && . ./.env; set +a; \
		$(PY) check_one.py $(Q)

check:
	@set -a; [ -f .env ] && . ./.env; set +a; \
		SPAMBAN_RUN_LABEL=$${SPAMBAN_RUN_LABEL:-manual} \
		$(PY) check.py

check-dry:
	@set -a; [ -f .env ] && . ./.env; set +a; \
		SPAMBAN_RUN_LABEL=$${SPAMBAN_RUN_LABEL:-dry} \
		SPAMBAN_DRY_RUN=1 \
		SPAMBAN_WINDOW_MINUTES=$${SPAMBAN_WINDOW_MINUTES:-1} \
		$(PY) check.py

clean:
	rm -rf venv __pycache__ */__pycache__
