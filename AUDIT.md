# Аудит webscope

**Дата:** 2026-10-30 · **Коммит:** `879b321` · **Версия в коде:** 0.3.0
**Объём:** 8 725 строк Python, 149 тестов, 54 файла в `src/`

---

## TL;DR

Проект сильнее, чем 95% «AI-обёрток над Lighthouse»: есть архитектура слоёв,
детерминированный движок, человеческий язык отчёта, история с диффами и MCP-цикл
«нашёл → выдал ТЗ → перепроверил». Это реальная продуктовая идея, а не демо.

Но **в текущем виде веб-часть нельзя выставлять в интернет**: там нет аутентификации,
есть произвольная запись файла через `/upload`, stored XSS и обход SSRF-защиты.
Плюс CI красный, а движок в самом ценном месте (дубли `title` по шаблонам) выдаёт
ложные срабатывания на каждом сайте с `sitemap.xml`.

| Разрез | Оценка | Почему |
|---|---|---|
| Идея и позиционирование | **9/10** | «Починили → отписались» осознано, диффы как ядро подписки |
| Архитектура движка | **8/10** | Чистые функции проверок, единая схема находки, версионирование JSON |
| Качество проверок | **6/10** | Часть проверок — срезы (25 элементов, первый экран), нет `pageerror` |
| Веб-приложение (код) | **5/10** | Маршруты читаются, но 667 строк в одном файле, нет слоя сервисов |
| Безопасность веб-приложения | **2/10** | Нет auth, запись файла куда угодно, XSS, SSRF |
| Инженерные процессы | **4/10** | CI красный, покрытие 61%, нет лицензии, документация расходится с кодом |
| Готовность к публичному запуску | **3/10** | Пункт «безопасность» в PLAN честно помечен ⏳ — и это подтверждается |

> **Статус на 2026-10-30 (после исправлений):** S1–S7 закрыты, B1–B5, B9, B10
> исправлены, CI зелёный, тестов 170 вместо 128. Подробности — раздел 10.

---

## 1. Как проверял

| Шаг | Результат |
|---|---|
| `pytest -m "not browser"` (Python 3.11) | **128 passed**, 21 deselected |
| Всего тестов | **149** (в PLAN заявлено 105) |
| `coverage run -m pytest` | **61 %**; `checks/*` — 12–30 %, `mcp_server` — 0 %, `scanner` — 35 % |
| `ruff check .` | **4 ошибки** → CI-джоба `lint` красная |
| `ruff format --check .` | **1 файл** не отформатирован → CI красная и здесь |
| `playwright install chromium` | Не удалось (в песочнице нет сети до CDN браузеров) |
| Живые PoC через `TestClient` | Подтверждены 8 дыр (ниже) |
| Локальный HTTP-сервер + `crawl()` | Подтверждён баг с `title` из sitemap |

**Ограничение:** браузерные тесты и часть SSRF-сценариев (JS внутри загруженной
страницы) не запускались — Chromium не установился. Всё, что помечено «статически»,
выведено из кода и требует подтверждения на живом браузере.

---

## 2. Дыры безопасности

### P0 — блокеры публичного запуска

---

#### S1. Аутентификации нет вообще, а страница входа не работает

`src/webscope/webapp/app.py:285-308`

В приложении есть маршрут `/auth/login`, форма, пароль по умолчанию
`WEBSCOPE_DEV_PASS=dev` и cookie `webscope_session=auth`. **Ни один маршрут эту
cookie не проверяет** — нет ни middleware, ни зависимости `Depends`. Плюс сама
страница входа падает:

```
GET  /auth/login  -> 500  (TemplateNotFound: 'auth.html' — файла нет в templates/)
GET  /sites       -> 405  (а именно туда редиректит успешный login)
```

PoC (без единой cookie):

```
POST /sites                 -> 303 /sites/1        (создан сайт)
GET  /sites/1/settings      -> 200                 (видны email, telegram, логин)
POST /sites/1/settings      -> 303, в БД: attacker@evil.com / schedule=daily
GET  /api/sites             -> 200                 (весь список сайтов и находок)
```

**Влияние:** любой, кто дотянется до порта, читает и переписывает данные всех
клиентов: подменяет адрес доставки отчётов (утечка отчётов), удаляет сайты,
запускает сканы. Cookie `value="auth"` вообще не подписана — её можно подделать
руками, если проверку добавят «как есть».

