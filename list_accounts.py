#!/usr/bin/env python3
"""Шаг 1 проверки: вывести список Telegram-аккаунтов воркспейса.

Запуск:
    set -a; source .env; set +a
    python3 list_accounts.py

Печатает таблицу: status / username / phone / fullName / id
и сводку по статусам.
"""

from __future__ import annotations

import os
import sys
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


def list_accounts() -> list[dict]:
    out: list[dict] = []
    cursor: Optional[str] = None
    while True:
        params: dict[str, Any] = {"limit": 100}
        if cursor:
            params["startingAfter"] = cursor
        r = requests.get(
            f"{API_BASE}/workspaces/{WS_ID}/telegram-accounts",
            headers=H, params=params, timeout=30,
        )
        if r.status_code != 200:
            sys.stderr.write(f"HTTP {r.status_code}: {r.text}\n")
            sys.exit(1)
        body = r.json()
        out.extend(body.get("data", []))
        if not body.get("hasMore"):
            break
        cursor = (body.get("cursors") or {}).get("next")
        if not cursor:
            break
    return out


def main() -> int:
    accounts = list_accounts()
    if not accounts:
        print("Аккаунтов в воркспейсе нет.")
        return 0

    rows = []
    for a in accounts:
        tg = a.get("telegram") or {}
        rows.append(
            (
                a.get("status", "?"),
                tg.get("username") or "",
                tg.get("phone") or "",
                tg.get("fullName") or "",
                a.get("id", ""),
            )
        )

    headers = ("status", "username", "phone", "fullName", "id")
    widths = [
        max(len(h), max((len(str(r[i])) for r in rows), default=0))
        for i, h in enumerate(headers)
    ]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    print(fmt.format(*("-" * w for w in widths)))
    for r in rows:
        print(fmt.format(*r))

    print()
    by_status: dict[str, int] = {}
    for a in accounts:
        s = a.get("status", "?")
        by_status[s] = by_status.get(s, 0) + 1

    print(f"Всего: {len(accounts)}")
    for s, n in sorted(by_status.items(), key=lambda x: -x[1]):
        print(f"  {s}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
