# Деплой webscope на Fly.io

Продовый стенд: Fly.io, приложение `webscope`, регион Токио (`nrt`).
Сканер работает по-настоящему (Chromium внутри контейнера), не заглушка.

## Адреса

| Что | Адрес |
|---|---|
| Основной (для жюри и всех) | https://webscope.duckdns.org/ |
| Технический | https://webscope.fly.dev/ |
| Healthcheck | https://webscope.duckdns.org/healthz |

`webscope.fly.dev` у провайдера A1 (Беларусь) не резолвится: DNS отдаёт
заглушку `185.61.104.x` вместо Fly. Поэтому основной адрес — DuckDNS,
он резолвится обычным DNS без Private DNS и VPN. По IP блокировки нет:
любой домен, указывающий на `66.241.125.17`, открывается у всех.

> Токен DuckDNS лежит в `docs/.deploy-secrets` — это локальный файл,
> он не коммитится (см. `.gitignore`). Посмотреть: `cat docs/.deploy-secrets`.

## Что где живёт

| Ресурс | Значение |
|---|---|
| Fly app | `webscope` (org `personal`) |
| Region | `nrt` (Токио), множитель цены ×1.308 |
| Машина | `shared-cpu-1x`, 1024 МБ RAM (на 512 МБ Chromium падает по OOM) |
| Volume | `webscope_data`, 1 ГБ, монтируется в `/data` |
| База | `/data/webscope.db` (`WEBSCOPE_DB_PATH`) |
| Chromium | `/ms-playwright` (`PLAYWRIGHT_BROWSERS_PATH`), ставится в образ |
| IPv4 | `66.241.125.17` (shared public ingress) |
| IPv6 | `2a09:8280:1::20f:fcc0:0` (dedicated) |

## Деплой

```bash
cd ~/Work/qa-startup          # он же /data/Work/qa-startup

flyctl status -a webscope
flyctl deploy -a webscope     # сборка Dockerfile и rolling-замена машины
flyctl logs -a webscope       # старт, healthcheck, сканы
flyctl ssh console -a webscope
```

Полная пересборка без кэша — `flyctl deploy -a webscope --no-cache`.
Первый деплой после `fly launch` может занять несколько минут: образ ~483 МБ.

Проверка после деплоя:

```bash
curl -s https://webscope.duckdns.org/healthz          # {"status":"ok"}
curl -s -o /dev/null -w '%{http_code}\n' https://webscope.duckdns.org/
curl -s -o /dev/null -w '%{http_code}\n' https://webscope.duckdns.org/static/css/base.css
```

## Секреты и вход

Сейчас вход **выключен** (`WEBSCOPE_AUTH_PASSWORD` не задан): кабинет и
запуск сканов доступны любому, кто знает адрес. Чтобы закрыть:

```bash
flyctl secrets set -a webscope \
  WEBSCOPE_AUTH_PASSWORD='сложный-пароль' \
  WEBSCOPE_AUTH_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
```

- `WEBSCOPE_AUTH_USER` — логин, по умолчанию `admin`.
- `WEBSCOPE_AUTH_KEY` — Fernet-ключ для паролей к защищённым сайтам.
  Без него пароли хранятся как есть.
- `WEBSCOPE_MOCK_SCANNER=1` — включает заглушку (одинаковые отчёты для всех
  сайтов). В этом режиме в интерфейсе висит честная полоса «Демо-режим».
  На проде **не задавать**.

Публичные маршруты без входа: `/`, `/landing`, `/auth/*`, `/healthz`,
`/static/*`, `/__local/*`. Остальное требует авторизации.

## Домен DuckDNS

Домен: `webscope.duckdns.org`, DNS-провайдер DuckDNS (TTL 60 с).

| Тип | Имя | Значение |
|---|---|---|
| A | `webscope.duckdns.org` | `66.241.125.17` |
| AAAA | `webscope.duckdns.org` | `2a09:8280:1::20f:fcc0:0` |
| TXT | `_fly-ownership.webscope.duckdns.org` | `app-egk20lk` |

DuckDNS отдаёт одну TXT-запись на все под-поддомены, поэтому запись,
добавленная для `webscope.duckdns.org`, работает и для
`_fly-ownership.webscope.duckdns.org`.

Обновление записей (токен — в `docs/.deploy-secrets`, файл не в git):

```bash
cd ~/Work/qa-startup
set -a; . docs/.deploy-secrets; set +a

# A + AAAA
curl "https://www.duckdns.org/update?domains=$DUCKDNS_DOMAIN&token=$DUCKDNS_TOKEN&ip=66.241.125.17&ipv6=2a09:8280:1::20f:fcc0:0&verbose=true"

# TXT для подтверждения владения доменом в Fly
curl "https://www.duckdns.org/update?domains=$DUCKDNS_DOMAIN&token=$DUCKDNS_TOKEN&txt=app-egk20lk&verbose=true"
```

Оба запроса должны ответить `OK ... UPDATED`.

Токен DuckDNS хранится только локально: `docs/.deploy-secrets`
(добавлен в `.gitignore`). В репозиторий и в переписку его класть нельзя —
он даёт доступ к записям домена. Если файл потерян, токен на сайте DuckDNS
не показывается; тогда проще создать новый домен на новом аккаунте и
перевыпустить сертификат.

### Сертификат

TLS выпускает Fly через Let's Encrypt, автоматически и бесплатно:

```bash
flyctl certs add webscope.duckdns.org -a webscope
flyctl certs check webscope.duckdns.org -a webscope   # ждём Status = Issued
flyctl certs list -a webscope
```

Подтверждение владения — по TXT `_fly-ownership` (значение выше) или по
AAAA-записи на IPv6 приложения. Сертификат продлевается сам; на
`*.fly.dev` действует отдельный сертификат `CN=*.fly.dev`.

## Trial Fly и деньги

Аккаунт без карты — trial: машину принудительно останавливают через
5 минут после старта, в логах это видно как

```
Trial machine stopping. To run for longer than 5m0s, add a credit card
```

Поэтому первый заход после паузы занимает 2–3 секунды (машина просыпается
по запросу). Привязка карты убирает это ограничение; тариф остаётся
pay-as-you-go, без подписки.

Ориентир по цене (официальный прайс Fly, ноябрь 2026):

| Ресурс | Цена |
|---|---|
| `shared-cpu-1x` 256 МБ | $2.19/мес (Ashburn) |
| +1 ГБ RAM | +$6.00/мес |
| Volume | $0.15 за ГБ/мес |
| Egress | $0.02/ГБ (Европа/США), $0.04/ГБ (Азия) |
| Общий IPv4, IPv6 | бесплатно |

Наш конфиг в Токио: ≈ $8.9/мес круглосуточно. С `auto_stop_machines = true`
платим только за время работы; счета меньше $5 Fly не выставляет.
В Европе (`ams`, `fra`) дешевле и быстрее из Минска, но переезд требует
нового volume и переноса базы.

## Что уже починено в сборке

Чтобы не сломать при следующем деплое:

1. **static в wheel.** `pyproject.toml` → `package-data` включает
   `static/*.svg`, `static/css/*.css`, `static/js/*.js`. Без этого
   установленный пакет падает на старте:
   `Directory .../webapp/static does not exist`.
2. **Один `pip install ".[web]"` в builder.** Runtime-стадия копирует
   пакеты из builder; отдельная установка без extras приводила к
   `ModuleNotFoundError: No module named 'fastapi'`.
3. **Chromium после копирования пакетов.** Версия браузера совпадает
   с версией `playwright` из builder.
4. **Флаги Chromium в контейнере** (`scanner.py`):
   `--disable-dev-shm-usage` (в Docker `/dev/shm` = 64 МБ) и
   `--no-sandbox` (нет user namespaces). Без них скан падает:
   `BrowserContext.new_page: Target crashed`.
5. **Entrypoint + volume.** Fly монтирует `/data` от root, приложение
   работает от `webscope`. `docker-entrypoint.sh` делает `chown -R`
   и сбрасывает привилегии через `setpriv`/`su`.
6. **`.dockerignore`.** В контекст не попадают `.venv`, `pitch/`,
   `data/`, `docs/`, `tests/`, `.git` (было 488 МБ / 12k файлов).
7. **Память 1024 МБ.** На 512 МБ рендерер Chromium падает по памяти.

## Локальный запуск (как на проде, без заглушки)

```bash
cd ~/Work/qa-startup
WEBSCOPE_DB_PATH=data/webscope.db \
  .venv/bin/python -m uvicorn webscope.webapp.app:create_app \
  --factory --host 127.0.0.1 --port 8000
```

`WEBSCOPE_MOCK_SCANNER=1` **не задавать**, иначе все сайты получат один
и тот же демо-отчёт. Лог: `/tmp/opencode/webscope.log`.

## Диагностика

| Симптом | Что смотреть |
|---|---|
| Сайт не открывается на телефоне/A1 | `resolvectl query webscope.duckdns.org` → должен быть `66.241.125.17`; `curl -s --resolve webscope.duckdns.org:443:66.241.125.17 https://webscope.duckdns.org/healthz` |
| `webscope.fly.dev` не открывается | Нормально для A1, используйте DuckDNS-домен |
| Долгий первый заход | Trial остановил машину; `flyctl machine list`, `flyctl machine start <id>` |
| 502 / пустая страница | `flyctl logs`; машина могла не пройти healthcheck |
| Скан падает `Target crashed` | Проверить флаги Chromium и память 1 ГБ |
| 404 на CSS | Проверить `package-data` и `pip show -f webscope` |
| Сканы одинаковые | Задан `WEBSCOPE_MOCK_SCANNER=1`; в UI горит «Демо-режим» |
| `RuntimeError: Directory .../static does not exist` | В wheel не попала статика, см. п. 1 |
| SQLite `unable to open database file` | Права на `/data`, см. entrypoint |

## Полезные команды

```bash
flyctl ips list -a webscope
flyctl volumes list -a webscope
flyctl machine list -a webscope
flyctl certs list -a webscope
flyctl ssh console -a webscope -C "ls -la /data"
flyctl ssh console -a webscope -C "python -c \"import sqlite3;c=sqlite3.connect('/data/webscope.db');print(c.execute('select id,status,score from runs order by id desc limit 3').fetchall())\""
```

## Ограничения

- Оплата на сайте не подключена: тарифы — будущие лимиты, не действующие.
- Один регион, одна машина, без реплик: при деплое короткий простой.
- SQLite на volume: бэкапы — снапшоты Fly (первые 10 ГБ/мес бесплатно),
  отдельного cron-бэкапа нет.