**Фикс (минимум):**
```python
# middleware, проверяющий подписанную сессию, + защита /__local и /api
app.add_middleware(SessionMiddleware, secret_key=os.environ["WEBSCOPE_SECRET"])
```
и `Depends(require_user)` на все маршруты, кроме `/healthz` и `/auth/*`.

---

#### S2. `/upload` пишет файлы в любое место файловой системы

`src/webscope/webapp/app.py:552-569`

```python
safe = Path(*[part for part in rel.parts if part not in ("..", ".", "")])
dest = base / safe
```
Фильтр выбрасывает `..`, но **не выбрасывает корень `/`**. Абсолютный путь в
`Path(*parts)` остаётся абсолютным, и `base / safe` его игнорирует.

PoC (реальный HTTP-запрос, ответ 200):

```
POST /upload  files=[index.html]  data={"paths": "/tmp/audit/PWNED2.txt"}
-> файл создан вне каталога загрузки: True
```

**Влияние:** запись произвольного содержимого от имени процесса. Дальше —
перезапись `webscope.db`, конфигов, а при правах выше среднего — и кода.
Jinja2 по умолчанию (`auto_reload=True`) перечитывает шаблоны с диска, поэтому
перезапись `templates/base.html` даёт серверный шаблонный инъекшн, то есть RCE
без перезапуска.

**Фикс:**
```python
dest = (base / safe).resolve()
if not dest.is_relative_to(base.resolve()):
    raise HTTPException(400, "Недопустимый путь")
```
плюс лимит размера файла и общего числа файлов.

---

#### S3. Загруженный HTML исполняется на origin приложения

`app.py:35`, `app.py:647` (`StaticFiles(directory=_LOCAL_DIR, html=True)`)

```
GET /__local/<job>/index.html -> 200  text/html
тело с <script> исполняемое: True
CSP / X-Content-Type-Options / X-Frame-Options: нет
```

Внешние `job_id` — `uuid4().hex`, угадать нельзя, но это не защита: любой может
загрузить свой HTML и получить рабочий URL на вашем домене. Скрипт получает
доступ к `/api/*` с cookie пользователя, читает и удаляет сайты, подменяет
адреса отчётов. Для многопользовательской версии (а она в роадмапе) это
классический stored XSS.

**Хуже:** этот же HTML открывает **серверный** Chromium при сканировании
(`scanner_with_local` разрешает `allow_private` для `/__local/`). То есть
загруженная страница получает сеть вашего хоста: `fetch('http://169.254.169.254/…')`,
внутренние сервисы, админки. Результат можно вынести в отчёт (например, в текст
`console/error`), а отчёт — публичный. Это обход SSRF-защиты целиком.

**Фикс:** отдавать `/__local` с отдельного origin/поддомена, с
`Content-Type: text/plain` + `Content-Disposition: attachment` для не-HTML,
с `Content-Security-Policy: sandbox; default-src 'none'`, с TTL и авторизацией
по владельцу задания.

---

#### S4. SSRF-защита проверяет только первый хост

`scanner.py:45-82` (`validate_target`)

Проверяется `socket.getaddrinfo(host)` стартового URL. Дальше:

* `page.goto` идёт по **редиректам** (публичный хост → `302 http://169.254.169.254/`);
* `crawler.crawl` использует `httpx.Client(follow_redirects=True)` — тоже без проверки;
* `links._check_internal_links` — то же;
* DNS rebinding: хост резолвится дважды (в `validate_target` и в браузере);
* `WEBSCOPE_ALLOW_PRIVATE=1`/`--allow-private` отключает защиту глобально для всех,
  а не для конкретной цели.

В PLAN (§11) прямо написано «блок private IP (DNS-resolve + **проверка редиректов**)»,
но проверки редиректов в коде нет.

**Фикс:** Playwright `route("**/*")` с перехватом и проверкой каждого запроса
(или `context.route` + abort для приватных IP), плюс собственный резолвер для
`httpx`-транспорта, плюс пиннинг IP на время запроса.

---

#### S5. Нет ни лимитов, ни CSRF, ни очереди

* Ни одного rate-limit (grep `rate|limit` по `app.py` — только `limit=` в запросах к БД).
* Пять POST-форм и API-методы без CSRF-токена (`index.html:16`, `settings.html:13`,
  `settings.html:92`, `site.html:46`, `site.html:205`).
