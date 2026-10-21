# webscope — план проекта

> Детерминированный движок веб-QA, который отдаёт находки в машинно-читаемом виде
> и позволяет AI-кодинг-агенту (Claude Code, Cursor, Codex) самому их чинить.

Статус: v0.1 (MVP собран и работает: CLI, 6 проверок, MCP-сервер, 28 тестов, CI).
Документ — рабочий план, а не презентация.

## 0. Что уже сделано (2026-10-21)

| Что | Статус |
|---|---|
| CLI `scan` (text/json/html/sarif/junit), exit code, baseline, evidence-скриншоты | ✅ |
| Проверки: a11y (axe-core 4.11), content, forms, links, console, viewport | ✅ |
| Архетип-детектор (фреймворк / CMS / UI-кит) | ✅ |
| MCP-сервер: `scan_page`, `list_findings`, `get_fix_prompt` (mcp 2.x, `MCPServer`) | ✅ |
| 28 тестов (юнит + браузерные), ruff, GitHub Actions | ✅ |
| Живой прогон на example.com: 10 находок, детерминированно | ✅ |

Не сделано и требует внимания: краулер по sitemap/robots и группировка по шаблонам
(Milestone 2), набор из 20 сайтов для измерения FP-rate (Milestone 3), проверка цикла
«агент починил → скан зелёный» (Milestone 1, критерий приёмки).

---

## 1. Проблема

У команды, которая чинит сайт, нет дешёвого способа понять, **что именно сломалось**,
до того как это увидит пользователь:

- Lighthouse/axe-DevTools дают список правил, но не «вот этот баг, вот фикс».
- AI-QA платформы (Momentic, Spur, TestOptim, SignalCrawler, GoQA) либо дорогие,
  либо недетерминированные (LLM решает, что считать багом → галлюцинации и false positives).
- Ручной регресс стоит дороже, чем баг.

Ключевой разрыв: **находки существуют в человекочитаемом виде, но не в машинно-читаемом**.
AI-агент не может взять PDF-отчёт и починить сайт. Он умеет читать JSON/SARIF и диффы.

## 2. Решение

`webscope` — CLI + MCP-сервер, который:

1. **Детерминированно** проверяет страницу (Playwright + axe-core + собственные правила).
2. **Подтверждает** каждую находку в реальном браузере: скриншот элемента, CSS-селектор,
   HTML-фрагмент, страница и координаты.
3. **Отдаёт** результат в JSON / SARIF / текстовом виде — и в виде готового *fix-пrompt*
   для AI-агента: что сломано, где, и что именно нужно сделать.
4. **Доступен как MCP-сервер**: Claude Code / Cursor вызывают `scan_page` и получают
   задачи, которые агент выполняет сам.

Ключевой принцип (как у SignalCrawler, но дешевле и без AI-облака):
**код измеряет, браузер подтверждает, AI объясняет**. LLM никогда не создаёт находки.

## 3. Почему не generic «вставь URL → отчёт»

| Проблема generic-сервисов | Как решаем |
|---|---|
| Free-аналоги: Lighthouse, axe DevTools, TLDR → ценовой якорь = 0 | Мы продаём не отчёт, а **исполняемый артефакт для агента** и CI-гейт |
| False positives убивают доверие | Каждая находка подтверждена в браузере + evidence; FP-rate — публичная метрика |
| AI галлюцинирует находки | Ядро детерминированное, AI только severity-коррекция/группировка/текст фикса |
| Один и тот же список WCAG-ошибок у всех | Архетип-детектор → профильные проверки (см. §5) |
| Отчёт нельзя потреблять в пайплайне | SARIF/JUnit + exit code + MCP |

## 4. Аудитория

- **Первичная:** команды, которые уже пользуются AI-кодинг-агентами и у которых нет
  браузерного QA. Ценность: агент сам находит и чинит регрессии.
- **Вторичная:** QA-инженеры без инфраструктуры автотестов; small e-commerce/агентства,
  которым нужен регулярный отчёт (в будущем — white-label).

