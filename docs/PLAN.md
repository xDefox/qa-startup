# webscope — Project Plan

> Детерминированный движок веб-QA: находит проблемы на сайте, объясняет их языком владельца и отдаёт в машинно-читаемом виде для AI-агента.

**Статус:** 2026-11-05. Работает: CLI (scan/crawl/diff/history), MCP-сервер, веб-интерфейс, краулер, тесты, CI.

---

## 0. Что уже сделано

| Что | Статус |
|---|---|
| CLI scan/crawl/diff/history/MCP/serve | ✅ |
| 7 модулей проверок: a11y(axe-core 4.11), content, forms, interaction, links, console/network, viewport/targets | ✅ |
| Проверка дублей title/description по шаблонам краулера | ✅ |
| Диагностика ошибок запуска: домен/https/таймаут/статус вместо общей «недоступен» | ✅ |
| Тест детерминизма повторного скана = бинарные находки | ✅ |
| Архетип-детектор (stack/UI-kit) | ✅ |
| Краулер: robots.txt, sitemap.xml, обход по ссылкам, группировка по шаблонам | ✅ |
| Снимки, диффы, тренд, --history-dir | ✅ |
| Оценка «здоровья» 0–100 + перевод находок на язык владельца | ✅ |
| MCP-сервер scan_page/list_findings/get_fix_prompt (mcp 2.x) | ✅ |
| Веб-интерфейс: форма → отчёт, история, расписание, загрузка локальных файлов, кабинет управления | ✅ |
| Хранилище SQLite (sites, runs, findings, diffs, миграции) | ✅ |
| Алерты email+Telegram при ухудшении старых проблем | ✅ |
| Спиннер «Идёт проверка», JS-перехват submit без перезагрузки | ✅ |
| Брендбук BRANDBOOK.md палитра тем, шкала серьёзности, типографика, движение | ✅ |
| 307 тестов (юнит+браузерные+веб), ruff, GitHub Actions | ✅ |

---

## 1. Milestones

| № | Мильштейн | Статус |
|---|---|---|
| **M0 — ядро** ✅ | CLI, 6 проверок, архетип, evidence, тесты, CI | ✅ |
| **M1 — MCP** ✅ | `mcp_server.py` (stdio, 3 тула), `test_mcp_smoke` | ✅ |
| **M2 — краулер** ✅ | robots.txt, sitemap.xml + index, обход по ссылкам, группировка по шаблону | ✅ |
| **M3 — история и диффы** ✅ | снимки JSON, диффы, тренд, --history-dir | ✅ |
| **M4 — массовый продукт: MVP** | веб-интерфейс ✅ / биллинг ⏳ | 1️⃣ Веб ✅, 2️⃣ Биллинг ⏳, 3️⃣ Email/Telegram ⚠️, 4️⃣ Watchdog ⚠️ | ⏳ |
| **M5 — проверка спроса** (параллельно, дешевле кода) | Лендинг ✅, разговоры с владельцами, пилоты, тарифы | ⏳ | |

---

## 2. Current status v0.3.1 (2026-10-29)

- Audit fixes S1–S7 closed, CI green, 170 тестов (на тот момент).
- Free tier — 5 находок.
- Watchdog Starter $19.
- Unit Economics ARPU $26, CAC $30, LTV/CAC 7.5×, Payback 1.3 мес.
- Baseline scan: 2.7 с, оценка 84/100.

---

## 3. Tasks — SPRINT 1 (Blockers 0–3 days, DONE)

| # | Задача | Результат |
|---|---|
| 1 | **CSP Header (report-only → enforce)** | ✅ DONE |
| 2 | **Inline styles/scripts → .css/.js** | ✅ DONE |
| 3 | **CTA в Hero на `/`** | ✅ DONE |
| 4 | **Watchdog CTA/Onboarding Settings** | ✅ DONE |
| 5 | **Watchdog CTA Landing** | ✅ DONE |

---

## 4. Sprint 2 (Short-term, 1–2 недели)

| # | Задача | Статус |
|---|---|
| 6 | **Pay-per-scan Billing (Stripe/ЮKassa)** | ✅ DONE |
| 7 | **Email/Telegram уведомления Watchdog** | ✅ DONE |
| 8 | **E2E тесты Playwright** | 🔄 IN PROGRESS |
| 9 | **Load Testing k6** | ⏳ PENDING |

---

## 5. Next actions (P1/P2)

- SARIF partialFingerprints — P1
- Interaction scroll — B7 — требует браузерных тестов
- axe target-size вместо собственной проверки — B8 — требует FP подтверждения
- Шифрование auth_password через auth_vault — P1
- Python-multipart/python-memory: добавить в dependencies — P0
- LICENSE file — P2
- PDF reports — P2
- Multi-tenant accounts — P2
- Docker/infra — P2
- Pre-commit/CI gates — P2

---

## 6. Risks & mitigations

| Риск | Митигация |
|---|---|
| False positives | evidence-first, FP verification, dedupe axe |
| Churn after fix | портфель агентств, регулярная обязанность, weekly-алерты |
| Competition (Lighthouse etc.) | детерминизм + диффы + готовое ТЗ |
| CAC > $80 | SEO-first, CMS partnerships, контент-маркетинг |
| Abuse Free tier | 5 находок лимита, email/device fingerprint/Stripe |
| Hosting Playwright | 1 браузер/прогон, лимит страниц и времени |

---

*Документ обновляется по ходу реализации.*