* Каждый POST запускает `Playwright` + до 20 страниц обхода. Параллельные запросы =
  столько же Chromium-процессов. Локально это 30–60 с и 300–800 МБ на прогон.

**Влияние:** DoS в один `for`-цикл (`curl` × 50). CSRF сейчас не эксплуатируется
только потому, что аутентификации нет вовсе; как только появится cookie-сессия,
все эти формы станут CSRF-вектором.

**Фикс:** очередь (arq/RQ) с фиксированным числом воркеров, лимит «N активных
сканов на IP/аккаунт», `slowapi`, CSRF-middleware + `SameSite=Strict`, `Secure`.

---

#### S6. Пароли к защищённым сайтам лежат в открытом виде

`webapp/storage.py:32` (`auth_password TEXT`), `storage.py:588`.

При этом в репозитории есть `auth_vault.py` с Fernet — **мёртвый код**: он нигде
не импортируется, а `cryptography` не объявлена в зависимостях (устанавливается
случайно транзитивно; в моём venv `Required-by:` пуст). Статья GDPR/152-ФЗ про
«учётные данные клиентских сайтов» начинается ровно с этого места.

**Фикс:** шифровать перед записью (`WEBSCOPE_AUTH_KEY`), либо вообще не хранить
пароль — хранить только cookie-сессию с TTL, а `auth_vault` либо подключить,
либо удалить вместе с тестом.

---

#### S7. Проверка ссылок выключает TLS-верификацию

`checks/links.py:118`

```python
with httpx.Client(timeout=timeout, follow_redirects=True, verify=False) as client:
```

Все «битые ссылки» проверяются без проверки сертификата: MITM не виден,
самоподписанный сертификат считается нормой, а `https` на самом деле может быть
`http` с прокси. Плюс `httpx.Client` создаётся **на каждую ссылку** (до 20 штук ×
8 потоков) — соединения не переиспользуются.

**Фикс:** `verify=True`, один общий клиент, `HEAD` → `GET` при `403/405`
(многие CDN отдают `403` на `HEAD` — это даёт ложные «битые ссылки»),
пробрасывать cookies сессии, чтобы проверять защищённые сайты.

---

### P1 — до первого платящего клиента

| # | Дыра | Где | Влияние |
|---|---|---|---|
| S8 | Загрузки всех пользователей лежат в общем `/tmp/webscope-local`, не удаляются, раздаются без авторизации | `app.py:35`, `app.py:643` | Утечка чужих сборок, заполнение диска |
| S9 | Нет заголовков безопасности; `/docs` открыт | `create_app` | Раскрытие API-схемы, кликджекинг |
| S10 | Injection в заголовок письма через URL сайта | `alerts.py:123` + `normalize_url` | `ValueError` не ловится → алерт теряется, исключение всплывает в фоновую задачу |
| S11 | `WEBSCOPE_ALLOW_PRIVATE` отключает SSRF-защиту для всего приложения | `scanner.py:60`, `app.py:236` | Один неверный флаг в env — и сервис сканирует вашу сеть |
| S12 | `SMTP` только через `starttls()` — порт 465 (SSL) не поддерживается | `alerts.py:80` | Часть SMTP-провайдеров не подключается |

---

## 3. Баги движка (то, за что платят)

### B1. `/api/sites/{id}/report.sarif` падает с 500

`app.py:633` использует `json.loads`, но `json` не импортирован в модуле.
Это и есть та самая ошибка `F821`, которую ловит `ruff` — то есть **CI это уже
видел, но остался красным и никто не посмотрел**.

```
report.txt  -> 200      report.sarif -> 500
report.json -> 200      report.xml   -> 200
```

### B2. Всем страницам из sitemap присваивается `title` главной → ложные дубли

`crawler.py:288-335`:

```python
if depth > 0:
    ... html = response.text
else:
    html = homepage_html      # ← все seed-URL из sitemap получают HTML главной
```

Все URL из `sitemap.xml` попадают в очередь с `depth=0`, значит их `title` и
`description` — это `title` главной. Дальше `_duplicate_meta_findings` честно
находит «одинаковые заголовки у страниц шаблона».