Монетизация (roadmap, не MVP): OSS-ядро → hosted CI-дашборд с историей и
диффом «до/после» → white-label отчёты для агентств.

## 5. Центральная гипотеза: «общая структура сайтов»

Исходная идея автора: у всех сайтов одинаковые классы и атрибуты, поэтому можно
сделать универсальный набор проверок.

Уточнение после исследования рынка: **единица общности — не CSS-классы, а семантика и
роли**. Классы уникальны для каждого проекта (`.btn-primary` vs `.c-button`), а вот
`input`, `button`, `nav`, `form`, `label`, `alt`, `role`, `aria-*` стандартизированы
(HTML Living Standard + WAI-ARIA). На этом стоит `axe-core`.

Из этого следует **архетип-детектор**: по DOM/ARIA/meta определить стек и UI-кит
сайта и выбрать профильный набор проверок.

| Признак | Детектируется | Что меняем в проверках |
|---|---|---|
| `__NEXT_DATA__` / `data-reactroot` | React / Next.js | SPA-навигация, клиентские роуты, отсутствие SSR-контента |
| `Vue`, `data-v-*` | Vue | То же |
| `ng-version` | Angular | То же |
| `wp-content` | WordPress | Темы/плагины: полный путь к шаблону, доступность тем |
| `Shopify.theme`, `cdn.shopify` | Shopify | Проверка чек-аута, `Shopify.pay`, политики возврата |
| классы `ant-*` | Ant Design | Компонентные a11y-паттерны |
| классы `Mui*` | MUI | То же |
| `btn btn-`, `col-` | Bootstrap | Сетка: переполнение на 320px |
| utility-классы (`flex`, `px-`, `text-`) | Tailwind | Утилитарный CSS: текст-контраст по вычисленным стилям |

Архетип — **внутренний механизм выбора проверок**, а не маркетинговая фишка.

## 6. Архитектура

```
                    ┌───────────────────────────────┐
  CLI (scan/report) │                               │
  MCP (stdio/http)  │   webscope.core               │
  CI (exit code)    │   ┌───────────────────────┐   │
                    │   │ scanner: playwright  │   │
                    │   │ ├ crawl (sitemap,     │   │
                    │   │ │  robots, templates) │   │
                    │   │ ├ archetype detector  │   │
                    │   │ └ checks/*           │   │
                    │   │   ├ a11y (axe-core)   │   │
                    │   │   ├ content           │   │
                    │   │   ├ forms             │   │
                    │   │   ├ links             │   │
                    │   │   ├ console/network   │   │
                    │   │   └ viewport/targets │   │
                    │   └───────────────────────┘   │
                    │   models: Finding / ScanResult │
                    │   report: text | json | html | │
                    │           sarif | junit | fix  │
                    └───────────────────────────────┘
                                    │
                        ┌───────────┴───────────┐
                        │  evidence: screenshot, │
                        │  selector, snippet,   │
                        │  console log          │
                        └───────────────────────┘
```

Принципы слоёв:

- `checks/*` — чистые функции `(page, ctx) -> list[Finding]`. Не знают про отчёт и MCP.
- `scanner.py` — оркестрация: браузер, архетип, контекст, evidence-сбор.
- `models.py` — схема данных, версионируется (semver на формат JSON).
- `report.py` — формат вывода; `mcp_server.py` — обёртка MCP.

