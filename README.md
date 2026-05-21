# crmchat-spamban

**English** · [Русский](README.ru.md)

[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/kimaduzin/crmchat-spamban/pulls)

Automated SpamBan health checker for Telegram outreach teams using
[CRMchat](https://crmchat.ai).

`crmchat-spamban` runs the official `@SpamBot` self-check across every
Telegram account in a CRMchat workspace, classifies each response
(`ok` / `limited` / `banned` / `unknown` / `error`) and sends clear alerts to
your Telegram chat — so your team reacts **before** deliverability collapses.

## Why this project

Manual checks do not scale when you manage many Telegram accounts.

This project gives you:

- One-command onboarding (`./setup.sh`) for new team members.
- Safe credential validation before first run.
- Repeatable daily monitoring (manual, cron, or systemd timers).
- Actionable alerts with account context and a direct CRMchat account link.

## Key features

- Checks all Telegram accounts from a CRMchat workspace.
- Uses official `@SpamBot` self-check flow (`/start` + history parsing).
- Sends summary + per-account detailed alerts to Telegram.
- Supports dry runs and partial runs for smoke tests.
- Includes scripts for troubleshooting one account quickly.
- Ships with ready-to-use systemd timers for production scheduling.

## Requirements

- Python `3.9+`
- CRMchat API token (`CRMCHAT_TOKEN`)
- CRMchat workspace ID (`WORKSPACE_ID`)
- Telegram bot token for notifications (`NOTIFY_BOT_TOKEN`)
- Telegram target chat ID (`NOTIFY_CHAT_ID`)

## Quick start

```bash
git clone https://github.com/kimaduzin/crmchat-spamban.git
cd crmchat-spamban
./setup.sh
```

`setup.sh` will:

1. Create `venv`
2. Install dependencies
3. Run interactive config wizard (`setup_env.py`)
4. Validate CRMchat + Telegram credentials
5. Save `.env` securely (best effort `chmod 600`)

## Common commands

```bash
make verify              # smoke-test configuration and integrations
make list                # list all accounts in the workspace
make one                 # full cycle for one active account
make one Q=@username     # target one account by username / phone / account ID
make check-dry           # no /start send, read-only style run
make check               # full run and Telegram notifications
```

## Example alert summary

```text
SpamBan check — manual
Start:  2026-05-21 13:00 MSK
Finish: 14:01 MSK

Total: 27
OK: 24
Limited: 1
Banned: 1
Unauthorized: 1
Offline: 0
Errors/Unknown: 0
```

For each non-OK account, `crmchat-spamban` also sends a separate detailed message with:

- account identifier
- exact `@SpamBot` response (or CRMchat status reason)
- timestamp
- quick link to open account in CRMchat UI

## Configuration

Copy `.env.example` to `.env` (or use `./setup.sh`):

```bash
CRMCHAT_TOKEN=sk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
WORKSPACE_ID=xxxxxxxxxxxxxxxxxxxx
NOTIFY_BOT_TOKEN=1234567890:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
NOTIFY_CHAT_ID=123456789

# optional runtime knobs:
# SPAMBAN_RUN_LABEL=manual
# SPAMBAN_WINDOW_MINUTES=60
# SPAMBAN_DRY_RUN=0
# SPAMBAN_REPLY_WAIT=6
# SPAMBAN_LIMIT=0
```

### Multiple workspaces (optional)

Use `.env.extra.example` to define an override file for additional workspaces.
This lets one deployment run separate checks with different workspace IDs and
optional notification chats.

## Production deployment (Linux + systemd)

Templates are included in `systemd/`:

- `spamban-weekday-morning.*`
- `spamban-weekday-evening.*`
- `spamban-saturday.*`
- `spamban-sunday.*`
- `spamban-extra-morning.*` (example for secondary workspace)

High-level flow:

1. Copy project to server (for example `/opt/spamban`)
2. Create service user
3. Configure `.env`
4. Create virtual environment and install deps
5. Run `verify.py`
6. Install timers and enable them

See unit files in `systemd/` and adapt schedule/timezone/window for your case.

## How it works (technical flow)

For each account in workspace:

1. Skip non-active CRMchat statuses (`frozen`, `banned`, `offline`, etc.)
2. Resolve `SpamBot` peer via Telegram raw API
3. Send `/start`
4. Read recent message history
5. Classify response text using pattern sets in `check.py`
6. Report summary and detailed exceptions

## Security notes

- Never commit `.env` or real tokens.
- Prefer separate tokens/chats per teammate or environment.
- Use a dedicated Telegram bot only for monitoring.
- Restrict server filesystem permissions (`.env` should be owner-readable only).

## FAQ

**Is sending `/start` to `@SpamBot` safe?**  
Yes. `@SpamBot` is Telegram’s self-check bot. This is not mass messaging.

**What if SpamBot wording changes and status becomes `unknown`?**  
Extend pattern lists in `check.py` (`GOOD_PATTERNS`, `LIMITED_PATTERNS`,
`BANNED_PATTERNS`).

**What about `FLOOD_WAIT` errors?**  
Current behavior: mark as error and retry in next scheduled run.

## Project structure

```text
.
├── check.py
├── check_one.py
├── list_accounts.py
├── verify.py
├── setup.sh
├── setup_env.py
├── Makefile
├── .env.example
├── .env.extra.example
└── systemd/
```

## Contributing

Issues and pull requests are welcome!

- [Open an issue](https://github.com/kimaduzin/crmchat-spamban/issues) for bugs,
  new SpamBot wording patterns, or feature ideas.
- Keep PRs focused: one concern per PR.
- Include before/after behavior in the description.

## License

Released under the [MIT License](LICENSE).

## Disclaimer

You are responsible for compliance with Telegram terms, CRMchat terms, local
laws and your organization's policies. This project is provided **as is**,
without warranties of any kind. The author is not affiliated with Telegram
or CRMchat.
