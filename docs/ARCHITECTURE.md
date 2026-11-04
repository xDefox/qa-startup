# webscope — Архитектура и дизайн-решения

> Единый источник правды по архитектуре. Ссылки из PLAN.md §§6–8, 12, 14 и LECTURE.md.
> Статус: **v0.3.1 + AUDIT fixes (2026-10-30)**.

---

## 1. Слоистая архитектура

```
┌─────────────────────────────────────────────────────────────┐
│  CLI (cli.py) / MCP (mcp_server.py) / CI (exit code)       │
│  Веб (FastAPI: webapp/app.py → routes/*)                    │
└────────────────────────────────┬────────────────────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │   webscope.core         │
                    │  ┌───────────────────┐  │
                    │  │ crawler.py        │  │  ← robots.txt, sitemap, шаблоны
                    │  │ scanner.py        │  │  ← Playwright, archetype, checks
                    │  │   ├ archetype.py  │  │  ← детектор стека/UI-кита
                    │  │   └ checks/*      │  │  ← 7 модулей проверок
                    │  │       a11y        │  │     axe-core 4.11 (WCAG 2.0/2.1/2.2)
                    │  │       content     │  │     lang, title, og, h1, alt, дубли id
                    │  │       forms       │  │     label, name, autocomplete, кнопки
                    │  │       links       │  │     href=#, noopener, mixed, битые
                    │  │       console     │  │     errors, warnings, uncaught, failed
                    │  │       viewport    │  │     overflow 320/768, target-size 24px
                    │  │       interaction │  │     кнопку нельзя нажать (hit-test)
                    │  │       js          │  │     (заглушка, не используется)
                    │  ├ scoring.py       │  │  ← балл 0–100 + человеческий язык
                    │  ├ history.py       │  │  ← снимки, диффы, тренд
                    │  ├ models.py        │  │  ← Finding, ScanResult, схемы JSON
                    │  └ report.py        │  │  ← text/plain/json/html/sarif/fix-prompt
                    └─────────────────────┘  │
                                 │          │
                    ┌────────────▼────────────┐
                    │   webscope.webapp       │
                    │   scheduler → monitor → │
                    │   SQLite (sites, runs,  │
                    │   findings, diffs) →    │
                    │   alerts (email, TG)    │
                    └─────────────────────────┘
```

**Принцип:** `checks/*` — чистые функции `(page, ctx) → list[Finding]`. Не знают про отчёт/MCP/БД. Это даёт детерминизм и тестируемость без браузера.

---

## 2. Схема данных (JSON v1.0)

```jsonc
{
  "schema_version": "1.0",
  "url": "https://example.com",
  "final_url": "https://example.com/",
  "title": "Example",
  "archetype": {"framework": "next", "cms": null, "ui_kit": "tailwind"},
  "duration_ms": 3120,
  "pages_scanned": 1,
  "findings": [
    {
      "rule": "content/image-alt",
      "severity": "serious",
      "title": "Изображение без alt",
      "message": "У <img> нет атрибута alt",
      "url": "https://example.com/",
      "selector": "main > div:nth-child(2) > img",
      "snippet": "<img src=\"/logo.png\">",
      "help_url": "https://www.w3.org/WAI/WCAG22/Understanding/non-text-content.html",
      "source": "webscope.content",
      "details": {"evidence": "002_content_image_alt.png"}
    }
  ],
  "summary": {"critical": 0, "serious": 1, "moderate": 4, "minor": 2, "total": 7}
}
```

- `schema_version` — semver. Поля только добавляем, не удаляем.
- `details` — расширяемый объект (evidence, owner, fp, location, fingerprint, ...).
- `source` — модуль, создавший находку (`webscope.content`, `webscope.a11y`, ...).
- `help_url` — прямая ссылка на WCAG/MDN/спецификацию для человека и агента.

---

## 3. Набор проверок (7 модулей)

| Check | Правила (ключевые) | Severity | Источник |
|---|---|---|---|
| `a11y` | axe-core: wcag2a, wcag2aa, wcag21a, wcag21aa, wcag22aa, best-practice | по impact | vendor/axe.min.js |
| `content` | lang, charset, title, description, viewport, og-теги, h1, order, img-alt, iframe-title, empty-link-name, duplicate-id | serious→minor | свои |
| `forms` | input-no-label, label-placeholder-only, input-no-name, email-autocomplete, submit-accessible-name | serious→minor | свои |
| `links` | href-hash, blank-no-noopener, mixed-content, internal-broken, timeout | serious→minor | свои |
| `console` | error, warning, pageerror (uncaught), requestfailed | serious→moderate | свои |
| `viewport` | overflow-320, overflow-768, target-size | serious→minor | свои |
| `site` | duplicate-title, duplicate-description | moderate→minor | crawl |

**FP-дедуп:** находки, совпадающие с axe-правилом по элементу, схлопываются (`_AXE_EQUIVALENTS` в `checks/content.py`). Для проверок уровня документа (lang, title, h1) — по URL страницы.

---

## 4. Archetype-детектор (`archetype.py`)

```python
# Признаки → действия
{
  "next": ["__NEXT_DATA__", "data-reactroot"],
  "react": ["data-reactroot"],
  "vue": ["Vue", "data-v-"],
  "angular": ["ng-version"],
  "wordpress": ["wp-content"],
  "shopify": ["Shopify.theme", "cdn.shopify"],
  "antd": ["ant-*"],
  "mui": ["Mui*"],
  "bootstrap": ["btn btn-", "col-"],
  "tailwind": ["flex", "px-", "text-", "grid"]
}
```

**Назначение:** внутренний механизм выбора профиля проверок (SPA-навигация, компонентные паттерны, сетка). Не маркетинговая фишка.