PoC на локальном сервере (sitemap: `/a/1`, `/a/2` с разными заголовками):

```
http://127.0.0.1:47791/a/1  template=…/a/{id}  title='Главная'   ← должно быть 'Товар первый'
http://127.0.0.1:47791/a/2  template=…/a/{id}  title='Главная'   ← должно быть 'Товар второй'
templates: {'…/a/{id}': ['…/a/1', '…/a/2']}    → одна находка content/duplicate-title
```

**Это ложное срабатывание на каждом сайте с sitemap** — в самом продукте про
«точность находок». Плюс `crawl` отдаёт эти же неверные `title` в JSON.

**Фикс:** качать страницу для любого `depth`, а `homepage_html` использовать
только для стартового URL; sitemap-сиды ставить в очередь с `depth=1`.

### B3. Дифф теряет находки

`history.py:214-215`:

```python
old_by_key = {_key(item): item for item in old.findings}  # dict схлопывает дубли
new_by_key = {_key(item): item for item in new.findings}
```

`_key = (rule, url, selector)`. У документных проверок (`content/duplicate-id`,
`missing-lang`, `no-h1`) `selector is None`, поэтому все находки одного правила
на странице схлопываются в одну.

PoC: появились 2 новых дубля id → `новых находок в диффе: 0`.

**Фикс:** группировать по ключу в списки (`defaultdict(list)`) и матчить
мультимножеством, а лучше — хранить в находке стабильный `fingerprint`
(sha1 от `rule + нормализованный элемент`).

### B4. Артефакт сканера снижает балл сайта

`scoring.py:311-329` + `links.py:162`

`links/limit-reached` — это сообщение **о самом сканере** («проверил 20 из 120
ссылок»), а не дефект сайта. Но `compute_score` берёт все правила без фильтра:

```
чистая страница + links/limit-reached -> score = 99   (ожидается 100)
```

Плюс сама формулировка содержит опечатку: «Проверена **не часть** внутренних ссылок»
(`links.py:164`) — читается как ошибка.

**Фикс:** ввести `Finding.details.kind = "diagnostic"` (или префикс `meta/`) и
исключать такие находки из `summary`, `score` и `top_actions`; в отчёт выводить
отдельной строкой «Корректность проверки».

### B5. Предупреждения из чужих виджетов считаются дефектом сайта

`checks/console.py:56-67` — для `console/warning` не проставляется `details.owner`,
в отличие от ошибок и упавших запросов (строки 43, 93). Политика «чужие виджеты не
дефект сайта» (заявлена в `origins.py` и README) здесь не соблюдается.

PoC: сторонний `console/warning` → `external=0`, `score=99`.

### B6. Не ловятся необработанные JS-исключения

В PLAN (§7) заявлено: `console` ловит «ошибки/варнинги, **uncaught exceptions**,
упавшие запросы». В коде подписка только на `console`, `requestfailed`,
`response` (`scanner.py:404-406`). `page.on("pageerror")` **отсутствует** — а
именно через `pageerror` приходят `TypeError`/`ReferenceError`, которые не
попали в `console.error`. Для инструмента, который продаёт «сайт сломался»,
это пропуск главного сигнала.

### B7. Проверка «кнопку нельзя нажать» видит только первый экран и первые 25 элементов

`checks/interaction.py:68-77`:

```js
if (visW < 8 || visH < 8) return false;   // элементы ниже фолда: visH < 0 → отбрасываются
...
.slice(0, 25)
```

Страница не скроллится, а центр элемента за пределами вьюпорта просто отсекается.
Итог: кнопка «Оформить заказ» в середине страницы не проверяется вообще, и
критичная находка (`interaction/button-blocked`) не появляется. Плюс жёсткий
лимит 25 без всякой пометки в отчёте.

**Фикс:** `el.scrollIntoView({block:'center'})` перед hit-test, лимит вынести в
настройку и сообщать, если упёрлись; обходить элементы порциями по скроллу.

### B8. `viewport/target-size` без исключений WCAG → поток ложных

`checks/viewport.py:48-63` проверяет «ширина или высота < 24 px» для всех
`a, button, input, select, textarea`. В WCAG 2.5.8 есть исключения: inline-ссылки
внутри текста и «достаточный интервал». У axe-core это правило (`target-size`)
уже реализовано вместе с исключениями и даёт в разы меньше шума. Своя проверка
поверх axe — гарантированный источник FP, а вы боретесь именно за FP-rate < 10 %.

