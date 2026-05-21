#!/usr/bin/env bash
# Установщик spamban:
#   1. Проверяет Python 3.9+
#   2. Создаёт venv в ./venv
#   3. Ставит зависимости из requirements.txt
#   4. Запускает интерактивный мастер настройки .env
#
# Запуск:
#   chmod +x setup.sh
#   ./setup.sh
#
# Идемпотентен — можно запускать повторно, чтобы переподнять .env.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

GREEN='\033[32m'; YELLOW='\033[33m'; RED='\033[31m'; CYAN='\033[36m'; BOLD='\033[1m'; RESET='\033[0m'

info()  { printf '%b ℹ  %s%b\n' "$CYAN"   "$*" "$RESET"; }
ok()    { printf '%b ✓  %s%b\n' "$GREEN"  "$*" "$RESET"; }
warn()  { printf '%b ⚠  %s%b\n' "$YELLOW" "$*" "$RESET"; }
fail()  { printf '%b ✗  %s%b\n' "$RED"    "$*" "$RESET"; exit 1; }

# --- 1. Python ---
if ! command -v python3 >/dev/null 2>&1; then
    fail "Не найден python3. Установи Python 3.9+ и повтори."
fi

PY_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PY_MAJOR="${PY_VERSION%%.*}"
PY_MINOR="${PY_VERSION##*.}"
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 9 ]; }; then
    fail "Нужен Python 3.9+, у тебя $PY_VERSION."
fi
ok "Python $PY_VERSION найден"

# --- 2. venv ---
if [ ! -d "venv" ]; then
    info "Создаю virtualenv в ./venv …"
    python3 -m venv venv
    ok "venv создан"
else
    info "venv уже есть, переиспользую"
fi

# --- 3. deps ---
info "Ставлю зависимости (requirements.txt) …"
./venv/bin/pip install --quiet --upgrade pip
./venv/bin/pip install --quiet -r requirements.txt
ok "Зависимости установлены"

# --- 4. .env ---
if [ ! -f ".env" ]; then
    cp .env.example .env
    chmod 600 .env || true
    info "Создан .env из шаблона"
fi

echo ""
info "Запускаю мастер настройки .env…"
echo ""
./venv/bin/python setup_env.py

echo ""
ok "Готово."
echo ""
printf '%bЧто дальше%b:\n' "$BOLD" "$RESET"
echo "  ./venv/bin/python list_accounts.py   # все аккаунты воркспейса"
echo "  ./venv/bin/python verify.py          # smoke-test всех кредов"
echo "  ./venv/bin/python check_one.py       # проверить один аккаунт"
echo "  ./venv/bin/python check.py           # полная проверка с алертами в Telegram"
echo ""
echo "  make check    # короткий алиас на полную проверку (через Makefile)"
