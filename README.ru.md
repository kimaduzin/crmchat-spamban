# crmchat-spamban

[English](README.md) · **Русский**

[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/kimaduzin/crmchat-spamban/pulls)

Автоматическая проверка SpamBan-статуса Telegram-аккаунтов для команд,
которые занимаются аутричом через [CRMchat](https://crmchat.ai).

`crmchat-spamban` запускает официальную самопроверку в `@SpamBot` от лица
каждого аккаунта в воркспейсе CRMchat, классифицирует ответ
(`ok` / `limited` / `banned` / `unknown` / `error`) и шлёт понятные алерты
в твой Telegram-чат — чтобы команда успела среагировать **до того**,
как просядет доставляемость.

## Зачем это

Ручные проверки не масштабируются, когда аккаунтов десятки или сотни.

Этот проект даёт:

- Онбординг новых участников команды одной командой (`./setup.sh`).
- Безопасную валидацию кредов **до** первого боевого запуска.
- Регулярный мониторинг (вручную, через cron или systemd-таймеры).
- Алерты с контекстом по аккаунту и прямой ссылкой в карточку CRMchat.

## Что умеет

- Проверяет все Telegram-аккаунты выбранного воркспейса CRMchat.
- Использует официальный self-check через `@SpamBot` (`/start` + чтение истории).
- Шлёт сводку + детальные алерты по каждому проблемному аккаунту в Telegram.
- Поддерживает dry-run и частичные прогоны для отладки.
- Включает отдельные скрипты для быстрой диагностики одного аккаунта.
- Поставляется с готовыми systemd-таймерами для прод-расписания.

## Что понадобится

- Python `3.9+`
- API-токен CRMchat (`CRMCHAT_TOKEN`)
- ID воркспейса CRMchat (`WORKSPACE_ID`)
- Токен Telegram-бота для уведомлений (`NOTIFY_BOT_TOKEN`)
- ID Telegram-чата, куда бот будет писать (`NOTIFY_CHAT_ID`)

## Быстрый старт

```bash
git clone https://github.com/kimaduzin/crmchat-spamban.git
cd crmchat-spamban
./setup.sh
```

`setup.sh` сделает:

1. Создаст `venv`.
2. Поставит зависимости.
3. Запустит интерактивный мастер настройки (`setup_env.py`).
4. Проверит креды CRMchat и Telegram прямо в процессе ввода.
5. Сохранит `.env` с правами `600` (на сколько позволит ОС).

## Частые команды

```bash
make verify              # smoke-тест всей конфигурации
make list                # таблица аккаунтов воркспейса
make one                 # полный цикл для одного (первого active) аккаунта
make one Q=@username     # проверить аккаунт по username / телефону / ID
make check-dry           # все аккаунты, без отправки /start (read-only)
make check               # боевой прогон + алерты в Telegram
```

## Пример сводки

```text
SpamBan check — manual
Старт:  2026-05-21 13:00 MSK
Финиш:  14:01 MSK

Всего: 27
OK: 24
Ограничено (limited): 1
Забанено (banned): 1
Заморожено (frozen): 0
Без сессии (unauthorized): 1
Оффлайн (offline): 0
Ошибки / не распознано: 0
```

По каждому проблемному аккаунту `crmchat-spamban` присылает отдельное
сообщение с:

- идентификатором аккаунта;
- точным текстом ответа `@SpamBot` (или комментарием по CRMchat-статусу);
- временем проверки;
- кнопкой «Открыть аккаунт» — прямой ссылкой в веб-интерфейс CRMchat.

## Конфигурация

Скопируй `.env.example` в `.env` (либо запусти `./setup.sh`, который
сделает это интерактивно):

```bash
CRMCHAT_TOKEN=sk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
WORKSPACE_ID=xxxxxxxxxxxxxxxxxxxx
NOTIFY_BOT_TOKEN=1234567890:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
NOTIFY_CHAT_ID=123456789

# опциональные параметры запуска:
# SPAMBAN_RUN_LABEL=manual
# SPAMBAN_WINDOW_MINUTES=60
# SPAMBAN_DRY_RUN=0
# SPAMBAN_REPLY_WAIT=6
# SPAMBAN_LIMIT=0
```

### Где взять значения

**`CRMCHAT_TOKEN`** — Settings → API keys → Create в `app.crmchat.ai`.
Ключ начинается с `sk_…` и показывается один раз — сразу копируй.

**`WORKSPACE_ID`** — проще всего получить через `./setup.sh`: он покажет
список доступных воркспейсов и даст выбрать. Альтернативно: посмотри
URL после логина (`https://app.crmchat.ai/w/<WORKSPACE_ID>/...`) или
запроси через API:

```bash
curl -s -H "Authorization: Bearer $CRMCHAT_TOKEN" \
  "https://api.crmchat.ai/v1/organizations"
curl -s -H "Authorization: Bearer $CRMCHAT_TOKEN" \
  "https://api.crmchat.ai/v1/workspaces?organizationId=<ORG_ID>"
```

**`NOTIFY_BOT_TOKEN`** — `@BotFather` → `/newbot`. Сразу напиши боту
любое сообщение или добавь в нужную группу, чтобы Telegram запомнил
чат.

**`NOTIFY_CHAT_ID`** — `./setup.sh` парсит `getUpdates` бота и предлагает
выбрать. Вручную: открой
`https://api.telegram.org/bot<NOTIFY_BOT_TOKEN>/getUpdates` и найди
поле `chat.id`. Для групп и каналов ID начинается с `-100…`.

### Несколько воркспейсов (опционально)

Файл `.env.extra.example` — шаблон override-файла для дополнительных
воркспейсов. Это позволяет с одной установки гонять отдельные проверки
для разных `WORKSPACE_ID` и при необходимости разных чатов уведомлений.

Секреты (`CRMCHAT_TOKEN`, `NOTIFY_BOT_TOKEN`) при этом остаются в одном
общем `.env`.

## Прод-деплой (Linux + systemd)

В папке `systemd/` лежат готовые юниты:

- `spamban-weekday-morning.*` — будни 08:00–09:00 MSK
- `spamban-weekday-evening.*` — будни 17:00–19:00 MSK
- `spamban-saturday.*` — суббота 12:00–14:00 MSK
- `spamban-sunday.*` — воскресенье 18:00–21:00 MSK
- `spamban-extra-morning.*` — пример для дополнительного воркспейса

Время по МСК, аккаунты внутри окна распределяются равномерно с рандомным
джиттером — так не палится «ровно в 08:00 все 27 аккаунтов разом пошли
писать SpamBot».

Общий план деплоя:

1. Скопировать проект на сервер (например, в `/opt/spamban`).
2. Создать сервисного пользователя (`useradd -r spamban`).
3. Заполнить `.env`.
4. Создать venv и поставить зависимости.
5. Прогнать `verify.py` — убедиться, что креды работают.
6. Положить юниты в `/etc/systemd/system/` и включить таймеры.

Расписание можно менять как угодно — это просто `OnCalendar=…` в
`*.timer` и `SPAMBAN_WINDOW_MINUTES=…` в `*.service`.

### Если на сервере нет systemd

Можно через cron:

```cron
0  8 * * 1-5  cd /opt/spamban && SPAMBAN_RUN_LABEL=weekday-morning SPAMBAN_WINDOW_MINUTES=60  $(grep -v '^#' .env | xargs) ./venv/bin/python check.py >> /var/log/spamban.log 2>&1
0 17 * * 1-5  cd /opt/spamban && SPAMBAN_RUN_LABEL=weekday-evening SPAMBAN_WINDOW_MINUTES=120 $(grep -v '^#' .env | xargs) ./venv/bin/python check.py >> /var/log/spamban.log 2>&1
0 12 * * 6    cd /opt/spamban && SPAMBAN_RUN_LABEL=saturday        SPAMBAN_WINDOW_MINUTES=120 $(grep -v '^#' .env | xargs) ./venv/bin/python check.py >> /var/log/spamban.log 2>&1
0 18 * * 0    cd /opt/spamban && SPAMBAN_RUN_LABEL=sunday          SPAMBAN_WINDOW_MINUTES=180 $(grep -v '^#' .env | xargs) ./venv/bin/python check.py >> /var/log/spamban.log 2>&1
```

> systemd-юниты дают рандомизацию старта (`RandomizedDelaySec=120`) и
> ловят пропущенные запуски (`Persistent=true`) — в cron этого нет,
> поэтому в проде предпочтительнее systemd, если он доступен.

## Как это работает внутри

Для каждого аккаунта в воркспейсе:

1. Аккаунты с CRMchat-статусом не `active` (`frozen`, `banned`,
   `unauthorized`, `offline`) сразу попадают в детальный отчёт без
   обращения к SpamBot — TL-вызовы по ним невозможны.
2. Резолвится peer `@SpamBot` через Telegram raw API.
3. Отправляется `/start`.
4. Читается последняя история (limit=5).
5. Текст ответа классифицируется по паттернам из `check.py`
   (`GOOD_PATTERNS` / `LIMITED_PATTERNS` / `BANNED_PATTERNS`).
6. Формируется сводка и детальные сообщения по проблемным аккаунтам.

## Безопасность

- **Никогда** не коммить `.env` и реальные токены в репозиторий.
- Лучше отдельный токен / отдельный чат для каждого участника команды
  или для каждой среды (dev / prod).
- Используй выделенного Telegram-бота строго для мониторинга — не
  переиспользуй продакшен-бота из других проектов.
- На сервере ограничь права на файл `.env` владельцу (`chmod 600`).
- В `.gitignore` уже исключены `.env`, `.env.*` (кроме примеров),
  `venv/`, `__pycache__/`.

## FAQ

**Безопасно ли отправлять `/start` в `@SpamBot`?**
Да. `@SpamBot` — официальный бот Telegram именно для самопроверки
аккаунта. Это не рассылка по другим пользователям, не спам и не серая
зона.

**SpamBot сменил формулировку, и проверка вернула `unknown` — что делать?**
В детальном алерте будет полный текст ответа. Допиши характерную
подстроку в один из списков в начале `check.py` (`GOOD_PATTERNS`,
`LIMITED_PATTERNS`, `BANNED_PATTERNS`). Pull request с новой
формулировкой — всегда welcome, особенно для не-английских языков.

**Что с `FLOOD_WAIT`?**
Парсится из ответа, но мы НЕ ждём. Аккаунт помечается как `error` с
понятной пометкой, на следующем запуске будет повторная попытка. Если
хочется ждать — правится в `check_account()` в `check.py`.

**Аккаунты со статусом `frozen` / `banned` / `unauthorized` / `offline`
в CRMchat?**
TL-вызовы по ним невозможны, поэтому SpamBot не дёргается. Они сразу
попадают в детальный отчёт со статусом и пояснением из CRMchat.

**Не упрёмся ли в rate limit CRMchat (300 req/min)?**
Нет — на сотню аккаунтов выходит ~3 запроса на каждого, разнесённые по
60–180-минутному окну. До лимита далеко.

**Можно несколько коллег с одного notify-бота?**
Можно — у каждого свой `NOTIFY_CHAT_ID`. Но проще дать каждому своего
бота: меньше путаницы при дебаге.

## Структура проекта

```text
.
├── check.py                # боевой запуск: проверка всех аккаунтов + алерты
├── check_one.py            # пошаговая проверка ОДНОГО аккаунта
├── list_accounts.py        # таблица всех аккаунтов воркспейса
├── verify.py               # smoke-test всех кредов
├── setup.sh                # установка одной командой
├── setup_env.py            # интерактивный мастер настройки .env
├── Makefile                # короткие алиасы для частых команд
├── requirements.txt
├── .env.example            # шаблон конфига с комментариями
├── .env.extra.example      # override для второго воркспейса
└── systemd/                # шаблоны systemd-юнитов для прод-расписания
```

## Контрибьют

Issues и pull requests приветствуются!

- [Открой issue](https://github.com/kimaduzin/crmchat-spamban/issues) для
  багов, новых формулировок SpamBot или фич-предложений.
- PR должен решать одну задачу — так его проще ревьюить.
- В описании PR — что было до и что стало после.

Особенно полезны issues с новыми формулировками SpamBot на разных
языках: каждое такое сообщение делает проверку точнее для всего
сообщества.

## Лицензия

Распространяется по лицензии [MIT](LICENSE).

## Дисклеймер

Ты сам отвечаешь за соблюдение условий использования Telegram, CRMchat,
законов твоей страны и политик твоей организации. Проект распространяется
**как есть** (as is), без каких-либо гарантий. Автор не аффилирован ни с
Telegram, ни с CRMchat.