Плюс `MIN_TARGET_PX = 24` (`viewport.py:13`) объявлен, но нигде не используется.

### B9. Отчёт пропадает после 20 неудачных прогонов

`webapp/storage.py:422`:

```python
def latest_ok_run(self, site_id):
    for run in self.list_runs(site_id, limit=20):   # ← смотрим только 20 последних
```

PoC: 1 успешный прогон + 20 упавших → `latest_ok_run() is None`. Веб-интерфейс
показывает «Отчёт ещё не готов», хотя отчёт есть.

**Фикс:** `SELECT * FROM runs WHERE site_id=? AND status='ok' ORDER BY id DESC LIMIT 1`.

### B10. `<select>` без `name` не проверяется

`checks/forms/base.py:110`:

```python
if not control.get("name") and control.get("tag") != "select":
```

Селект без `name` не отправляется ровно так же, как инпут. Логика выглядит как
случайная заплатка (возможно, чтобы не шуметь на кастомных селектах), но в коде
нет ни комментария, ни теста.

### B11. `normalize_url` пропускает мусор, но отбрасывает валидное

`app.py:68-78`:

| Вход | Результат | Оценка |
|---|---|---|
| `evil.com\nBcc: victim@x.tld` | принимается как есть | ❌ переводы строк → инъекция в письмо |
| `http://user@127.0.0.1` | принимается | ❌ userinfo перед хостом |
| `a.b:99999` | принимается | ❌ порт вне диапазона |
| `[::1]` | `Похоже, это не адрес сайта` | ❌ валидный IPv6 отклонён |
| `localhost:8080` | `https://localhost:8080` | ⚠️ IPv4/localhost допустимы для скана своих стендов |

**Фикс:** разбирать через `urllib.parse`, отклонять `\r\n`, `username/password`,
проверять порт, разрешать IPv6 в скобках.

### B12. Краулер: robots и шаблоны

* `crawler.py:211` — `robots.txt` с кодом `401/403` считается «правил нет»
  (по спеке 401/403 = запрещено всё).
* `crawler.py:288` — статус главной не проверяется: 404-страница попадает в обход
  как валидная.
* `template_key` понимает только числовые/UUID/hex-сегменты. ЧПУ-каталог
  (`/product/iphone-15`, `/blog/kak-vybrat`) даёт **отдельный шаблон на каждую
  страницу**, и обещание «300 URL → 8 шаблонов» не работает:

```
/product/iphone-15 -> shop.ru/product/iphone-15     ← уникальный «шаблон»
/product/galaxy-s24 -> shop.ru/product/galaxy-s24   ← уникальный «шаблон»
```
  Следствие: `representative_pages` тащит почти все URL, `max_pages` съедается
  первыми 20–30 страницами, а проверка дублей по шаблонам почти не срабатывает.
* Нет учёта `<link rel="canonical">`, `meta robots noindex/nofollow`, нет задержки
  между запросами (вежливость), `queue.pop(0)` — O(n²) на больших сайтах.

### B13. SARIF/JUnit теряют смысл в CI

* SARIF без `partialFingerprints` → GitHub Code Scanning считает каждую находку
  новой на каждом прогоне и заваливает PR повторными алертами.
* JUnit: `tests == failures` всегда, `skipped` не бывает, внешние находки входят
  в `tests`; нет `<system-out>` с селектором и сниппетом.
* `render_sarif` ставит `artifactLocation.uri = полный URL`, хотя SARIF ждёт
  путь/URI относительно репозитория — GitHub покажет ссылку как «внешний файл».

### B14. Мелочи, но дешёвые

* `mcp_server.py:82` — `Severity(min_severity)` кидает `ValueError` на опечатке,
  вместо понятной ошибки инструмента; кэш без ограничения размера (утечка памяти).
* `cli.py` — `--fail-on` по умолчанию `serious` у `scan` и `none` у `crawl`;
  для CI это неожиданно.
* `report.py:187` — `render_junit` не экранирует `type=` (там enum, безопасно),
  но `name`/`message` экранируются только через `html_lib.escape` без учёта
  непечатаемых символов — XML 1.0 их запрещает.
