# webscope — Документы (master index)

Все разрозненные документы сгруппированы в единую систему сxref-ссылками.
Каждый документ указан с аудиториями, статусом и ключевымиDecisionами.

---

## Структура docs/

| Запись | Аудитория | Статус | Документ | Книга |
|---|---|---|---|---|
| **[0] PRODUCT — 产品定义与问题** | Владелец сайта, агент, инвестор | ✔ готов | [PLAN.md](PLAN.md) §§1–5, 13 · [README.md](README.md) §§1–2 | — |
| **[1] ARCHITECTURE — 架构与设计决策** | Разработчик,gartner | ✔ готов | [PLAN.md](PLAN.md) §§6–8, 12 · [LECTURE.md](LECTURE.md) · [AUDIT.md](AUDIT.md) §§3–4 | — |
| **[2] SECURITY — 安全审计与修复** | Разработчик, безопасности | ✔ закрыты P0 | [SECURITY.md](SECURITY.md) · [PLAN_SECURITY.md](PLAN_SECURITY.md) | — |
| **[3] ECONOMICS — 经济模型与定价** | Владелец сайта, агент, инвестор | ✔ одобрено | [ECONOMICS.md](ECONOMICS.md) | — |
| **[4] BRANDING — 品牌与дизайн-система** |所有 front-end дизайн | ✔ готов | [BRANDING.md](BRANDING.md) | — |
| **[5] DEVELOPMENT — 开发流程与технические детали** | Разработчик | ✔ готов | [README.md](README.md) §§6–7, 10 · [PLAN.md](PLAN.md) §§9, 14 · [LECTURE.md](LECTURE.md) | — |
| **[6] ROADMAP — 规划与里程�ми** |все заинтересованные | ✔ готов | [ROADMAP.md](ROADMAP.md) · [ECONOMICS.md](ECONOMICS.md) §§4, 5 | — |
| **[7] PITCH — Pitch и презентационные материалы** | все演讲者 | ✔-|pitch/ | [pitch/](pitch/) | — |

---

## 1. Структура папок

### /docs/ (текущие документы)

| Подпапка | Содержимое |
|---|---|
| **/`** | INDEX.md, ARCHITECTURE.md, BRANDING.md, ECONOMICS.md, ROADMAP.md, SECURITY.md |
| **/legacy/** | ОLD-версии всех md-файлов (AUDIT.md, BRANDBOOK.md, economic-audit.md, economic-persona.md, LECTURE.md, PLAN_SECURITY.md, ECONOMIC_JUSTIFICATION_RU.md). Ссылки в INDEX.md не ведут сюда. |

### /docs/ARCHITECTURE.md → §6 PLAN.md (структура src/)
### /docs/ECONOMICS.md → §3 economics (Free 5 находок; Starter $19 / Pro $59 / Business $199)
### /docs/SECURITY.md → §2 аудит P0 (S1–S7 закрыты)
### /docs/ROADMAP.md → §9 дорожная карта (Milestone 0–5)
### /docs/BRANDING.md → BRANDBOOK.md (дизайн-токены)

---

## 2. Ключевые документы (исходные файлы в корне)

Эти файлы остаются в корне `qa-startup/` как **источник правды** (git-tracked):

| Файл | Раздел | Описание |
|---|---|---|
| **PLAN.md** | §§1–14 | Главный план проекта (дочерние ссылки → docs/) |
| **README.md** | §§1–10 | Быстрый старт, установка, CLI, веб, проверки |
| **AUDIT.md** | §1–19 | Полный аудит безопасности + P1/P2 остаточные |
| **LECTURE.md** | — | Snapshot P0–P1 (2026-10-30) |
| **BRANDBOOK.md** | — | Визуальный стиль (альтернатива docs/BRANDING.md) |
| **economic-audit.md** | §3 | Сильные/слабые стороны бизнес-модели |
| **economic-persona.md** | §1 | Детальный портрет покупателя |
| **ECONOMIC_JUSTIFICATION_RU.md** | §§1–5 | Подробное обоснование цены (каждая цифра) |
| **PLAN_SECURITY.md** | — | Дополнительные безопасность-замечания |

### Почему оставляются в корне?
- Они git-tracked и history-важны
- PLAN.md ссылается на них напрямую (§6, §9)
- Docs/ — это **документация для потребления**, а исходники — **для версионности**

---

## 3. Дочерние ссылки (из PLAN.md)

| PLAN.md § | Ссылка | Статус |
|---|---|---|
| §6 | **[ARCHITECTURE.md](ARCHITECTURE.md)** | ✅ — architecture layer doc |
| §7 | **[checks + MCP](ARCHITECTURE.md)** | ✅ — 7 check modules |
| §9 | **[ROADMAP.md](ROADMAP.md)** | ✅ — Milestone 0–5 |
| §14 | **[ARCHITECTURE.md](ARCHITECTURE.md)** (src/ структура) | ✅ — file tree |
| README.md §6 | **[ARCHITECTURE.md](ARCHITECTURE.md)** | ✅ — checks section |
| README.md §10 | **[DEVELOPMENT.md](DEVELOPMENT.md)** | — (если создадим) |

---

## 4. Текущая версия (v0.3.1)

| Версия | Дата | Статус |
|---|---|---|
| **v0.3.1** | 2026-10-29 | FP-фиксы 2.4–2.8, работает CLI/MCP/веб/хранилище/алерты/спиннер/брендбук |
| **AUDIT fix** | 2026-10-30 | S1–S7, B1–B5 — все закрыты, CI зеленый, 170 тестов (на тот момент) |
| **ECONOMICS (архив)** | 2026-11-02 | старые тарифы $12/59/149; заменены моделью «5 находок» 2026-11-04 |
| **Pitch/economics v2** | 2026-11-05 | 307 тестов; Free 5 находок, Starter $19 / Pro $59 / Business $199; дек 3 мин + Q&A 5 мин |
| **Docs clean** | 2026-11-03 | Корневая папка `qa-startup/` очищена от лишних файлов (перемещены в `docs/legacy/` и `scripts/`/`data/`) |

---

## 5. Связь с другими файлами

### Индекс → остальные docs/
- INDEX.md → ARCHITECTURE.md / BRANDING.md / ECONOMICS.md / ROADMAP.md / SECURITY.md (кроссы внутри каждой)
- INDEX.md → docs/legacy/ (archived copies, never deleted)

### Исходники → INDEX.md
- PLAN.md → §6, §9, §14 → ссылки на INDEX.md разделы
- README.md → §6, §10 → ссылки на INDEX.md разделы
- AUDIT.md → §2 → [SECURITY.md](SECURITY.md) (исправления)
- economic-* → → [ECONOMICS.md](ECONOMICS.md) (обоснование)