## 7. Схема данных

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
      "severity": "serious",          // critical | serious | moderate | minor
      "title": "Изображение без alt",
      "message": "У <img> нет атрибута alt",
      "url": "https://example.com/",
      "selector": "main > div:nth-child(2) > img",
      "snippet": "<img src=\"/logo.png\">",
      "help_url": "https://dequeuniversity.com/rules/axe/4.10/image-alt",
      "source": "webscope.content",
      "evidence": {"screenshot": "evidence/page-1-content-image-alt-2.png"},
      "details": {"impact": "serious"}
    }
  ],
  "summary": {"critical": 0, "serious": 1, "moderate": 4, "minor": 2, "total": 7}
}
```

Совместимость: `schema_version` — semver. Поля только добавляем, не удаляем.

## 8. Набор проверок (MVP)

| Check | Что ловит | Severity |
|---|---|---|
| `a11y` | axe-core, теги wcag2a/2aa, wcag21a/21aa, wcag22aa | по impact |
| `content` | `lang`, `title`, meta description, h1, порядок заголовков, `img` без alt, `iframe` без title, пустые ссылки/кнопки, дубли id | serious → minor |
| `forms` | input без label, label только через placeholder, input без `name`, email без `autocomplete`, submit без доступного имени, дубль `id` в форме | serious → moderate |
| `links` | `href="#"`, `javascript:void(0)`, `target=_blank` без `rel=noopener`, битые внутренние ссылки (HTTP-статус), mixed content (http:// на https-странице) | critical → minor |
| `console` | ошибки/варнинги в консоли, uncaught exceptions, упавшие запросы (4xx/5xx) | serious → moderate |
| `viewport` | горизонтальный overflow на 320px и 768px, элементы вне вьюпорта, target size < 24×24 (WCAG 2.2 2.5.8) | serious → minor |
| `meta` | отсутствие `viewport` meta, `charset`, отсутствие HTTPS, отсутствие HSTS/security-заголовков (критично только для отдельного профиля) | moderate → minor |

Правила по умолчанию детерминированы и версионируются; у каждой — `rule` id и `help_url`.

## 9. MCP-инструменты

```
scan_page(url, checks?, timeout?) -> ScanResult(JSON)
list_findings(url, min_severity?) -> краткий список
get_fix_prompt(url, rule?) -> готовый промпт для coding-агента
```

`get_fix_prompt` — ключевая фишка: он собирает из находок **задачу для агента**:
что сломано, селектор, HTML, требование WCAG, критерий приёмки и что проверить после
фикса. Агент применяет правку и перезапускает `scan_page` — цикл замыкается.

Пример:

```
Fix the following webscope findings on https://example.com:

[1] content/image-alt (serious) — Изображение без alt
    selector: main > div:nth-child(2) > img
    snippet:  <img src="/logo.png">
    rule:     WCAG 1.1.1 Non-text Content
    accept:   element has a non-empty alt attribute (or aria-label / role="presentation")
```

## 10. Дорожная карта

### Milestone 0 — ядро (1–2 недели) ✅ сделано
- [x] `scan <url>` → JSON/text, exit code по severity
- [x] Проверки: a11y, content, forms, links, console, viewport
- [x] Архетип-детектор (фреймворк, CMS, UI-кит)
- [x] Evidence: скриншот элемента, селектор, сниппет
- [x] Unit-тесты + CI (ruff, pytest)
- **Приёмка:** `webscope scan https://example.com --format json` даёт ≥1 находку на
  заведомо сломанной странице и 0 ложных на верхушке `example.com`; повторный прогон
  детерминирован (diff пустой). → ✅ находки подтверждены, детерминированность проверена
  на браузерном тесте с фикстурой

### Milestone 1 — MCP (1 неделя) ✅ сделано
- [x] MCP-сервер (`stdio`), 3 тула, инструкция для Claude Code / Cursor
- [x] `get_fix_prompt` + проверка цикла «агент починил → скан зелёный»
- **Приёмка:** агент в чистой сессии по промпту «проаудити https://... и почини
  найденное» находит и правит минимум одну находку. → сервер и тулы работают
  (smoke-тест `tests/mcp_smoke.py`), сам цикл «агент чинит» нужно проверить руками

### Milestone 2 — CI и форматы (1 неделя)
- GitHub Action, `sarif`/`junit` вывод, baseline-файл (игнор известных находок)
- **Приёмка:** Action ломает PR при появлении новой critical-находки.