* `app.py:520-533` — `/api/sites/{id}` при отсутствии успешного прогона
  возвращает `findings: []` и `diff: null`, хотя есть `last_error` — интеграции
  не отличить «всё хорошо» от «ещё не проверяли».

---

## 4. Процесс, упаковка, документация

| Находка | Факт |
|---|---|
| CI красный на `main` | `ruff check` — 4 ошибки (включая `F821`), `ruff format --check` — 1 файл |
| Покрытие | 61 %; `checks/content.py` — 12 %, `links.py` — 14 %, `console.py` — 15 %, `mcp_server.py` — 0 % в небраузерной джобе |
| Нет тестов на безопасность | Ни одного теста на `/upload`, авторизацию, CSRF |
| Заявленный Python | `requires-python = ">=3.13"`, но 128 тестов зелёные на **3.11** — порог отсекает пользователей без причины |
| Лицензия | `license = {text = "MIT"}`, а файла `LICENSE` в репозитории **нет** |
| Скрытые зависимости | `python-multipart` (нужен для `Form`/`File`) тянется транзитивно через `mcp`; `cryptography` импортируется тестом, но не объявлена |
| Версии зависимостей | Только нижние границы (`httpx>=0.27`, `playwright>=1.49`, `mcp>=1.2`) → через месяц может не собраться |
| MCP-шим | `mcp>=1.2` + импорт `mcp.server.mcpserver` (mcp 2.x) — путь 1.x никем не тестируется |
| Документация vs код | PLAN: «105 тестов» (факт 149), «v0.3.1» (факт 0.3.0), «uncaught exceptions» (нет), «проверка редиректов» (нет) |
| Нет Docker/деплоя | Нет `Dockerfile`, `docker-compose`, healthcheck-конфига, метрик |
| Нет pre-commit/CI-гейтов | CI не проверяет покрытие, безопасность (`pip-audit`, `bandit`), не запускается на всех ветках |

---

## 5. Что улучшить: приоритеты

### Сейчас (P0, до любого публичного URL) — ~3–5 дней

1. **Аутентификация и сессии**: `itsdangerous`/`SessionMiddleware`, таблица
   пользователей, владелец у сайта, `Depends` на все маршруты; удалить `dev/dev`
   и битую страницу `auth.html` (или написать её).
2. **Безопасный `/upload`**: `resolve() + is_relative_to`, лимит файлов/размера,
   TTL и очистка, отдельный origin для `/__local`, CSP `sandbox`.
3. **SSRF**: перехват всех запросов браузера (`context.route`), проверка IP после
   резолва на каждый хост и после каждого редиректа; вынести `allow_private` в
   явную настройку конкретного сайта, а не глобального env.
4. **Очередь и лимиты**: 1–2 воркера сканов, лимит на IP/аккаунт, таймаут прогона.
5. **Красный CI**: `import json`, `ruff --fix`, `ruff format`, добавить
   `pytest --cov` с порогом и `pre-commit`.
6. **Пароли**: шифрование через `auth_vault` + `cryptography` в зависимостях,
   либо отказ от хранения пароля в пользу cookie-сессии.

### Дальше (P1, точность движка) — ~1–2 недели

7. **Починить `crawl`**: `title`/`description` из реальных страниц (B2),
   canonical/nofollow, `robots` 401/403, статус главной.
8. **Починить дифф**: `defaultdict(list)` + `fingerprint` находки (B3),
   `partialFingerprints` в SARIF (B13).
9. **Разделить «дефект сайта» и «диагностику сканера»**: `limit-reached`,
   `links/unreachable` по таймауту и т.п. не должны влиять на балл (B4).
10. **Точность**: `pageerror` (B6), скролл в `interaction` (B7), axe `target-size`
    вместо своей проверки (B8), `owner` для warning (B5), `latest_ok_run` (B9).
11. **Регресс-набор FP/TP**: сохранить HTML реальных сайтов как фикстуры
    (у вас уже есть `test-fixtures/` — расширить до 20–30 случаев: Tilda, Tilda
    с попапом, cookie-баннер, SPA-логин, ЧПУ-каталог) и гонять их в обычной
    (небраузерной) джобе через `page.set_content`.

### Потом (P2, продукт и процессы)

12. **Мультиарендность**: аккаунты, приглашения для агентств, «портфель сайтов»,
    роли (owner/viewer) — это же снимает churn, о котором вы пишете в PLAN.
