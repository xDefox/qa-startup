# webscope

Детерминированный движок веб-QA: обходит сайт, подтверждает каждую находку в
реальном браузере и отдаёт результат в машинно-читаемом виде — в том числе как готовое
ТЗ для AI-кодинг-агента.

```
webscope scan https://example.com --format json
webscope crawl https://example.com --history-dir .webscope
webscope scan https://example.com --fix-prompt > fix.md
claude mcp add webscope -- webscope mcp
```

## Идея

У всех сайтов общая структура: формы, кнопки, ссылки, заголовки, изображения — это
одни и те же семантические конструкции (`input`, `button`, `label`, `alt`, ARIA-роли).
На этом держится возможность написать универсальный набор проверок, который работает
на любом сайте без настройки.

Принцип работы: **код измеряет, браузер подтверждает, AI объясняет**.
LLM никогда не создаёт находки — он только объясняет уже подтверждённые.

Полный план проекта — в [PLAN.md](PLAN.md).

## Установка

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium   # либо используется системный Chromium
```

## Использование

### CLI

```bash
# текстовый отчёт
webscope scan https://example.com

# JSON для пайплайна
webscope scan https://example.com --format json --out report.json

# SARIF для GitHub Code Scanning
webscope scan https://example.com --format sarif --out results.sarif

# ТЗ для coding-агента
webscope scan https://example.com --fix-prompt

# только часть проверок, со скриншотами находок
webscope scan https://example.com --checks a11y,forms --evidence-dir evidence/

# CI: код возврата 1, если есть находки от serious и выше
webscope scan https://example.com --fail-on serious
```

### Обход сайта, история и сравнение

```bash
# обойти сайт и проверить по одной странице каждого шаблона (/catalog/1 и /catalog/2 — один шаблон)
webscope crawl https://example.com --max-pages 30 --depth 2

# тот же обход, но с сохранением снимка и сравнением с прошлым прогоном
webscope crawl https://example.com --history-dir .webscope

# отчёт для владельца сайта: без терминов, с оценкой и планом из 3 действий
webscope crawl https://example.com --format plain

# сравнить два снимка вручную
webscope diff .webscope/old.json .webscope/new.json

# динамика по прогону: оценка и количество проблем по дням
webscope history https://example.com --dir .webscope
```

История хранится рядом: `.webscope/<домен>/<метка>.json` + `latest.json`.
Формат снимка — тот же JSON, что у `scan --format json`, поэтому его можно
скармлить в свой пайплайн.

### Форматы отчётов

| Формат | Для чего |
|---|---|
| `text` | Технический отчёт для разработчика |
| `plain` | Отчёт для владельца сайта: оценка 0–100, «почему это важно», «что делать» |
| `json` | Для пайплайнов и агентов |
| `html` | Отчёт для отправки клиенту или вложения в письмо |
| `sarif` | GitHub Code Scanning |
| `junit` | JUnit XML для CI |

### MCP

```bash
webscope mcp
```

Инструменты:

| Инструмент | Назначение |
|---|---|
| `scan_page(url, checks, timeout_ms)` | Полный скан, результат в JSON |
| `list_findings(url, min_severity)` | Краткий список находок |
| `get_fix_prompt(url, rules)` | Готовое ТЗ для исправления находок |

Цикл работы агента: `scan_page` → `get_fix_prompt` → правка кода → `scan_page` повторно.

## Проверки

| Check | Что ловит |
|---|---|
| `a11y` | axe-core: WCAG 2.0/2.1/2.2 A/AA, best-practice |
| `content` | `lang`, `title`, description, viewport, заголовки, `alt`, `iframe`, пустые ссылки/кнопки, дубли `id` |
| `forms` | подписи полей, `name`, `autocomplete`, доступные имена кнопок |
| `links` | `href="#"`, `target=_blank` без `noopener`, mixed content, битые внутренние ссылки |
| `console` | ошибки и предупреждения консоли, упавшие запросы |
| `viewport` | горизонтальный overflow на 320/768px, размер целей касания < 24×24 |

## Безопасность

- Только `http/https`, без credentials в URL.
- SSRF-защита: приватные, loopback и link-local адреса блокируются
  (обход — `--allow-private` или `WEBSCOPE_ALLOW_PRIVATE=1`, только для своих стендов).
- Скриншоты и разметка попадают в локальный каталог `--evidence-dir`.
- Сканирование чужих сайтов — только те, на которые у вас есть право проверять; по
  умолчанию уважается `robots.txt` при кодировании собственного краулера.

## Лицензия

MIT
