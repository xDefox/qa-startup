# Детальный план исправлений — webscope v0.3.1 (P0 / P1)

Рабочая директория: `/home/kuga/Work/qa-startup`

---

## 1. P0 — Безопасность (S1–S7)

### S1. Аутентификация / middleware
- **Где:** `src/webscope/webapp/app.py` 450–464 (`guard` middleware); `auth.py` 34–60; `routes_auth.py` (битый файл, строка 14 содержит `...`).
- **Что сломано:** `routes_auth.py` — синтаксическая ошибка (`...` в параметре функции), `auth_login_post` не принимает `templates`, поэтому `/auth/login` падает. Middleware в `app.py` работает, но `routes_auth.py` ломает CI и сборку.
- **Правка:**
  - Удалить `routes_auth.py` или заменить на рабочий `routes/auth.py` (см. §4).
  - Убедиться, что `auth_configured()` (`auth.py:34`) и `is_authenticated()` (`auth.py:57`) используются в `guard`.
  - Добавить тесты безопасности (`tests/test_security.py`) для `/upload`, `/__local`, CSRF — их нет в репозитории.

### S2. `/upload` — запись за пределы каталога
- **Где:** `src/webscope/webapp/app.py` 757–824 (`upload_files`).
- **Что уже исправлено:** строки 785–793 (`resolve()` + `is_relative_to(base.resolve())`), `is_absolute()` (строка 786), лимиты размера (`MAX_UPLOAD_FILE_BYTES` 10 МБ, `MAX_UPLOAD_TOTAL_BYTES` 50 МБ, `MAX_UPLOAD_FILES` 300) — строки 794–797.
- **Что осталось (P0):**
  - Добавить проверку доступа к `/__local/{job_id}` при `auth_configured()`. В `_SandboxedLocalFiles.get_response` (`app.py:207`) или через middleware проверить `is_authenticated(request)`.
  - Убедиться, что `_prune_local_uploads` (`app.py:181`) удаляет старые задания; можно вызвать в `lifespan` или при `get_response`.

### S3. Загруженный HTML — stored XSS / origin приложения
- **Где:** `app.py` 195–213 (`_SandboxedLocalFiles`), `app.py:865` (монтирование `StaticFiles`).
- **Что уже исправлено:** CSP `sandbox allow-scripts ...` (строка 205), `X-Content-Type-Options: nosniff`, `Cache-Control: no-store` (строки 210–212).
- **Что осталось (P0):**
  - Убедиться, что `/__local/` не доступен без авторизации при включённом `auth_configured()` (если это не сканер). Для сканера (`scanner_with_local`, строка 376) разрешается `allow_private=True`, но cookie не требуется.
  - Усилить `CSP` до `sandbox; default-src 'none'; script-src 'self' 'unsafe-inline'`.

### S4. SSRF — проверка только первого хоста, редиректы
- **Где:** `scanner.py` 146–175 (`validate_target`), 188–217 (`install_private_network_guard`); `netguard.py` (`GuardedTransport`, `is_forbidden_address`, `url_targets_private_network`).
- **Что уже исправлено:** `validate_target` проверяет `socket.getaddrinfo` и отклоняет приватные IP; `install_private_network_guard` перехватывает каждый запрос браузера (`context.route`) и блокирует приватные адреса.
- **Что осталось (P0):**
  - Убрать `os.environ.get("WEBSCOPE_ALLOW_PRIVATE")` из `validate_target` (строка 162) или ограничить его до параметра `allow_private` функции, чтобы глобальный env не отключал защиту.
  - В `netguard.py` (`url_targets_private_network`) добавить `socket.getaddrinfo` для каждого хоста, чтобы редиректы на приватные IP блокировались даже через DNS-rebinding.
  - В `checks/links.py` (строки 146–152) убедиться, что `httpx.Client` не использует `verify=False` (в текущей версии `verify` не указан, по умолчанию `True` — это хорошо). Добавить проверку `response.url` на приватный адрес после редиректа или отключить `follow_redirects` для `links`.

