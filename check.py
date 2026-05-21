#!/usr/bin/env python3
"""SpamBan check для всех Telegram-аккаунтов воркспейса CRMchat.

Алгоритм:
1. GET /workspaces/{ws}/telegram-accounts — список аккаунтов.
2. Распределяем аккаунты по окну (рандомные смещения внутри [start, start + window]).
3. Для каждого аккаунта со status=active:
     contacts.resolveUsername("SpamBot") → userId/accessHash
     messages.sendMessage("/start", randomId)
     ждём ответ
     messages.getHistory(limit=5) → берём первое НЕисходящее сообщение
     классифицируем текст: ok | limited | banned | unknown
4. Шлём в Telegram-бот:
     — сводку: всего / ok / ограничено / забанено / без сессии / ошибки
     — по каждому проблемному аккаунту: статус, логин, телефон, время, текст ответа.

Запуск:
    SPAMBAN_WINDOW_MINUTES=60 SPAMBAN_RUN_LABEL=morning ./check.py
"""

from __future__ import annotations

import html
import json
import logging
import os
import random
import sys
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

import requests

API_BASE = "https://api.crmchat.ai/v1"
CRMCHAT_APP_BASE = "https://app.crmchat.ai"
MSK = ZoneInfo("Europe/Moscow")


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        sys.stderr.write(f"ERROR: env var {name} is required\n")
        sys.exit(2)
    return value


TOKEN = _require_env("CRMCHAT_TOKEN")
WS_ID = _require_env("WORKSPACE_ID")
NOTIFY_BOT_TOKEN = _require_env("NOTIFY_BOT_TOKEN")
NOTIFY_CHAT_ID = _require_env("NOTIFY_CHAT_ID")

WINDOW_MINUTES = int(os.environ.get("SPAMBAN_WINDOW_MINUTES", "60"))
RUN_LABEL = os.environ.get("SPAMBAN_RUN_LABEL", "manual")
DRY_RUN = os.environ.get("SPAMBAN_DRY_RUN", "0") == "1"
REPLY_WAIT_SECONDS = float(os.environ.get("SPAMBAN_REPLY_WAIT", "6"))
# Если задан > 0 — берём только N случайных аккаунтов из воркспейса. Удобно
# для отладки и smoke-тестов.
LIMIT = int(os.environ.get("SPAMBAN_LIMIT", "0"))

H = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}

# Тексты ответов @SpamBot. Бот отвечает на языке клиента (RU/EN), формулировки
# шаблонные. Если придёт незнакомая фраза — статус будет 'unknown', и в
# детальном алерте увидишь полный текст → допишешь подстроку в нужный список.
# Все паттерны сравниваются в lower-case.
GOOD_PATTERNS = [
    # EN
    "no limits are currently applied",
    "good news",
    # RU
    "свободен от каких-либо ограничений",
    "нет ограничений",
    "не наложено никаких ограничений",
]
LIMITED_PATTERNS = [
    # EN
    "your account is now limited",
    "your account will be limited",
    "you are limited until",
    "limited until",
    "we have decided to keep these limitations",
    "i'm sorry to inform",
    "i am sorry to inform",
    "your account was reported",
    "currently restricted",
    # RU
    "ваш аккаунт ограничен",
    "ваш аккаунт временно ограничен",
    "ваш аккаунт сейчас ограничен",
    "ваша учётная запись ограничена",
    "ваша учетная запись ограничена",
    "к сожалению, мы применили ограничения",
    "мы применили ограничения",
    "мы решили оставить эти ограничения",
    "оставить эти ограничения в силе",
    "поступили жалобы",
    "поступают жалобы",
    "к сожалению, ваш аккаунт",
]
BANNED_PATTERNS = [
    # EN
    "your account has been blocked",
    "your account is blocked",
    "permanently blocked",
    "unfortunately, our moderators",
    # RU
    "ваш аккаунт заблокирован",
    "аккаунт навсегда заблокирован",
    "учётная запись заблокирована",
    "учетная запись заблокирована",
]


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("spamban")


@dataclass
class Result:
    account_id: str
    login: str
    phone: str
    status: str  # ok | limited | banned | frozen | unauthorized | offline | error | unknown
    message: str
    checked_at: datetime = field(default_factory=lambda: datetime.now(tz=MSK))


