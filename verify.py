#!/usr/bin/env python3
"""Smoke-test для конфигурации spamban.

Проверяет:
  1. Все обязательные env-переменные заданы.
  2. CRMCHAT_TOKEN валиден  (GET /v1/organizations).
  3. WORKSPACE_ID доступен  (GET /v1/workspaces/{ws}/telegram-accounts).
  4. NOTIFY_BOT_TOKEN валиден  (Telegram getMe).
  5. NOTIFY_CHAT_ID доступен боту  (sendMessage с пометкой "test").

Возвращает exit code 0, если всё ок, иначе ≥1.

Запуск:
    ./setup.sh                  # ставит venv + deps, потом запускает verify.py не сам
    set -a; source .env; set +a
    ./venv/bin/python verify.py
    # или, если уже работает Makefile:
    make verify
"""

from __future__ import annotations

import os
import sys
from typing import Optional

import requests

API_BASE = "https://api.crmchat.ai/v1"
TG_API = "https://api.telegram.org"

C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_GREEN = "\033[32m"
C_RED = "\033[31m"
C_YELLOW = "\033[33m"
C_CYAN = "\033[36m"


def c(text: str, color: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"{color}{text}{C_RESET}"


def step(text: str) -> None:
    print()
    print(c(f"→ {text}", C_BOLD + C_CYAN))


def ok(text: str) -> None:
    print(c(f"  ✓ {text}", C_GREEN))


def fail(text: str) -> None:
    print(c(f"  ✗ {text}", C_RED))


def warn(text: str) -> None:
    print(c(f"  ⚠ {text}", C_YELLOW))


def need_env(name: str) -> Optional[str]:
    val = os.environ.get(name)
    if not val:
        fail(f"переменная окружения {name} не задана")
        return None
    return val


def main() -> int:
    print(c("spamban verify — smoke-test конфигурации", C_BOLD))

    errors = 0

    step("1/4. Проверяю env-переменные")
    crm_token = need_env("CRMCHAT_TOKEN")
    ws_id = need_env("WORKSPACE_ID")
    bot_token = need_env("NOTIFY_BOT_TOKEN")
    chat_id = need_env("NOTIFY_CHAT_ID")
    if not all([crm_token, ws_id, bot_token, chat_id]):
        warn("Нет всех обязательных переменных. Запусти ./setup.sh.")
        return 1
    ok("все переменные присутствуют")

    headers = {"Authorization": f"Bearer {crm_token}", "Accept": "application/json"}

    step("2/4. CRMchat — валидность токена")
    try:
        r = requests.get(f"{API_BASE}/organizations", headers=headers, timeout=20)
    except requests.RequestException as e:
        fail(f"сетевая ошибка: {e}")
        return 1
    if r.status_code == 401:
        fail("401 Unauthorized — токен невалиден")
        return 1
    if not r.ok:
        fail(f"HTTP {r.status_code}: {r.text[:300]}")
        return 1
    orgs = (r.json() or {}).get("data") or []
    if not orgs:
        warn("организаций не найдено — токен валиден, но непонятно к кому привязан")
    else:
        ok(f"токен валиден, организаций видно: {len(orgs)}")

    step("3/4. CRMchat — доступ к воркспейсу и аккаунтам")
    try:
        r = requests.get(
            f"{API_BASE}/workspaces/{ws_id}/telegram-accounts",
            headers=headers,
            params={"limit": 100},
            timeout=20,
        )
    except requests.RequestException as e:
        fail(f"сетевая ошибка: {e}")
        return 1
    if r.status_code in (401, 403):
        fail(f"{r.status_code} — нет доступа к воркспейсу {ws_id}. "
             "Проверь WORKSPACE_ID и что токен принадлежит правильной организации.")
        return 1
    if r.status_code == 404:
        fail(f"404 — воркспейс {ws_id} не найден")
        return 1
    if not r.ok:
        fail(f"HTTP {r.status_code}: {r.text[:300]}")
        return 1
    body = r.json() or {}
    data = body.get("data") or []
    has_more = bool(body.get("hasMore"))
    by_status: dict[str, int] = {}
    for a in data:
        s = a.get("status") or "?"
        by_status[s] = by_status.get(s, 0) + 1
    plus = "+" if has_more else ""
    ok(f"воркспейс доступен, аккаунтов на первой странице: {len(data)}{plus}")
    if by_status:
        details = ", ".join(f"{k}={v}" for k, v in sorted(by_status.items()))
        ok(f"распределение по статусам: {details}")
    if not data:
        warn("в воркспейсе нет Telegram-аккаунтов — проверять будет нечего")

    step("4/4. Telegram notify-бот — getMe + тестовое сообщение")
    try:
        me_resp = requests.get(f"{TG_API}/bot{bot_token}/getMe", timeout=15)
        me_body = me_resp.json() if me_resp.content else {}
    except requests.RequestException as e:
        fail(f"getMe сетевая ошибка: {e}")
        errors += 1
        me_body = {}
    if not me_body.get("ok"):
        fail(f"getMe отверг токен: {me_body.get('description') or me_resp.text[:200]}")
        errors += 1
    else:
        me = me_body["result"]
        ok(f"бот валиден: @{me.get('username')} ({me.get('first_name')})")

        try:
            send_resp = requests.post(
                f"{TG_API}/bot{bot_token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": "spamban verify ✓ — креды работают.",
                    "disable_web_page_preview": True,
                },
                timeout=15,
            )
            send_body = send_resp.json() if send_resp.content else {}
        except requests.RequestException as e:
            fail(f"sendMessage сетевая ошибка: {e}")
            errors += 1
            send_body = {}
        if not send_body.get("ok"):
            fail(f"sendMessage отвергнут: "
                 f"{send_body.get('description') or send_resp.text[:200]}")
            warn("Возможные причины: неверный chat_id, бот не добавлен в группу, "
                 "пользователь ещё не написал боту /start.")
            errors += 1
        else:
            ok(f"тестовое сообщение доставлено в chat_id={chat_id}")

    print()
    if errors:
        print(c(f"Найдено проблем: {errors}. Поправь и перезапусти verify.", C_RED + C_BOLD))
        return 1
    print(c("Всё ок. Можно запускать ./venv/bin/python check.py", C_GREEN + C_BOLD))
    return 0


if __name__ == "__main__":
    sys.exit(main())
