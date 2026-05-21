#!/usr/bin/env python3
"""Интерактивный мастер настройки .env для spamban.

Что делает:
  1. Читает текущий .env (если есть) — берёт оттуда дефолты.
  2. Поочерёдно спрашивает каждое значение, объясняя где его взять.
  3. На лету валидирует:
       - CRMCHAT_TOKEN  → GET /v1/workspaces (200 = ок)
       - WORKSPACE_ID   → подгружает список воркспейсов и предлагает выбор;
                          считает Telegram-аккаунты внутри
       - NOTIFY_BOT_TOKEN → getMe (200 = ок, видно username бота)
       - NOTIFY_CHAT_ID → sendMessage тестового сообщения
  4. Сохраняет результат в .env (с правами 600, если возможно).

Запуск:
    python3 setup_env.py            # обычно вызывается из ./setup.sh
"""

from __future__ import annotations

import getpass
import os
import re
import sys
from pathlib import Path
from typing import Optional

try:
    import requests
except ImportError:
    sys.stderr.write(
        "ERROR: модуль 'requests' не установлен.\n"
        "Запусти ./setup.sh — он поставит зависимости автоматически,\n"
        "либо вручную: pip install -r requirements.txt\n"
    )
    sys.exit(2)


HERE = Path(__file__).resolve().parent
ENV_PATH = HERE / ".env"
ENV_EXAMPLE = HERE / ".env.example"

API_BASE = "https://api.crmchat.ai/v1"
TG_API = "https://api.telegram.org"

# Какие ключи мы умеем заполнять и в каком порядке. Остальные ключи из .env
# (если есть) сохраняются как есть.
MANAGED_KEYS = [
    "CRMCHAT_TOKEN",
    "WORKSPACE_ID",
    "NOTIFY_BOT_TOKEN",
    "NOTIFY_CHAT_ID",
]

C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"
C_GREEN = "\033[32m"
C_RED = "\033[31m"
C_YELLOW = "\033[33m"
C_CYAN = "\033[36m"