### S5. Нет лимитов, CSRF, очереди
- **Где:** `auth.py` 88–101 (`csrf_safe`), `limits.py`, `app.py` 397–413 (`RateLimiter`, `scan_limit_response`).
- **Что уже исправлено:** `csrf_safe` проверяет `Origin`/`Referer`; `RateLimiter` ограничивает запуски; `max_concurrent_scans` (строка 407) ограничивает параллельные сканы.
- **Что осталось (P0):**
  - Улучшить ключ `RateLimiter`: `request.client.host` (`app.py:399`) не учитывает прокси. Добавить `request.headers.get("x-forwarded-for", ...).split(",")[0].strip()` с проверкой `trusted_hosts`.
  - Убедиться, что `Schedule` (`scheduler.py`) не запускает больше сканов, чем `max_concurrent_scans`.

### S6. Пароли открытым текстом
- **Где:** `auth_vault.py` 1–67, `storage.py` 84–91 (`_seal` / `_open`).
- **Что уже исправлено:** `auth_vault.py` использует `Fernet` (`cryptography`); `Storage` вызывает `_seal` при вставке/обновлении (`storage.py:301`, `335`) и `_open` при чтении (`storage.py:629`).
- **Что осталось (P0):**
  - Добавить `cryptography>=43` в `dependencies` (`pyproject.toml` строка 9) — сейчас она только в `[project.optional-dependencies]` (`dev`, `web`). Без этого `auth_vault.py` не работает при установке без `[dev,web]`.
  - Добавить `python-multipart>=0.0.9` в `dependencies` (строка 9) — требуется для `Form`/`File` в `upload`.

### S7. TLS-верификация отключена
- **Где:** `checks/links.py` (строки 146–152). В текущей версии `verify` не указан (по умолчанию `True`). Аудит упоминает `verify=False`, но в коде этого нет — возможно, исправлено ранее.
- **Правка:** убедиться, что `verify=True` или не отключено; использовать один общий `httpx.Client` (уже сделано, строка 146).

---

## 2. Auth middleware — текущее состояние

- `auth.py`: `auth_configured()` (строка 34), `is_authenticated()` (57), `csrf_safe()` (88), `cookie_kwargs()` (104) — рабочие.
- `app.py`: middleware `guard` (450–464) проверяет `auth_configured()` и `is_public_path()`; `is_authenticated()` проверяет HMAC-cookie; `csrf_safe()` проверяет `Origin`/`Referer`.
- `routes_auth.py`: **битый** — содержит `...` в параметре функции (`request: Request, ...`), что вызывает `invalid-syntax`. Этот файл нужно либо исправить, либо удалить, т.к. `auth_login`, `auth_logout` уже есть в `app.py` (467–493).

---

## 3. `/upload` — конкретные правки

**Файл:** `src/webscope/webapp/app.py`

**Строки 776–824 (`upload_files`) — текущее состояние (уже исправлено):**
- `relative.is_absolute()` (786) — отклоняет абсолютные пути.
- `(base / safe).resolve()` + `.is_relative_to(base.resolve())` (791–793) — отклоняет выход за каталог.
- `MAX_UPLOAD_FILE_BYTES` (59) = 10 МБ, `MAX_UPLOAD_TOTAL_BYTES` (60) = 50 МБ, `MAX_UPLOAD_FILES` (58) = 300 — лимиты размера и числа файлов.
- `_prune_local_uploads` (181) — удаляет старые задания.

**Оставшиеся правки (P0):**
- В `_SandboxedLocalFiles.get_response` (`app.py:207`) добавить проверку доступа при `auth_configured()`.
- В `apply_headers` (`auth.py:127`) добавить `X-XSS-Protection` и `Referrer-Policy` (частично уже есть `nosniff` и `same-origin`).

---

## 4. SSRF — конкретные правки

**Файл:** `src/webscope/scanner.py`

**Строки 146–175 (`validate_target`):**
- Убрать `os.environ.get("WEBSCOPE_ALLOW_PRIVATE")` (строка 162) или ограничить до параметра функции.

