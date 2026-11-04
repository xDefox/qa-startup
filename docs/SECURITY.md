# webscope — Безопасность (AUDIT fixes 2026-10-30)

> Полный аудит S1–S7, B1–B5. Статус: закрыты. См. AUDIT.md §2, §10.

---

## S1. Аутентификация / middleware

- **Где:** `auth.py:34` (`auth_configured()`), `auth.py:57` (`is_authenticated()`), `auth.py:88` (`csrf_safe()`), `app.py:450` (`guard` middleware).
- **Проблема:** ни один маршрут не проверял cookie `webscope_session` — ни middleware, ни `Depends`.
- **Реализация:**
  - `auth_configured()` — проверяет `WEBSCOPE_AUTH_PASSWORD` в env; если выключен, все маршруты открыты.
  - `is_authenticated(request)` — валидация HMAC-коokie: `secret, token = cookie.split("|")`; `hmac.compare_digest(hmac.new(secret.encode(), token.encode(), hashlib.sha256).hexdigest(), token)`.
  - `csrf_safe()` — проверяет `Origin` / `Referer` headers; при mismatch возвращает 403.
  - Middleware `guard` в `app.py:450` оборачивает все маршруты, кроме `/healthz`, `/auth/*`, `/static`.
- **Тест:** `test_security.py::test_pages_require_login`, `test_login_sets_session_and_grants_access`, `test_forged_cookie_is_rejected`, `test_csrf_blocks_foreign_origin`.

---

## S2. `/upload` — запись за пределы каталога

- **Где:** `app.py:785` (`upload_files`).
- **Было:** `Path(*[part for part in rel.parts if part not in ("..", ".", "")])` — отбрасывал `..`, но не корень `/`.
- **Стало:** `dest = (base / safe).resolve()` + `if not dest.is_relative_to(base.resolve()): raise 400`.
- **Лимиты:** `MAX_UPLOAD_FILE_BYTES=10 МБ`, `MAX_UPLOAD_TOTAL_BYTES=50 МБ`, `MAX_UPLOAD_FILES=300`.
- **Ротация:** `_prune_local_uploads` удаляет старые (50 последних) при каждой загрузке.
- **Тест:** `test_upload_rejects_absolute_path`, `test_upload_keeps_relative_paths_inside`, `test_upload_rejects_huge_file`, `test_prune_removes_old_uploads`.

---

## S3. Загруженный HTML — stored XSS / origin

- **Где:** `app.py:259` (`_SandboxedLocalFiles.get_response`), `app.py:865` (`StaticFiles(directory=_LOCAL_DIR, html=True)`).
- **Было:** HTML исполнялось на origin с CSP-проigem.
- **Стало:** `/__local/` отдаётся с `Content-Security-Policy: sandbox; default-src 'none'; script-src 'self' 'unsafe-inline'`, `X-Content-Type-Options: nosniff`, `Cache-Control: no-store`.
- **Для сканера:** `scanner_with_local` разрешает `allow_private` explicit per-site, cookie не требуется.
- **Тест:** `test_uploaded_page_is_served_in_sandbox`.

---

## S4. SSRF — проверка только первого хоста, редиректы

- **Где:** `scanner.py:146` (`validate_target`), `scanner.py:188` (`install_private_network_guard`), `netguard.py` (`GuardedTransport`).
- **Было:** `validate_target` проверял только начальный хост через `getaddrinfo`; редиректы блокировались не были.
- **Стало:**
  - `validate_target` отклоняет приватные IP (127.0.0.1, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, link-local).
  - `install_private_network_guard` перехватывает **каждый** запрос браузера (`context.route`) и блокирует приватные адреса и редиректы на них.
  - `GuardedTransport` для `httpx.Client` / краулера: тот же check на каждом HTTP-запросе.
- **Тест:** `test_guarded_transport_blocks_localhost`, `test_crawl_respects_private_network_block`.

---

## S5. Нет лимитов, CSRF, очереди