---

## 5. MCP-инструменты (`mcp_server.py`)

| Инструмент | Вход | Выход | Назначение |
|---|---|---|---|
| `scan_page` | `url, checks?, timeout_ms?` | `ScanResult` (JSON) | Полный скан для агента |
| `list_findings` | `url, min_severity?` | краткий список | Быстрый обзор |
| `get_fix_prompt` | `url, rules?` | промпт для coding-агента | **Ключевая фишка**: ТЗ с селектором, HTML, WCAG, критерий приёмки |

Цикл: `scan_page` → `get_fix_prompt` → правка кода → `scan_page` повторно.

---

## 6. Веб-слой (FastAPI) — структура после разделения

| Файл | Ответственность | Строк |
|---|---|---|
| `app.py` | сборка: storage, monitor, routers, middleware, lifespan | ~960 |
| `state.py` | `AppState` — всё, что нужно хендлеру, в `app.state.webscope` | ~120 |
| `deps.py` | лимиты запуска, создание прогона, поиск сайта/404 | ~180 |
| `routes/auth.py` | GET/POST `/auth/login`, POST `/auth/logout` | ~150 |
| `routes/pages.py` | страницы: `index_cards`, `index`, `sites_index`, `site_delete`, `site_settings` | ~300 |
| `routes/api.py` | `/api/sites*`, `/api/sites/{id}/report.*`, `/api/sites/{id}/scan` | ~400 |
| `routes/reports.py` | форматы отчёта (HTML/JSON/TXT/XML/SARIF), download, filenames | ~250 |
| `routes/uploads.py` | локальные сборки: лимиты, песочница, CSP sandbox | ~200 |
| `views.py` | данные страницы отчёта: группы, блокеры, дифф | ~400 |
| `storage.py` | SQLite: сайты, прогоны, находки, диффы, миграции, auth_vault | ~800 |
| `scheduler.py` | расписание, монитор, `reconcile_running` | ~300 |
| `alerts.py` | email (SMTP), Telegram, ухудшения старых проблем | ~350 |
| `storage_local.py` | `_LOCAL_DIR`, `_prune_local_uploads`, `_SandboxedLocalFiles` | ~150 |
| `urls.py` | разбор введённого адреса | ~80 |

**Тест структуры:** `tests/test_webapp_structure.py` падает, если в `app.py` появятся `@app.get` или он вырастет > 200 строк.

---

## 7. Безопасность — закрытые P0 (AUDIT.md §2, §10)

| Пункт | Файл | Суть |
|---|---|---|
| S1 Auth middleware | `auth.py:57`, `app.py:450` | HMAC cookie, `auth_configured()`, `is_public_path()` |
| S2 `/upload` | `app.py:785` | `resolve()` + `is_relative_to`, лимиты 300/10MB/50MB, ротация |
| S3 XSS `/__local` | `app.py:259` | CSP `sandbox allow-scripts`, `nosniff`, `no-store` |
| S4 SSRF | `scanner.py:146`, `netguard.py` | `getaddrinfo` на каждом хосте/редиректе, `context.route` |
| S5 CSRF/лимиты | `auth.py:88`, `app.py:397` | `Origin`/`Referer`, `RateLimiter`, `max_concurrent_scans=2` |
| S6 Пароли | `auth_vault.py`, `storage.py` | Fernet (`cryptography`), `WEBSCOPE_AUTH_KEY` |
| S7 TLS | `checks/links.py:146` | `verify=True` (умолчание), общий клиент, `HEAD→GET` на 403/405 |

> Детали правок: [SECURITY.md](SECURITY.md)

---

## 8. Метрики качества (AUDIT.md §4)

| Метрика | Значение | Цель |
|---|---|---|
| `ruff check` | ✅ зелёный | — |
| `ruff format` | ✅ зелёный | — |
| Тесты (not browser) | 254 passed | — |
| Тесты (browser) | 21 (требуют Chromium) | — |
| Покрытие `checks/*` | 12–30% | ≥ 70% |
| Покрытие `scanner` | 35% | ≥ 70% |
| Покрытие `mcp_server` | 0% | ≥ 50% |
| `test_security.py` | 4 теста (1 падает) | все зелёные |

---

## 9. Остаточные P1/P2 (из AUDIT.md §5, §19)

| # | Задача | Файлы | Приоритет |
|---|---|---|---|
| 7 | SARIF `partialFingerprints` | `report.py`, `models.py` | P1 |
| 10 | Скролл в `interaction` (B7) | `checks/interaction.py` | P1 |
| 11 | axe `target-size` вместо своей (B8) | `checks/viewport.py` | P1 |
| 12 | Шифрование `auth_password` (B6, S6) | `storage.py`, `pyproject.toml` | P1 |
| 18 | PDF-отчёты | `report.py`, `routes/reports.py` | P2 |
| 19 | Мультиарендность | `storage.py`, `routes/*`, `auth.py` | P2 |
| 20 | Postgres-адаптер | `storage.py`, `pyproject.toml` | P2 |

---

## 10. Связи с другими документами

- **[SECURITY.md](SECURITY.md)** — полный аудит + PoC + патчи
- **[ECONOMICS.md](ECONOMICS.md)** — почему per-site подписка, тарифы, unit economics
- **[ROADMAP.md](ROADMAP.md)** — Milestone 0–5 с критериями выхода
- **[DEVELOPMENT.md](DEVELOPMENT.md)** — запуск, тесты, CI, вклад
- **[BRANDING.md](BRANDING.md)** — CSS-переменные, токены, словарь формулировок
- **[PLAN.md](../PLAN.md)** — общий план проекта (источник для §§6–8, 12, 14)