13. **Отчёты**: PDF, публичная ссылка с TTL, скриншоты-миниатюры (evidence уже есть,
    но лежит только на диске), email-шаблон в HTML.
14. **Алерты**: Slack/webhook, дайджест «раз в неделю», троттлинг, ретраи,
    поддержка SMTP-SSL (465).
15. **Производительность**: один `httpx.Client` на прогон, параллельные страницы
    (2–3 контекста), кэш статики, отмена прогона.
16. **Наблюдаемость**: structured logging, `request_id`, метрики (длительность
    скана, доля ошибок, FP-rate), Sentry.
17. **Юридика**: подтверждение прав на сканирование, `robots.txt` и для одиночного
    `scan`, политика хранения (сейчас загрузки и история растут бесконечно),
    GDPR-заметка про хранение кредов.
18. **Инфраструктура**: `Dockerfile` + compose, Postgres-адаптер (SQLite уже
    мешает при многопоточности), `pip-audit`/`bandit` в CI, Dependabot,
    `py.typed`, lock-файл (`uv.lock`).
19. **Код**: разбить `app.py` (667 строк) на `routes/pages.py`, `routes/api.py`,
    `services/scans.py`, `services/reports.py`; вынести `_LOCAL_DIR` и upload в
    отдельный модуль `storage_local.py`; дублирующийся рендер `plain`/`text`
    в `report.py` (≈150 строк почти одинаковой логики) свести к одной функции
    с «renderer»-параметром.

---

## 6. Готовые патчи для пяти самых дешёвых дыр

```python
# 1) app.py: json не импортирован
import json  # ← добавить в блок импортов

# 2) app.py: безопасный путь загрузки
safe = Path(*[part for part in rel.parts if part not in ("..", ".", "")])
dest = (base / safe).resolve()
if not dest.is_relative_to(base.resolve()):
    raise HTTPException(status_code=400, detail="Недопустимый путь файла")

# 3) scoring.py: диагностика сканера не влияет на балл
DIAGNOSTIC_RULES = {"links/limit-reached"}
own = [f for f in findings if is_site_defect(f) and f.rule not in DIAGNOSTIC_RULES]

# 4) history.py: не терять дубли в диффе
from collections import defaultdict

old_by_key: dict[tuple, list] = defaultdict(list)
for item in old.findings:
    old_by_key[_key(item)].append(item)
# и в фазе 1/2 матчить по одному элементу из списка, а не по всему ключу

# 5) crawler.py: реальные title вместо главной
if depth > 0 or url != root_url:
    response = client.get(url)
    if response.status_code >= 400:
        result.skipped.append({"url": url, "reason": f"HTTP {response.status_code}"})
        continue
    html = response.text
else:
    html = homepage_html
```

---

## 7. Как воспроизвести проверки

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev,web]"
pytest -m "not browser" -q          # 128 passed
ruff check . && ruff format --check .   # ❌ 4 ошибки + 1 файл
playwright install chromium         # без этого 21 тест не запустится

# PoC: доступ без авторизации и запись мимо каталога
python - <<'PY'
from fastapi.testclient import TestClient
from webscope.webapp.app import create_app
import tempfile, os
app = create_app(db_path=tempfile.mktemp(suffix=".db"), scanner_func=lambda u, o: None)
c = TestClient(app, raise_server_exceptions=False)
print(c.post("/sites", data={"url": "example.com"}, follow_redirects=False).status_code)  # 303
print(c.get("/sites/1/settings").status_code)                                            # 200
print(c.post("/upload", files=[("files", ("a.html", b"x", "text/html"))],
             data={"paths": "/tmp/pwned.txt"}).status_code)                              # 200
