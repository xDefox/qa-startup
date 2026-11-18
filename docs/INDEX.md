# webscope — Документы (master index)

All scattered documents grouped in one system with cross-references.
Each document listed with audience, status and key decisions.

---

## 1. Структура папок

### /docs/ (current documents)

| Subfolder | Contents |
|---|---|
| **/** | INDEX.md, ARCHITECTURE.md, AUDIT.md, BRANDING.md, ECONOMICS.md, PLAN.md, ROADMAP.md, SECURITY.md |
| **/legacy/** | OLD versions of all md files (archived) |

### /docs/ARCHITECTURE.md → §6 PLAN.md (structure src/)
### /docs/ECONOMICS.md → §3 economics (v2.1 Watchdog)
### /docs/SECURITY.md → §2 audit P0 (S1–S7 closed)
### /docs/ROADMAP.md → §9 roadmap (Milestones 0–5)
### /docs/BRANDING.md → design system (tokens, components, copy)

---

## 2. Ключевые документы (источники правды)

| File | Section | Description |
|---|---|---|
| **PLAN.md** | §§1–14 | Main project plan (sublinks → docs/) |
| **README.md** | §§1–10 | Quick start, install, CLI, web, checks |
| **AUDIT.md** | §1–19 | Full security audit + P1/P2 fixes |
| **BRANDING.md** | — | Design system (tokens, typography, severity scale) |
| **ECONOMICS.md** | — | Pricing, unit economics, persona, risks |

### /docs/legacy/ (archived, never deleted)
| File | Description |
|---|---|
| AUDIT.md | Old audit (2026-10-30) |
| BRANDBOOK.md | Old brandbook |
| economic-audit.md | Business model analysis |
| ECONOMIC_JUSTIFICATION_RU.md | Detailed price justification (RU) |
| economic-persona.md | Persona portrait |
| LECTURE.md | Snapshot P0–P1 (2026-10-30) |
| PLAN_SECURITY.md | Security fixes plan |

---

## 3. Дочерние ссылки (из PLAN.md)

| PLAN.md § | Link | Status |
|---|---|---|
| §6 | **[ARCHITECTURE.md](ARCHITECTURE.md)** | ✅ architecture layer doc |
| §7 | **[checks + MCP](ARCHITECTURE.md)** | ✅ 7 check modules |
| §9 | **[ROADMAP.md](ROADMAP.md)** | ✅ Milestone 0–5 |
| §14 | **[ARCHITECTURE.md](ARCHITECTURE.md)** (src/ structure) | ✅ file tree |
| README.md §6 | **[ARCHITECTURE.md](ARCHITECTURE.md)** | ✅ checks section |
| README.md §10 | **[DEVELOPMENT.md](DEVELOPMENT.md)** | — (if created) |

---

## 4. Текущая версия (v0.3.1)

| Version | Date | Status |
|---|---|---|
| **v0.3.1** | 2026-10-29 | FP fixes 2.4–2.8, works CLI/MCP/web/store/alerts/spinner/brandbook |
| **AUDIT fix** | 2026-10-30 | S1–S7, B1–B5 — all closed, CI green, 170 tests (at that time) |
| **ECONOMICS v2.1** | 2026-11-04 | old tariffs $12/59/149; replaced by "5 findings" model (2026-11-04) |
| **ECONOMICS v2.2** | 2026-11-12 | hybrid: subscriptions + pay-per-scan packages ($29/10, $99/50, $179/100) |
| **Pitch/economics v2** | 2026-11-05 | 307 tests; Free 5 findings, Starter $19 / Pro $59 / Business $199; Dec 3 min + Q&A 5 min |
| **Docs clean** | 2026-11-11 | Root qa-startup/ cleaned of extra files (moved to docs/legacy/, scripts/, data/) |

---

## 5. Связь с другими файлами

### Индекс → остальные docs/
- INDEX.md → ARCHITECTURE.md / ECONOMICS.md / ROADMAP.md / SECURITY.md / BRANDING.md / AUDIT.md (cross inside each)
- INDEX.md → docs/legacy/ (archived copies, never deleted)

### Исходники → INDEX.md
- PLAN.md §6, §9, §14 → ссылки на INDEX.md разделы
- README.md §6, §10 → ссылки на INDEX.md разделы
- AUDIT.md §2 → [SECURITY.md](SECURITY.md) (fixes)
- economic-* → [ECONOMICS.md](ECONOMICS.md) (justification)