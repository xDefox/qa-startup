# webscope v0.3.1 — технический обзор (P0–P1)

## Архитектура слоёв

```
CLI (cli.py) → Scanner (scanner.py) → Checks (checks/*) → Report (report.py) → Output (JSON/SARIF/HTML/text)
```

- `scanner.py`: `validate_target()` (SSRF, `netguard.py`), `crawl()` (Playwright), `install_private_network_guard()`.
- `checks/`: `a11y`, `forms`, `links`, `content`, `viewport`, `console`, `interaction`, `js`. Каждый — детерминированный, без LLM.
- `models.py`: `Finding` (`Severity`: critical/serious/moderate/minor/ok), `ScanResult`, `AuthCredentials`.
- `report.py`: `render_json()`, `render_sarif()`, `render_plain()`, `render_html()`.
- `scoring.py`: `plain_impact()`, `score_label()`, `top_actions()`.

## Webapp (FastAPI)

`webscope/webapp/app.py` (~960 строк после разделения):
- `lifespan` — `scheduler.start()` / `.stop()`, `storage.reconcile_running()`.
- Middleware `guard` (`auth_configured()`, `is_public_path()`, `csrf_safe()`, `is_authenticated()`).
- `routes/auth.py`: `auth_login_form` (GET `/auth/login`), `auth_login` (POST, `Form` + `check_credentials`), `auth_logout`.
- `routes/pages.py`: заглушки (`index_cards`, `index`, `list_sites` — функции не перенесены из `app.py`).
- `routes/upload.py`: заглушка.
- `routes/api.py`: заглушка.
- `storage_local.py`: `_LOCAL_DIR`, `_prune_local_uploads()`, `_SandboxedLocalFiles` (CSP sandbox).

### Безопасность P0 (закрыто)

| Пункт | Файл | Строки | Статус |
|---|---|---|---|
| S1 Auth middleware | `auth.py` | 57 (`is_authenticated`) | ✅ HMAC cookie |
| S2 Upload `/__local` | `app.py` | 261 (`_SandboxedLocalFiles.get_response`) | ✅ `auth_configured()` + `is_authenticated()` |
| S3 XSS / CSP | `app.py` | 259 (`SANDBOX`) | ✅ `sandbox allow-scripts`, `nosniff`, `no-store` |
| S4 SSRF | `scanner.py` | 146 (`validate_target`) | ✅ `env` удалён; `netguard.py` (`getaddrinfo`) |
| S5 Лимиты/CSRF | `auth.py` | 88 (`csrf_safe`) | ✅ `Origin`/`Referer` проверка |
| S6 Пароли | `auth_vault.py` | 1 (`Fernet`) | ✅ `cryptography` в `dependencies` |
| S7 TLS | `checks/links.py` | 146 | ✅ `verify` не отключён |

### Экономика

- `billing.py`: `PlanName` (`FREE`/`SOLO`/`STUDIO`/`AGENCY`), `SubscriptionStatus`, `Subscription`, `Invoice`.
- `storage.py`: `_seal()` / `_open()` для `auth_vault`.
- `PLAN.md` §9: Milestone 4 (биллинг) — `⏳`; Milestone 5 (спрос) — 10 пилотов с метрикой `fixed_findings > 0` (≥60%).

### CI / Качество

- `ruff check .` — зелёный.
- `ruff format --check .` — зелёный.
- `pytest tests/test_security.py` — 4 теста (1 падает: `test_auth_middleware_applied` — `importlib` не находит `guard`).
- Покрытие: `mcp_server` 0%, `checks/*` 12–30%, `scanner` 35% (`AUDIT.md`).

## Следующие шаги (P1)

1. Перенос функций `app.py` → `routes/pages.py` (`index_cards`, `index`, `sites_index`, `site_delete` и т.д.).
2. Расширение `tests/test_security.py`: `/upload` (лимиты), `/__local` (auth), CSRF (POST без cookie), SSRF-редирект (`netguard` с `getaddrinfo`).
3. Подключение `routes/pages.py` в `app.py` (уже подключено через `include_router`).
4. Миграция `BILLING_MIGRATION` (`storage.py`) или ручной учёт пилотов.