- **Где:** `auth.py:88` (`csrf_safe`), `app.py:397` (`RateLimiter`, `scan_limit_response`), `scheduler.py`.
- **Реализация:**
  - `csrf_safe` проверяет `Origin` / `Referer`.
  - `RateLimiter` (Rate limiter per IP/прокси: `x-forwarded-for` + trusted-hosts check).
  - `max_concurrent_scans=2` (параллельные прогоны).
  - `Schedule` не запускает больше сканов, чем лимит.
- **Тест:** `test_rate_limit_stops_scan_loop`, `test_csrf_blocks_foreign_origin`, `test_api_docs_are_closed`.

---

## S6. Пароли открытым текстом

- **Где:** `auth_vault.py` (Fernet), `storage.py:_seal` / `_open`.
- **Реализация:** Fernet encryption (`cryptography`) перед записью в БД (`_seal`) и после чтения (`_open`).
- **Зависимости:** `cryptography>=43` в `dependencies` (было только в `[optional]`).
- **Тест:** `test_auth_vault.py::test_storage_encrypts_password_at_rest`.

---

## S7. TLS-верификация отключена

- **Где:** `checks/links.py:146`.
- **Статус:** `verify` не отключён (по умолчанию `True`). Используется один общий `httpx.Client`.
- **Дополнительно:** `HEAD→GET` на `403/405/501` (многие CDN отдают `403` на `HEAD` — это даёт ложные «битые ссылки»).

---

## B1. `/api/sites/{id}/report.sarif` 500

- **Где:** `report.py:187`.
- **Было:** `json` не импортирован → `F821` + `json.JSONDecodeError`.
- **Стало:** добавлен `import json` в блок импортов; SARIF now has `partialFingerprints`.

---

## B2. Title из sitemap → ложные дубли

- **Где:** `crawler.py:288-335`.
- **Было:** все URL из sitemap получали `title` главной (`depth=0`).
- **Стало:** sitemap-сиды качаются (`depth=1`), статус главной проверяется отдельно.

---

## B3. Дифф терял находки

- **Где:** `history.py:214-215`.
- **Было:** `dict` схлопывал дубли по ключу `(rule, url, selector)`.
- **Стало:** `defaultdict(list)` + двухфазное сопоставление (по селектору → по нормализованному фрагменту).

---

## B4. Артефакт сканера снижал балл

- **Где:** `scoring.py:311-329`, `links.py:162`.
- **Было:** `links/limit-reached` влияло на score (99 вместо 100).
- **Стало:** `DIAGNOSTIC_RULES = {"links/limit-reached"}` исключаются из score и top_actions; опечатка в тексте исправлена («не часть» → «не вся»).

---

## B5. Предупреждения чужих виджетов

- **Где:** `checks/console.py:56-67`.
- **Было:** `details.owner` проставлялось только для ошибок.
- **Стало:** proставляется и для предупреждений (`warning`); `external` счётчик; балл только по сайту.

---

## B9. Отчёт исчезал после 20 неудачных прогонов

- **Где:** `storage.py:422` (`latest_ok_run`).
- **Было:** `limit=20` в запросе.
- **Стало:** `SELECT * FROM runs WHERE site_id=? AND status='ok' ORDER BY id DESC LIMIT 1` (без лимита 20).

---

## S8–S12 (в аудите, P1)

| # | Дыра | Статус | Ссылка |
|---|---|---|---|
| S8 | Loading path общее `/tmp/` | ⏳ P1 | скриншот/обсуждение |
| S9 | Нет заголовков безопасности / `/docs` открыт | ⏳ P1 | CSP, заголовки |
| S10 | Injection в заголовок письма | ⏳ P1 | `normalize_url`, валидация |
| S11 | `WEBSCOPE_ALLOW_PRIVATE` отключает защиту | ⏳ P1 | env → явный параметр |
| S12 | SMTP только starttls | ⏳ P1 | port 465 (SSL) |