def crmchat_get(path: str, params: Optional[dict] = None) -> dict:
    r = requests.get(f"{API_BASE}{path}", headers=H, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def tl_call(account_id: str, method: str, params: dict[str, Any]) -> dict:
    r = requests.post(
        f"{API_BASE}/workspaces/{WS_ID}/telegram-accounts/{account_id}/call/{method}",
        headers=H,
        json={"params": params},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["result"]


def list_accounts() -> list[dict]:
    out: list[dict] = []
    cursor: Optional[str] = None
    while True:
        params: dict[str, Any] = {"limit": 100}
        if cursor:
            params["startingAfter"] = cursor
        body = crmchat_get(f"/workspaces/{WS_ID}/telegram-accounts", params)
        out.extend(body.get("data", []))
        if not body.get("hasMore"):
            break
        cursor = (body.get("cursors") or {}).get("next")
        if not cursor:
            break
    return out


def classify(text: str) -> str:
    t = text.lower()
    if any(p in t for p in BANNED_PATTERNS):
        return "banned"
    if any(p in t for p in LIMITED_PATTERNS):
        return "limited"
    if any(p in t for p in GOOD_PATTERNS):
        return "ok"
    return "unknown"


def _extract_account_meta(acc: dict) -> tuple[str, str]:
    tg = acc.get("telegram") or {}
    username = tg.get("username")
    full_name = tg.get("fullName")
    phone = tg.get("phone") or ""
    if username:
        login = f"@{username}"
    elif full_name:
        login = full_name
    elif phone:
        login = f"+{phone}" if not phone.startswith("+") else phone
    else:
        login = acc.get("id", "?")
    return login, (f"+{phone}" if phone and not phone.startswith("+") else phone)


def _spambot_message_from_history(history: dict) -> Optional[str]:
    for m in history.get("messages") or []:
        if m.get("_") != "message":
            continue
        if m.get("out"):
            continue
        text = m.get("message")
        if text:
            return text
    return None


def check_account(acc: dict) -> Result:
    aid = acc["id"]
    login, phone = _extract_account_meta(acc)
    crm_status = acc.get("status", "unknown")

    if crm_status != "active":
        crm_status_explanations = {
            "frozen": (
                "Аккаунт ЗАМОРОЖЕН Telegram'ом (status=frozen в CRMchat). "
                "Это блокировка со стороны Telegram — TL-вызовы невозможны, "
                "проверка через @SpamBot пропущена. Нужно разморозить аккаунт "
                "(через https://t.me/spambot или восстановление в Telegram)."
            ),
            "banned": (
                "Аккаунт ЗАБАНЕН Telegram'ом (status=banned в CRMchat). "
                "Бан со стороны Telegram, восстановление обычно невозможно."
            ),
            "unauthorized": (
                "Сессия аккаунта НЕДЕЙСТВИТЕЛЬНА (status=unauthorized). "
                "Скорее всего его разлогинили. Проверка через @SpamBot невозможна — "
                "нужно перелогинить аккаунт в CRMchat."
            ),
            "offline": (
                "Аккаунт OFFLINE в CRMchat — TL-вызовы временно недоступны. "
                "Проверка через @SpamBot пропущена; перепроверим в следующий запуск."
            ),
        }
        return Result(
            account_id=aid,
            login=login,
            phone=phone,
            status=crm_status,
            message=crm_status_explanations.get(
                crm_status,
                f"CRMchat status: {crm_status} — живой сессии нет, "
                f"проверка через @SpamBot невозможна",
            ),
        )

    try:
        resolved = tl_call(aid, "contacts.resolveUsername", {"username": "SpamBot"})
        users = resolved.get("users") or []
        if not users:
            return Result(aid, login, phone, "error", "resolveUsername вернул пустой users[]")
        bot = users[0]
        peer_input = {
            "_": "inputPeerUser",
            "userId": int(bot["id"]),
            "accessHash": str(bot["accessHash"]),
        }

        if not DRY_RUN:
            tl_call(
                aid,
                "messages.sendMessage",
                {
                    "peer": peer_input,
                    "message": "/start",
                    "randomId": str(random.getrandbits(63)),
                },
            )
            time.sleep(REPLY_WAIT_SECONDS + random.uniform(0, 2))

        history_params = {
            "peer": peer_input,
            "offsetId": 0,
            "offsetDate": 0,
            "addOffset": 0,
            "limit": 5,
            "maxId": 0,
            "minId": 0,
            "hash": "0",
        }
        history = tl_call(aid, "messages.getHistory", history_params)
        text = _spambot_message_from_history(history)

        if not text:
            time.sleep(4)
            history = tl_call(aid, "messages.getHistory", history_params)
            text = _spambot_message_from_history(history)

        # Помечаем диалог с @SpamBot прочитанным — иначе на аккаунте остаётся
        # непрочитанное и плодится "1" на бейдже у живого пользователя.
        try:
            max_id = max(
                (int(m.get("id", 0)) for m in (history.get("messages") or [])),
                default=0,
            )
            if max_id > 0:
                tl_call(
                    aid,
                    "messages.readHistory",
                    {"peer": peer_input, "maxId": max_id},
                )
        except Exception as e:
            log.warning("readHistory failed for %s: %s", aid, e)

        if not text:
            return Result(
                aid, login, phone, "error",
                "Нет ответа от @SpamBot в последних 5 сообщениях (после повторной попытки)",
            )

        return Result(aid, login, phone, classify(text), text)

    except requests.HTTPError as e:
        msg = ""
        try:
            body = e.response.json() if e.response is not None else {}
            msg = body.get("message") or json.dumps(body)
        except Exception:
            msg = e.response.text if e.response is not None else str(e)

        if isinstance(msg, str) and msg.startswith("FLOOD_WAIT_"):
            try:
                wait = int(msg.split("_")[-1])
            except Exception:
                wait = 0
            return Result(
                aid, login, phone, "error",
                f"FLOOD_WAIT {wait}s — пропустили, перепроверим в следующем запуске",
            )

        status = e.response.status_code if e.response is not None else "?"
        return Result(aid, login, phone, "error", f"HTTP {status}: {msg}")

    except Exception as e:
        return Result(aid, login, phone, "error", f"{type(e).__name__}: {e}")


def crmchat_account_url(account_id: str) -> str:
    """URL карточки аккаунта в веб-интерфейсе CRMchat."""
    qs = urllib.parse.urlencode({"accountId": account_id})
    return f"{CRMCHAT_APP_BASE}/w/{WS_ID}/telegram?{qs}"


def notify(text: str, reply_markup: Optional[dict] = None) -> None:
    """Шлём сообщение в notify-бот. Делим на куски по 4000 символов.

    reply_markup (если задан) прикрепляется только к ПОСЛЕДНЕМУ куску —
    логично иметь кнопку «Открыть аккаунт» под единым сообщением.
    """
    chunks: list[str]
    if len(text) <= 4000:
        chunks = [text]
    else:
        chunks = [text[i : i + 4000] for i in range(0, len(text), 4000)]

    for i, chunk in enumerate(chunks):
        payload: dict[str, Any] = {
            "chat_id": NOTIFY_CHAT_ID,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup is not None and i == len(chunks) - 1:
            payload["reply_markup"] = reply_markup
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{NOTIFY_BOT_TOKEN}/sendMessage",
                json=payload,
                timeout=15,
            )
            if not r.ok:
                log.error("notify failed: %s %s", r.status_code, r.text)
        except Exception as e:
            log.error("notify exception: %s", e)


def schedule_offsets(n: int, window_seconds: int) -> list[float]:
    """Равномерные слоты с джиттером (sorted, в секундах от старта)."""
    if n <= 0:
        return []
    if n == 1:
        return [random.uniform(0, max(1, window_seconds))]
    base = [window_seconds * (i + 0.5) / n for i in range(n)]
    jitter = window_seconds / (n * 4)
    offsets = [max(0.0, b + random.uniform(-jitter, jitter)) for b in base]
    offsets.sort()
    return offsets


def render_summary(results: list[Result], started_at: datetime, finished_at: datetime) -> str:
    by_status: dict[str, int] = {}
    for r in results:
        by_status[r.status] = by_status.get(r.status, 0) + 1

    total = len(results)
    ok = by_status.get("ok", 0)
    limited = by_status.get("limited", 0)
    banned = by_status.get("banned", 0)
    frozen = by_status.get("frozen", 0)
    unauthorized = by_status.get("unauthorized", 0)
    offline = by_status.get("offline", 0)
    errors = by_status.get("error", 0) + by_status.get("unknown", 0)

    return (
        f"<b>SpamBan check — {html.escape(RUN_LABEL)}</b>\n"
        f"Старт:  {started_at.strftime('%Y-%m-%d %H:%M MSK')}\n"
        f"Финиш:  {finished_at.strftime('%H:%M MSK')}\n"
        f"\n"
        f"Всего: <b>{total}</b>\n"
        f"OK: <b>{ok}</b>\n"
        f"Ограничено (limited): <b>{limited}</b>\n"
        f"Забанено (banned): <b>{banned}</b>\n"
        f"Заморожено (frozen): <b>{frozen}</b>\n"
        f"Без сессии (unauthorized): <b>{unauthorized}</b>\n"
        f"Оффлайн (offline): <b>{offline}</b>\n"
        f"Ошибки/не распознано: <b>{errors}</b>"
    )


def render_detail(r: Result) -> str:
    login = r.login or "(no username)"
    if r.phone:
        login = f"{login} ({r.phone})"

    crm_only_statuses = {"frozen", "banned", "unauthorized", "offline"}
    if r.status in crm_only_statuses:
        body_label = "Комментарий (CRMchat-статус, @SpamBot не опрашивался):"
    elif r.status in ("error", "unknown"):
        body_label = "Комментарий:"
    else:
        body_label = "Ответ от @SpamBot:"

    return (
        f"<b>[{html.escape(r.status.upper())}]</b> {html.escape(login)}\n"
        f"Время:  {r.checked_at.strftime('%Y-%m-%d %H:%M:%S MSK')}\n"
        f"Account ID: <code>{html.escape(r.account_id)}</code>\n"
        f"\n"
        f"<b>{body_label}</b>\n"
        f"<pre>{html.escape(r.message[:3500])}</pre>"
    )


def main() -> int:
    started_at = datetime.now(tz=MSK)
    log.info(
        "Run label=%s, window=%dm, dry_run=%s, started=%s",
        RUN_LABEL, WINDOW_MINUTES, DRY_RUN, started_at,
    )

    accounts = list_accounts()
    log.info("Loaded %d accounts", len(accounts))

    if not accounts:
        notify(f"<b>SpamBan check ({html.escape(RUN_LABEL)})</b>\nАккаунтов нет, нечего проверять.")
        return 0

    random.shuffle(accounts)
    if LIMIT > 0 and LIMIT < len(accounts):
        log.info("SPAMBAN_LIMIT=%d → берём только N случайных аккаунтов из %d", LIMIT, len(accounts))
        accounts = accounts[:LIMIT]

    offsets = schedule_offsets(len(accounts), WINDOW_MINUTES * 60)

    results: list[Result] = []
    for offset, acc in zip(offsets, accounts):
        target = started_at + timedelta(seconds=offset)
        wait = (target - datetime.now(tz=MSK)).total_seconds()
        if wait > 0:
            log.info("Sleeping %.0fs until %s", wait, target.strftime("%H:%M:%S"))
            time.sleep(wait)

        login, _ = _extract_account_meta(acc)
        log.info("Checking %s [%s]", login, acc.get("id"))
        r = check_account(acc)
        log.info("  → %s: %s", r.status, r.message[:140])
        results.append(r)

    finished_at = datetime.now(tz=MSK)
    notify(render_summary(results, started_at, finished_at))

    for r in results:
        if r.status != "ok":
            markup = {
                "inline_keyboard": [[
                    {"text": "Открыть аккаунт", "url": crmchat_account_url(r.account_id)}
                ]]
            }
            notify(render_detail(r), reply_markup=markup)

    bad = sum(
        1 for r in results
        if r.status in ("limited", "banned", "frozen", "unauthorized")
    )
    log.info("Done. problematic=%d", bad)
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