print("файл создан:", os.path.exists("/tmp/pwned.txt"))                                  # True
PY
```

---

## 8. Что осталось непроверенным

* Браузерные тесты (21 штука) — нет Chromium в песочнице.
* SSRF через JS загруженной страницы — выведено из кода, требует реального браузера.
* Реальное поведение `interaction` на длинных страницах — проверяется только вручную.
* `mcp` 1.x (путь `FastMCP`) — в окружении стоял `mcp` 2.3.0.
* Воспроизведение FP на живых сайтах (varkacoffee.by из PLAN) — не было доступа.

---

## 9. Итог

У проекта **хорошее ядро и слабая обвязка**. Движок уже умеет то, за что можно
брать деньги (диффы, «что делать», ТЗ для агента), но:

1. **веб-слой — не MVP, а демо**: три P0-дыры дают полный контроль над данными
   и файловой системой хоста;
2. **точность страдает там, где она — главная ценность**: ложные дубли `title`
   на каждом sitemap, пропуск uncaught-исключений и кнопок ниже первого экрана;
3. **процесс не защищает от регрессий**: CI красный, покрытие 61 %, на безопасность
   нет ни одного теста.

Если закрыть P0 (≈ неделя) и B1–B5 (≈ неделя), проект становится тем, чем заявлен:
инструментом, которому владелец сайта верит, а агент — доисполняет.

---

## 10. Что исправлено (2026-10-30)

| Пункт | Как закрыт | Тесты |
|---|---|---|
| S1 — нет аутентификации | Вход по `WEBSCOPE_AUTH_PASSWORD`, middleware на все маршруты, HMAC-cookie вместо `auth`, `/auth/login` с настоящим шаблоном, `/sites` редиректит на главную | `test_security.py::test_pages_require_login`, `test_login_sets_session_and_grants_access`, `test_forged_cookie_is_rejected` |
| S2 — запись мимо каталога | `resolve()` + `is_relative_to`, абсолютные пути и `..` отклоняются, лимиты 300 файлов / 10 МБ / 50 МБ, ротация 50 загрузок | `test_upload_rejects_absolute_path`, `test_upload_keeps_relative_paths_inside`, `test_upload_rejects_huge_file`, `test_prune_removes_old_uploads` |
| S3 — XSS из загруженного HTML | `/__local/` отдаётся с `CSP: sandbox` и `nosniff` | `test_uploaded_page_is_served_in_sandbox` |
| S4 — SSRF через редиректы | `netguard.GuardedTransport` для краулера и проверки ссылок, `context.route` для браузера; в отчёт попадает примечание о блокировке | `test_guarded_transport_blocks_localhost`, `test_crawl_respects_private_network_block` |
| S5 — нет лимитов и CSRF | `RateLimiter` + `WEBSCOPE_MAX_CONCURRENT_SCANS`, CSRF по `Origin`/`Referer`, `/docs` и `/redoc` выключены | `test_rate_limit_stops_scan_loop`, `test_csrf_blocks_foreign_origin`, `test_api_docs_are_closed` |
| S6 — пароли открытым текстом | `auth_vault` (Fernet) подключён к `Storage`, ключ `WEBSCOPE_AUTH_KEY`, старые базы читаются | `test_auth_vault.py::test_storage_encrypts_password_at_rest` |
| S7 — `verify=False` | TLS проверяется, один общий клиент, `HEAD→GET` на 403/405/501 | код проверки ссылок |
| B1 — SARIF 500 | `import json` | `report.sarif → 200` |
| B2 — title из sitemap | sitemap-сиды скачиваются (`depth=1`), статус главной проверяется | `test_crawl_reads_real_titles_from_sitemap` |
| B3 — дифф терял находки | мультимножества вместо dict, двухфазное сопоставление сохранено | `test_diff_keeps_new_duplicates_without_selector` |
| B4 — артефакт сканера снижал балл | `DIAGNOSTIC_RULES` исключены из балла и топ-действий, опечатка в тексте исправлена | `test_diagnostic_findings_do_not_affect_score` |
| B5 — warning чужих виджетов | `details.owner` проставляется и для предупреждений | `test_console_units.py` |
| B9 — отчёт исчезал | `latest_ok_run` запросом по всей истории | `test_report_survives_long_failure_streak` |
| B10 — `<select>` без `name` | проверка снова работает | — |
| B6 — uncaught JS | добавлен `page.on("pageerror")` | `test_checks` (браузер) |
| B7/B8 (скролл в `interaction`, `target-size`) | **не закрыто** — требует браузерных тестов и отдельного решения по FP | — |
| Процесс | `ruff check`/`format` зелёные, `LICENSE` добавлен, `cryptography`/`python-multipart` объявлены, версия 0.3.1 | CI |

Осталось (P1/P2): `pageerror` (B6), скролл в `interaction` (B7), axe `target-size`
(B8), SARIF `partialFingerprints`, PDF и мультиарендность.