def c(text: str, color: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"{color}{text}{C_RESET}"


def header(title: str) -> None:
    print()
    print(c("=" * 64, C_DIM))
    print(c(f" {title}", C_BOLD + C_CYAN))
    print(c("=" * 64, C_DIM))


def info(text: str) -> None:
    print(c("ℹ ", C_CYAN) + text)


def ok(text: str) -> None:
    print(c("✓ ", C_GREEN) + text)


def warn(text: str) -> None:
    print(c("⚠ ", C_YELLOW) + text)


def err(text: str) -> None:
    print(c("✗ ", C_RED) + text)


def parse_env_file(path: Path) -> dict[str, str]:
    """Простой парсер KEY=VALUE без поддержки экспортов/мультистрок."""
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", stripped)
        if not m:
            continue
        key, val = m.group(1), m.group(2)
        if (val.startswith('"') and val.endswith('"')) or (
            val.startswith("'") and val.endswith("'")
        ):
            val = val[1:-1]
        result[key] = val
    return result


def write_env_file(path: Path, values: dict[str, str]) -> None:
    """Сохраняет .env, сохраняя все нетронутые ключи + комментарии-шапку."""
    existing_extra: dict[str, str] = {}
    if path.exists():
        existing_extra = {
            k: v
            for k, v in parse_env_file(path).items()
            if k not in MANAGED_KEYS
        }

    lines = [
        "# Сгенерировано setup_env.py.",
        "# Чтобы переподнять конфиг — перезапусти ./setup.sh.",
        "",
    ]
    for key in MANAGED_KEYS:
        lines.append(f"{key}={values.get(key, '')}")

    if existing_extra:
        lines.append("")
        lines.append("# --- Дополнительные ключи (не трогали) ---")
        for k, v in existing_extra.items():
            lines.append(f"{k}={v}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def prompt(label: str, default: Optional[str] = None, secret: bool = False) -> str:
    suffix = ""
    if default:
        shown = default
        if secret and len(default) > 8:
            shown = default[:4] + "…" + default[-4:]
        suffix = c(f" [{shown}]", C_DIM)
    while True:
        try:
            if secret:
                raw = getpass.getpass(f"{label}{suffix}: ")
            else:
                raw = input(f"{label}{suffix}: ")
        except (EOFError, KeyboardInterrupt):
            print()
            err("Прервано пользователем")
            sys.exit(130)
        value = raw.strip()
        if not value and default:
            return default
        if value:
            return value
        warn("Пустое значение, повтори ввод")


# ----------------------------------------------------------------------
# CRMchat
# ----------------------------------------------------------------------

def crmchat_list_workspaces(token: str) -> list[dict]:
    """Возвращает плоский список воркспейсов, доступных по этому токену.

    CRMchat API хочет organizationId как фильтр; чтобы найти все воркспейсы,
    сначала тянем список организаций, потом по каждой — список воркспейсов.
    """
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    orgs_resp = requests.get(f"{API_BASE}/organizations", headers=headers, timeout=20)
    if orgs_resp.status_code == 401:
        raise RuntimeError("Токен не принят (401 Unauthorized). Проверь CRMCHAT_TOKEN.")
    orgs_resp.raise_for_status()
    orgs = (orgs_resp.json() or {}).get("data") or []

    all_ws: list[dict] = []
    for org in orgs:
        org_id = org.get("id")
        if not org_id:
            continue
        ws_resp = requests.get(
            f"{API_BASE}/workspaces",
            headers=headers,
            params={"organizationId": org_id, "limit": 100},
            timeout=20,
        )
        if not ws_resp.ok:
            continue
        for ws in (ws_resp.json() or {}).get("data") or []:
            all_ws.append({
                "id": ws.get("id"),
                "name": ws.get("name") or "(no name)",
                "org_id": org_id,
                "org_name": org.get("name") or "(no org name)",
            })
    return all_ws


def crmchat_count_telegram_accounts(token: str, ws_id: str) -> Optional[int]:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    try:
        r = requests.get(
            f"{API_BASE}/workspaces/{ws_id}/telegram-accounts",
            headers=headers,
            params={"limit": 100},
            timeout=20,
        )
        if not r.ok:
            return None
        body = r.json() or {}
        data = body.get("data") or []
        return len(data) + (1 if body.get("hasMore") else 0)
    except Exception:
        return None


def setup_crmchat(current: dict[str, str]) -> tuple[str, str]:
    header("Шаг 1/3 — CRMchat")
    info("API-ключ CRMchat (sk_...).")
    info("Где взять: https://app.crmchat.ai → Settings → API keys → Create")
    print()

    while True:
        token = prompt(
            "CRMCHAT_TOKEN",
            default=current.get("CRMCHAT_TOKEN") or None,
            secret=True,
        )
        info("Проверяю токен через GET /v1/organizations…")
        try:
            workspaces = crmchat_list_workspaces(token)
        except RuntimeError as e:
            err(str(e))
            continue
        except requests.RequestException as e:
            err(f"Сетевая ошибка: {e}")
            continue

        if not workspaces:
            warn("Токен валиден, но воркспейсов не найдено.")
            ws_id = prompt(
                "Введи WORKSPACE_ID вручную",
                default=current.get("WORKSPACE_ID") or None,
            )
            return token, ws_id

        ok(f"Токен валиден. Найдено воркспейсов: {len(workspaces)}")
        break

    print()
    print(c("Доступные воркспейсы:", C_BOLD))
    for i, ws in enumerate(workspaces, 1):
        marker = ""
        if ws["id"] == current.get("WORKSPACE_ID"):
            marker = c("  ← сейчас в .env", C_GREEN)
        print(f"  {i}. {ws['name']:30s}  id={ws['id']}  org={ws['org_name']}{marker}")
    print(f"  M. Ввести WORKSPACE_ID вручную")
    print()

    while True:
        choice = prompt("Выбор", default="1")
        if choice.lower() == "m":
            ws_id = prompt(
                "WORKSPACE_ID",
                default=current.get("WORKSPACE_ID") or None,
            )
            break
        try:
            idx = int(choice)
            if 1 <= idx <= len(workspaces):
                ws_id = workspaces[idx - 1]["id"]
                break
        except ValueError:
            pass
        warn(f"Введи число от 1 до {len(workspaces)} или M")

    info(f"Считаю Telegram-аккаунты в воркспейсе {ws_id}…")
    count = crmchat_count_telegram_accounts(token, ws_id)
    if count is None:
        warn("Не удалось получить список аккаунтов — проверь права токена")
    elif count == 0:
        warn("В воркспейсе пока нет Telegram-аккаунтов. Это нормально, "
             "просто проверять будет нечего.")
    else:
        plus = "+" if count >= 100 else ""
        ok(f"Аккаунтов в воркспейсе: {count}{plus}")

    return token, ws_id


# ----------------------------------------------------------------------
# Telegram notify bot
# ----------------------------------------------------------------------

def tg_get_me(token: str) -> Optional[dict]:
    r = requests.get(f"{TG_API}/bot{token}/getMe", timeout=15)
    if not r.ok:
        return None
    body = r.json() or {}
    if not body.get("ok"):
        return None
    return body.get("result")


def tg_send_message(token: str, chat_id: str, text: str) -> tuple[bool, str]:
    try:
        r = requests.post(
            f"{TG_API}/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=15,
        )
        body = r.json() if r.content else {}
    except requests.RequestException as e:
        return False, f"network error: {e}"
    if r.ok and body.get("ok"):
        return True, ""
    desc = body.get("description") or r.text or "?"
    return False, f"HTTP {r.status_code}: {desc}"


def tg_suggest_chat_ids(token: str) -> list[dict]:
    """Парсит getUpdates и возвращает уникальные chat'ы, где бота уже видели."""
    try:
        r = requests.get(f"{TG_API}/bot{token}/getUpdates", timeout=15)
        body = r.json() if r.content else {}
    except Exception:
        return []
    if not body.get("ok"):
        return []
    seen: dict[str, dict] = {}
    for upd in body.get("result") or []:
        for key in ("message", "channel_post", "edited_message", "edited_channel_post",
                    "my_chat_member"):
            entity = upd.get(key)
            if not entity:
                continue
            chat = entity.get("chat") or {}
            cid = chat.get("id")
            if cid is None:
                continue
            seen[str(cid)] = {
                "id": cid,
                "type": chat.get("type") or "?",
                "title": chat.get("title")
                         or chat.get("username")
                         or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")]))
                         or "(no title)",
            }
    return list(seen.values())


def setup_notify_bot(current: dict[str, str]) -> tuple[str, str]:
    header("Шаг 2/3 — Telegram-бот для уведомлений")
    info("Создаётся один раз через @BotFather (/newbot).")
    info("После создания напиши боту /start (или добавь в нужную группу) —")
    info("чтобы Telegram запомнил chat_id.")
    print()

    while True:
        token = prompt(
            "NOTIFY_BOT_TOKEN",
            default=current.get("NOTIFY_BOT_TOKEN") or None,
            secret=True,
        )
        if not re.match(r"^\d+:[A-Za-z0-9_-]+$", token):
            warn("Похоже на невалидный токен (формат должен быть 123456:ABC…)")
            continue
        info("Проверяю бота через getMe…")
        me = tg_get_me(token)
        if not me:
            err("Telegram отверг токен. Проверь NOTIFY_BOT_TOKEN.")
            continue
        ok(f"Бот валиден: @{me.get('username')} ({me.get('first_name')})")
        break

    print()
    header("Шаг 3/3 — chat_id, куда слать уведомления")

    suggestions = tg_suggest_chat_ids(token)
    if suggestions:
        print(c("Бот видел сообщения в этих чатах:", C_BOLD))
        for i, ch in enumerate(suggestions, 1):
            marker = ""
            if str(ch["id"]) == str(current.get("NOTIFY_CHAT_ID")):
                marker = c("  ← сейчас в .env", C_GREEN)
            print(f"  {i}. id={ch['id']:<18}  type={ch['type']:<10}  {ch['title']}{marker}")
        print(f"  M. Ввести chat_id вручную")
        print()
        while True:
            choice = prompt("Выбор", default="1")
            if choice.lower() == "m":
                chat_id = prompt(
                    "NOTIFY_CHAT_ID",
                    default=current.get("NOTIFY_CHAT_ID") or None,
                )
                break
            try:
                idx = int(choice)
                if 1 <= idx <= len(suggestions):
                    chat_id = str(suggestions[idx - 1]["id"])
                    break
            except ValueError:
                pass
            warn(f"Введи число от 1 до {len(suggestions)} или M")
    else:
        warn("Бот пока не видел ни одного сообщения.")
        info("Напиши боту /start или добавь его в группу, потом введи chat_id вручную.")
        info("Подсказка: открой https://api.telegram.org/bot<TOKEN>/getUpdates")
        chat_id = prompt(
            "NOTIFY_CHAT_ID",
            default=current.get("NOTIFY_CHAT_ID") or None,
        )

    info("Шлю тестовое сообщение в чат…")
    success, problem = tg_send_message(
        token,
        chat_id,
        "spamban setup ✓ — бот настроен, можно гонять проверки.",
    )
    if success:
        ok("Тестовое сообщение доставлено.")
    else:
        warn(f"Доставить не удалось: {problem}")
        warn("Сохраню значение в .env, но проверь chat_id вручную через verify.py")

    return token, chat_id


# ----------------------------------------------------------------------
# main
# ----------------------------------------------------------------------

def main() -> int:
    print(c("spamban — мастер настройки .env", C_BOLD))
    print(c("Можно прервать в любой момент Ctrl+C, значения сохранятся только в конце.", C_DIM))

    if not ENV_EXAMPLE.exists():
        err("Не найден .env.example — запусти скрипт из папки spamban.")
        return 2

    current = parse_env_file(ENV_PATH)
    if current:
        info(f"Найден существующий .env — буду показывать текущие значения как дефолты.")

    try:
        crm_token, ws_id = setup_crmchat(current)
        bot_token, chat_id = setup_notify_bot(current)
    except KeyboardInterrupt:
        print()
        err("Прервано пользователем. Файл .env не изменён.")
        return 130

    final = dict(current)
    final["CRMCHAT_TOKEN"] = crm_token
    final["WORKSPACE_ID"] = ws_id
    final["NOTIFY_BOT_TOKEN"] = bot_token
    final["NOTIFY_CHAT_ID"] = chat_id

    write_env_file(ENV_PATH, final)
    print()
    ok(f"Сохранил {ENV_PATH} (chmod 600)")
    print()
    print(c("Готово. Дальше:", C_BOLD))
    print("  ./venv/bin/python list_accounts.py        # таблица аккаунтов")
    print("  ./venv/bin/python check_one.py            # проверить один аккаунт")
    print("  ./venv/bin/python verify.py               # smoke-test всех кредов")
    print("  ./venv/bin/python check.py                # полная проверка с алертами")
    return 0


if __name__ == "__main__":
    sys.exit(main())