**Строки 188–217 (`install_private_network_guard`):**
- Убедиться, что `context.route` блокирует каждый запрос на приватный адрес; добавить `socket.getaddrinfo` в `url_targets_private_network` (`netguard.py`) для проверки хоста после редиректа.

**Файл:** `src/webscope/netguard.py`
- Добавить `getaddrinfo` для каждого `hostname` в `url_targets_private_network`, чтобы блокировать редиректы на локальные/приватные IP даже через DNS-rebinding.

**Файл:** `src/webscope/checks/links.py`
- Убедиться, что `verify` не отключен (`verify=False` отсутствует — хорошо).
- Добавить проверку `response.url` на приватный адрес после `client.get` или отключить `follow_redirects`.

---

## 5. Разделение `app.py` (888 строк в текущей версии)

**Предлагаемая структура:**

```
src/webscope/webapp/
  app.py              # FastAPI, middleware, lifespan, подключение роутеров (≤ 150 строк)
  auth.py             # без изменений
  routes/
    __init__.py
    auth.py           # /auth/login, /auth/logout (исправленный routes_auth.py)
    pages.py          # /, /sites, /sites/{id}, /sites/{id}/history, /sites/{id}/settings, /sites/{id}/delete
    api.py            # /api/sites, /api/sites/{id}, /api/sites/{id}/runs, /api/sites/{id}/scan, /api/...
    upload.py         # /upload
  services/
    __init__.py
    scans.py          # trigger(), scan_limit_response(), build_report_view()
    reports.py         # report_payload(), _result_from_run(), download_filename()
  storage_local.py     # _LOCAL_DIR, _prune_local_uploads(), _SandboxedLocalFiles(), upload_files()
```

**Конкретное распределение функций из `app.py`:**

- `routes/auth.py`: `auth_login_form`, `auth_login`, `auth_logout` (строки 467–493).
- `routes/pages.py`: `index_cards`, `index`, `sites_index`, `site_page`, `site_history`, `site_settings`, `site_settings_save`, `site_delete` (строки 497–699).
- `routes/api.py`: `healthz`, `api_sites`, `api_site`, `api_runs`, `api_scan` (703–755), а также `api_report_*` (844–862).
- `routes/upload.py`: `upload_files` (757–824).
- `services/scans.py`: `trigger`, `scan_limit_response` (397–429), `build_report_view` (243–323).
- `services/reports.py`: `report_payload`, `report_response` (825–843), `_result_from_run` (872–885), `download_filename` (156–168).
- `storage_local.py`: `_LOCAL_DIR`, `MAX_UPLOAD_*`, `_prune_local_uploads`, `_SandboxedLocalFiles`, `upload_files`.

**Как это влияет на `app.py`:**
- После разделения `app.py` содержит только `create_app()`, `lifespan`, `guard` middleware, подключение роутеров и `mount_local`. Это уменьшает файл до ~120 строк.

---

## 6. CI — исправление `ruff` и `format`

**Текущие ошибки (`ruff check .`):**
- `routes_auth.py:14` — `invalid-syntax`: `...` в параметре функции.
- `app.py:7` — `I001`: импортный блок не отсортирован / не отформатирован.
- `app.py` — возможен `F821` (если `json` не импортирован; в текущей версии это исправлено, но стоит проверить).

**Текущие ошибки (`ruff format --check .`):**
- `app.py` — 1 файл не отформатирован (строка 46 — отсутствует пустая строка после `)`).

**Конкретные исправления:**
1. Удалить или исправить `routes_auth.py` (см. §5 — заменить на `routes/auth.py`).
2. `ruff format src/webscope/webapp/app.py` — исправляет строку 46.
3. `ruff check src/webscope/webapp/app.py --select I001 --fix .` — исправляет сортировку импортов.
4. В `pyproject.toml` (строка 9) добавить `cryptography>=43` и `python-multipart>=0.0.9` в `dependencies`.
5. Убедиться, что `tests/test_webapp_auth.py` проходит (`pytest tests/test_webapp_auth.py -q`).