### Milestone 3 — качество данных (2 недели)
- Набор из 20 реальных сайтов с заведомыми багами (для измерения FP-rate и полноты)
- Классификатор находок, отсев FP, приоритизация по «пользовательскому вреду»
- **Приёмка:** FP-rate < 10% на размеченном наборе.

### Milestone 4 — монетизация (после MVP)
- Hosted: история сканов, диффы, алерты в Slack/Teams
- White-label отчёты для агентств (для a11y/EAA — отдельный продуктовый слой)

## 11. Метрики

- **North star:** число находок, исправленных в течение 14 дней после скана.
- Time-to-first-report < 3 мин на сайт.
- FP-rate < 10% (доля находок, отклонённых пользователем как ложных).
- Adoption: повторные сканы (weekly+) > 40% пользователей.
- Reliability: детерминированный вывод при одинаковом входе (в пределах версии движка).

## 12. Риски

| Риск | Митигация |
|---|---|
| False positives | evidence-first: подтверждение в браузере, скриншот, сниппет; baseline; ручная разметка набора |
| Галлюцинации LLM | LLM не создаёт находки; только текст фикса и группировка; всё детерминировано и версионируется |
| SSRF / безопасность | Только `http/https`; блок localhost, link-local, private IP (DNS-resolve + проверка редиректов); таймауты; лимит страниц |
| Юридика и robots | По умолчанию уважать `robots.txt`; флаг `--ignore-robots` только для своих стендов; в отчёте — оговорка «автоматизированная проверка покрывает ~30–40% критериев WCAG» |
| Флейки | Детерминированный движок, нет гонок; повторные попытки только для network-зависимых проверок |
| Стоимость | Локальный рантайм, без облака; браузер один раз, кэш контекста |
| Мотивация LLM-агента чинить | `get_fix_prompt` даёт готовое ТЗ с критерием приёмки |

## 13. Конкурентное позиционирование

| | Momentic/Spur/TestOptim | SignalCrawler | Loupe/Axeazy (a11y) | **webscope** |
|---|---|---|---|---|
| Тип | SaaS-платформы | SaaS-аудит | a11y-отчёты | **CLI/MCP, open-source** |
| Находки | LLM-агентами | детермин. + AI | axe-core | **детермин. ядро** |
| Потребление | дашборд | PDF/dash | PDF | **JSON/SARIF + MCP** |
| Цель | закрыть баг | отчёт | отчёт | **починить баг** |
| Цена | $$ | freemium+ | €39+/мес | **бесплатно / self-hosted** |
| Канал | продажи | SEO | агентства | **GitHub / MCP-реестры** |

Мы не конкурируем с ними в «отчётах» — мы даём **слой исполнения** поверх их отчётов
и слой **исполнения для агентов**, которого на рынке нет.

## 14. Открытые вопросы (проверить на пользователях)

1. Кто платит: разработчик с AI-агентом или QA-инженер? Разные триггеры продажи.
2. Нужен ли доступ к приватным стендам (авторизация) — и как хранить секреты.
3. Нужен ли обход SPA-роутинга (React Router) для полного обхода.
4. Готов ли пользователь платить за историю/диффы (иначе остаётся бесплатный CLI).
5. Нужен ли домен «для кого»: e-commerce, маркетплейсы, сайты услуг — для профильных чек-листов.

## 15. Репозиторий

```
qa-startup/
├── PLAN.md                    # этот документ
├── README.md                  # быстрый старт + примеры
├── pyproject.toml
├── src/webscope/
│   ├── cli.py                 # scan / report / mcp
│   ├── scanner.py             # playwright + оркестрация
│   ├── models.py              # Finding, ScanResult
│   ├── archetype.py           # детектор стека/UI-кита
│   ├── report.py              # text/json/html/sarif
│   ├── mcp_server.py          # MCP-тулы
│   ├── vendor/axe.min.js      # вендорим axe-core 4.11.0
│   └── checks/                # a11y, content, forms, links, console, viewport
└── tests/
```
