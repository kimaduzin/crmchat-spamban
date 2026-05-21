#!/usr/bin/env python3
"""Шаг 2: полный цикл проверки на ОДНОМ аккаунте.

Запуск:
    set -a; source .env; set +a
    python3 check_one.py                  # первый active
    python3 check_one.py @username        # по @username (с @ или без)
    python3 check_one.py 79637426923      # по phone
    python3 check_one.py acc_id_xxxxxx    # по CRMchat account id

Делает:
    1. список аккаунтов → выбирает целевой
    2. resolveUsername("SpamBot") → печатает userId/accessHash
    3. sendMessage("/start", randomId)
    4. ждёт ответ
    5. getHistory(limit=5) → печатает входящее сообщение
    6. классифицирует: ok / limited / banned / unknown
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
from typing import Any, Optional

import requests

API_BASE = "https://api.crmchat.ai/v1"


def _require(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        sys.stderr.write(f"ERROR: env var {name} is required\n")
        sys.exit(2)
    return v


TOKEN = _require("CRMCHAT_TOKEN")
WS_ID = _require("WORKSPACE_ID")
H = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}

REPLY_WAIT = float(os.environ.get("SPAMBAN_REPLY_WAIT", "6"))

GOOD = [
    "no limits are currently applied",
    "good news",
    "свободен от каких-либо ограничений",
    "нет ограничений",
    "не наложено никаких ограничений",
]
LIMITED = [
    "your account is now limited",
    "your account will be limited",
    "you are limited until",
    "limited until",
    "we have decided to keep these limitations",
    "i'm sorry to inform",
    "i am sorry to inform",
    "your account was reported",
    "currently restricted",
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
BANNED = [
    "your account has been blocked",
    "your account is blocked",
    "permanently blocked",
    "unfortunately, our moderators",
    "ваш аккаунт заблокирован",
    "аккаунт навсегда заблокирован",
    "учётная запись заблокирована",
    "учетная запись заблокирована",
]


def crmchat_get(path: str, params: Optional[dict] = None) -> dict:
    r = requests.get(f"{API_BASE}{path}", headers=H, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def tl_call(account_id: str, method: str, params: dict[str, Any]) -> dict:
    url = f"{API_BASE}/workspaces/{WS_ID}/telegram-accounts/{account_id}/call/{method}"
    r = requests.post(url, headers=H, json={"params": params}, timeout=60)
    if not r.ok:
        sys.stderr.write(
            f"\nHTTP {r.status_code} on {method}\n"
            f"URL: {url}\n"
            f"Body: {r.text}\n"
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


def select_account(accounts: list[dict], query: Optional[str]) -> dict:
    if not query:
        for a in accounts:
            if a.get("status") == "active":
                return a
        sys.exit("Нет активных аккаунтов для проверки")

    q = query.lstrip("@").lower()
    for a in accounts:
        tg = a.get("telegram") or {}
        username = (tg.get("username") or "").lower()
        phone = (tg.get("phone") or "").lower()
        aid = (a.get("id") or "").lower()
        if q in (username, phone, aid):
            return a
    sys.exit(f"Аккаунт не найден по запросу: {query}")


def classify(text: str) -> str:
    t = text.lower()
    if any(p in t for p in BANNED):
        return "banned"
    if any(p in t for p in LIMITED):
        return "limited"
    if any(p in t for p in GOOD):
        return "ok"
    return "unknown"


def main() -> int:
    query = sys.argv[1] if len(sys.argv) > 1 else None

    print("=== STEP 1. Список аккаунтов ===")
    accounts = list_accounts()
    print(f"Загружено: {len(accounts)}")

    acc = select_account(accounts, query)
    tg = acc.get("telegram") or {}
    print(
        f"\nВыбран аккаунт:\n"
        f"  id:        {acc.get('id')}\n"
        f"  username:  @{tg.get('username') or '—'}\n"
        f"  phone:     +{tg.get('phone') or '—'}\n"
        f"  fullName:  {tg.get('fullName') or '—'}\n"
        f"  status:    {acc.get('status')}"
    )
    if acc.get("status") != "active":
        print(f"\nАккаунт не active — TL-вызовы невозможны. Конец.")
        return 1
    aid = acc["id"]

    print("\n=== STEP 2. contacts.resolveUsername(\"SpamBot\") ===")
    resolved = tl_call(aid, "contacts.resolveUsername", {"username": "SpamBot"})
    users = resolved.get("users") or []
    if not users:
        print("Пустой users[]:")
        print(json.dumps(resolved, indent=2, ensure_ascii=False)[:1500])
        return 1
    bot = users[0]
    bot_user_id = int(bot["id"])
    bot_access_hash = str(bot["accessHash"])
    print(f"  userId:     {bot_user_id}")
    print(f"  accessHash: {bot_access_hash}")
    print(f"  username:   @{bot.get('username')}")
    print(f"  isBot:      {bot.get('bot')}")

    peer = {
        "_": "inputPeerUser",
        "userId": bot_user_id,
        "accessHash": bot_access_hash,
    }

    print("\n=== STEP 3. messages.sendMessage('/start') ===")
    rid = str(random.getrandbits(63))
    print(f"  randomId: {rid}")
    send_res = tl_call(
        aid,
        "messages.sendMessage",
        {"peer": peer, "message": "/start", "randomId": rid},
    )
    print(f"  result _: {send_res.get('_')}")
    print(f"  full updates: {len(send_res.get('updates', []))}")

    print(f"\n=== STEP 4. Ждём {REPLY_WAIT:.1f}s ответа от @SpamBot ===")
    time.sleep(REPLY_WAIT)

    print("\n=== STEP 5. messages.getHistory(limit=5) ===")
    hist = tl_call(
        aid,
        "messages.getHistory",
        {
            "peer": peer,
            "offsetId": 0,
            "offsetDate": 0,
            "addOffset": 0,
            "limit": 5,
            "maxId": 0,
            "minId": 0,
            "hash": "0",
        },
    )

    msgs = hist.get("messages") or []
    print(f"  Получено сообщений: {len(msgs)}  (hist._: {hist.get('_')})")

    spambot_text: Optional[str] = None
    for i, m in enumerate(msgs):
        kind = m.get("_")
        out_flag = m.get("out", False)
        text_preview = (m.get("message") or "").replace("\n", " ")[:80]
        print(f"  [{i}] _={kind}  out={out_flag}  msg={text_preview!r}")
        if kind == "message" and not out_flag and m.get("message") and spambot_text is None:
            spambot_text = m["message"]

    if not spambot_text:
        print("\nНет входящего сообщения от SpamBot. Подождём ещё 5s и перечитаем...")
        time.sleep(5)
        hist = tl_call(
            aid,
            "messages.getHistory",
            {
                "peer": peer,
                "offsetId": 0,
                "offsetDate": 0,
                "addOffset": 0,
                "limit": 5,
                "maxId": 0,
                "minId": 0,
                "hash": "0",
            },
        )
        for m in hist.get("messages") or []:
            if m.get("_") == "message" and not m.get("out") and m.get("message"):
                spambot_text = m["message"]
                break

    if not spambot_text:
        print("\nSpamBot так и не ответил.")
        return 2

    print("\n=== STEP 6. Текст ответа SpamBot ===")
    print("-" * 60)
    print(spambot_text)
    print("-" * 60)

    verdict = classify(spambot_text)
    print(f"\nКлассификация: {verdict.upper()}")
    if verdict == "unknown":
        print("Текст не сматчился ни с одним паттерном — добавь подстроку")
        print("в GOOD_PATTERNS / LIMITED_PATTERNS / BANNED_PATTERNS в check.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