---

## 7. Итоговая таблица: что исправлено / что осталось / кто делает

| Пункт | Файл(ы) | Строки | Статус | Что сделать |
|---|---|---|---|---|
| S1 Auth | `routes_auth.py` | 14 | ❌ битый | Удалить или заменить на `routes/auth.py` |
| S1 Auth | `app.py` | 450–464 | ✅ middleware работает | Убедиться в тестах |
| S2 Upload | `app.py` | 757–824 | ✅ `resolve()` + лимиты | Добавить авторизацию `/__local` (P0) |
| S3 XSS / local | `app.py` | 195–213, 865 | ✅ CSP sandbox | Усилить заголовки (P1) |
| S4 SSRF | `scanner.py` | 146–175, 188–217 | ✅ `validate_target` + `route` | Убрать `env` из защиты (P0); добавить DNS-резолв в `netguard` (P0) |
| S4 SSRF | `netguard.py` | — | ⚠️ | Добавить `getaddrinfo` для каждого хоста |
| S5 Лимиты / CSRF | `auth.py` | 88–101 | ✅ `csrf_safe` | Улучшить ключ лимита (`X-Forwarded-For`) (P1) |
| S6 Пароли | `auth_vault.py` | 1–67 | ✅ Fernet | Добавить `cryptography` в `dependencies` (P0) |
| S6 Пароли | `storage.py` | 84–91 | ✅ `_seal` / `_open` | Убедиться в совместимости старых БД |
| S7 TLS | `checks/links.py` | 146–152 | ✅ `verify` не отключен | Убедиться в `verify=True` (P0) |
| Разделение app.py | `routes/` | — | ❌ нет файлов | Создать `routes/auth.py`, `routes/pages.py`, `routes/api.py`, `routes/upload.py` (P0) |
| Разделение app.py | `services/` | — | ❌ нет файлов | Создать `services/scans.py`, `services/reports.py` (P1) |
| Разделение app.py | `storage_local.py` | — | ❌ нет файла | Вынести `_LOCAL_DIR`, `_SandboxedLocalFiles`, `_prune_local_uploads` (P1) |
| CI — ruff | `routes_auth.py` | 14 | ❌ синтаксис | Удалить или исправить (P0) |
| CI — ruff | `app.py` | 7 | ❌ `I001` | `ruff check --fix .` (P0) |
| CI — format | `app.py` | 46 | ❌ не отформатирован | `ruff format .` (P0) |
| CI — deps | `pyproject.toml` | 9 | ⚠️ `cryptography`, `python-multipart` | Добавить в `dependencies` (P0) |

---

## 8. Рекомендуемый порядок действий

1. **P0 (1–2 дня):**
   - Удалить/исправить `routes_auth.py` → `routes/auth.py`.
   - `ruff format .` + `ruff check --fix .`.
   - Добавить `cryptography` и `python-multipart` в `pyproject.toml`.
   - Убедиться, что `tests/test_webapp_auth.py` проходит.

2. **P0 (2–3 дня):**
   - Исправить SSRF: убрать `env` из `validate_target`, усилить `netguard` с `getaddrinfo`.
   - Добавить базовые тесты безопасности (`test_upload`, `test_local_access`, `test_ssrf_redirect`).

3. **P1 (3–5 дней):**
   - Разделить `app.py` в `routes/` и `services/` (см. §5).
   - Добавить `services/scans.py`, `services/reports.py`, `routes/auth.py`, `routes/pages.py`, `routes/api.py`, `routes/upload.py`.
   - Добавить `pre-commit` или `tox` для CI.

4. **P1 (1–2 недели):**
   - Починить движок: `crawler.py` (title из sitemap — B2), `history.py` (дифф — B3), `scoring.py` (диагностика — B4), `console.py` (warning — B5), `interaction.py` (скролл — B7), `viewport.py` (axe — B8), `links.py` (verify — S7).
   - Добавить `LICENSE` (отсутствует в репозитории, хотя `pyproject.toml` указывает MIT).
