# webscope —planned 工作流与路径

> Единый источник дорожной карты. Ссылки из PLAN.md §§9–14.
> Статус: v0.3.1 (AUDIT fixes closing P0 已完成), Milestone 4（billing）⏳.

---

## Milestone 0 — ядро ✅

**Статус:** CLI (`scan`/`crawl`/`diff`/`history`), 6 модулей проверок, archetype-детектор, evidence, тесты, CI green.

## Milestone 1 — MCP ✅

**Статус:** `mcp_server.py` (stdio, 3 тула), `test_mcp_smoke` (pytest mark `browser`).

## Milestone 2 — краулер ✅

**Статус:** robots.txt, sitemap.xml + sitemap index, обход по ссылкам, группировка по шаблонам.

## Milestone 3 — история и диффы ✅

**Статус:** снимки в JSON, диффы (новые/исправленные/изменённые), тренд, `--history-dir`. Schema JSON → SQLite migrations.

## Milestone 4 — MVP product (веб ✅ / billing ⏳)

| Jab | State | Status |
|---|---|---|
| Веб-интерфейс | URL → отчёт | ✅ |
| Планировщик | еженедельный/ежедневный | ✅ |
| История/диффы в БД | SQLite | ✅ |
| Алерты | email + Telegram | ✅ |
| Биллинг | Plan/Subscription/Invoice + migration | ⏳ |
| Stripe | subscribtion per-site | ⏳ |
| Live demo | varkacoffee.by · 123 findings · score 7/10 | ✅ PoC |

## Milestone 5 — проверка спроса (идёт параллельно, дешевле кода)

| Jab | Task | State |
|---|---|---|
| Landing page | «Проверьте сайт бесплатно» | ✅ веб-интерфейс работает как лендинг |
| Conversations | 10–15 разговоров с владельцами сайтов | ⏳ |
| Pilot criteria | ≥ 10 платящих, fixed_findings > 0 ≥ 60% | ⏳ |
| Pilot metrics | FP < 10%, retention, time-to-first-fix | ⏳ |
| Crawling dashboard | мониторинг лидов/заявок | ⏳ |

---

## Post-audit fixes (P1/P2 per AUDIT.md §5, §19)

| # | Task | Priority | Files |
|---|---|---|---|
| 7 | SARIF partialFingerprints | P1 | report.py, models.py |
| 8 | Interaction scroll | P1 | checks/interaction.py |
| 9 | axe target-size vs own check | P1 | checks/viewport.py |
| 10 | Encrypt auth passwords | P1 | storage.py, pyproject.toml |
| 11 | LICENSE file | P2 | repo root |
| 12 | PDF reports | P2 | report.py, routes/reports.py |
| 13 | Multi-tenant accounts | P2 | storage.py, routes/*, auth.py |
| 14 | Postgres adapter | P2 | storage.py, pyproject.toml |
| 15 | Dockerfile + compose | P2 | infra |
| 16 | pip-audit/bandit in CI | P2 | .github/workflows/ci.yml |
| 17 | Dependabot, py.typed, uv.lock | P2 | pyproject.toml |

---

## ECONOMICS Milestone

| Jab | Task | State |
|---|---|---|
| Pricing tiers: Free 5 находок; Starter $19 / Pro $59 / Business $199 | Approved 2026-11-04 | ✅ |
| Unit economics ARPU $19–25, CAC~$30, churn≤12%, LTV/CAC~5× | Approved 2026-11-04 | ✅ |
| Economic justification document (Russian) | ../ECONOMICS.md | ✅ |
| Economic audit (penalties, rooms) | economic-audit.md, economic-persona.md | ✅ |
| Demand validation (pilot criteria) | Milestone 5 PLAN | ⏳ |

---

## Main risks (revisited)

| Risk | Mitigation |
|---|---|
| FP > 10% | evidence-first + FP button in UI + dedupe axe |
| Churn after fix | portfolio + EAA requirement + weekly alerts habit |
| Competition (Lighthouse etc.) | deterministic + AI + archetype + FP metrics + continuous service |
| CAC > $80 | SEO-first, CMS partnerships (Tilda/Shopify), content marketing |
| Hosting cost per scan | 1 browser/scan, cache context, page/time limits |

---

## Links

- **ARCHITECTURE.md** — layers, checks, data schema, webapp structure
- **SECURITY.md** — fixed by AUDIT, open P1 items
- **ECONOMICS.md** — pricing justification, unit economics, persona
- **BRANDING.md** — CSS tokens, typography, severity scale
- **DEVELOPMENT.md** — run, tests, CI, contribution
- **PLAN.md** — master plan (source of original milestones)