# webscope — 品牌与设计系统 (BRANDBOOK)

> Единый источник правды по визуальному стилю. Всё здесь взято из `src/webscope/webapp/templates/base.html` — если правило меняется, правится и этот файл.
> Reference: BRANDBOOK.md → **[BRANDING.md](BRANDING.md)**

## Principle: Interface as tool, not display case

Scandiour: скромная светлая база, один синий акцент и строгая шкала серьёзности.
Цвет несёт смысл: красный — блокирует клик, оранжевый — мешает клиенту, серый — мелочь.

## Palette

### Light theme (`--bg`: `#f6f7f9`, `--card`: `#ffffff`)

| Variable | HEX | Usage |
|---|---|---|
| `--bg` | `#f6f7f9` | фон страницы |
| `--card` | `#ffffff` | Карточки, шапки, поля |
| `--ink` | `#1c2333` | Основной текст, h1 |
| `--muted` | `#5b6474` | Подписи, вторичный текст |
| `--line` | `#e4e7ec` | Границы |
| `--accent` | `#2563eb` | Ссылки, кнопки |
| `--accent-hover` | `#1d4ed8` | Наведение |
| `--ok` | `#087443` | Отлично |

### Dark theme (`--bg`: `#0b1026`, `--card`: `#101625`)
Тёмно-синий → больше контраста с акцентом `#4f9bff`.

## Severity scale (both themes)

| Severity | Light HEX | Dark HEX | Bg / Text |
|---|---|---|---|
| Critical | `#b42318` | `#f87171` | `#fee4e2` / `#b42318` |
| Serious | `#d97706` | `#f59e0b` | `#fef0c7` / `#92400e` |
| Moderate | `#b54708` | `#f59e0b` | `#fdf1e3` / `#9a3412` |
| Minor | `#667085` | `#9aa2b4` | `#f2f4f7` / `#475467` |
| Success | `--ok` | `--ok` | `#dcfae6` / `#087443` |

Fonts: system stack (no web fonts):
```
-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
"Helvetica Neue", Arial, sans-serif
```
Monospace: system `monospace`.

Typographic scale:
| Element | Size | Weight |
|---|---|---|
| Score | 46px | 700 |
| h1 (page title) | 30px | 700 |
| h2 (card title) | 21px | 700 |
| Logo | 19px | 700 |
| Small text | 14px | 400 |
| Bullgidgets | 13px | 700 |
| `.where`, `th`, `code` | 12.5–13px | 400/700 |

Letter-spacing compression: larger text → tighter negative spacing (`-0.03em` → `-0.01em`).

## Code & radii

Radii encode hierarchy: larger → more rounded:
```
card: 14px, .step: 12px, buttons/fields: 10px, code: 5px, pills: 8px
```

Padding unit: 4px (typical: 8 / 12 / 14 / 16 / 18 / 22 / 24 / 28).

## Shadows
Card: double shadow — thin outline + deep blur:
```css
box-shadow: 0 1px 1px rgba(15, 23, 42, 0.01), 0 10px 30px -20px rgba(15, 23, 42, 0.8);
```

## Motion (respect prefers-reduced-motion)

| Effect | Duration | Timing |
|---|---|---|
| Button hover bg | 120ms | ease-in-out |
| Color/line change | 160ms | ease |
| Theme switch | 240ms | ease |
| Theme icon rotation | 320ms | ease |
| Spinning spinner | 800ms | linear, infinite |
| Progress bar | 1400ms | ease-in-out, infinite |

## Scan progress (.scan-progress)
Spinner + aria-live="polite" for screen readers; reduced motion: halved durations.

## Layout
```css
main { max-width: 940px; padding: 28px 20px 60px; }
.top { padding: 14px 24px; }
.row { flex gap: 12px; flex-wrap; }
.site-row { columns: URL + meta; score + arrow right }
```

## Contrast
- Minimum text contrast: **5.2:1** (WCAG AA requires 4.5:1).
- Visible focus: `outline: 2px solid var(--accent)` + `outline-offset: 2px`.
- `theme-color` in `<head>` adapts browser toolbar.
- Bullgidgets: light bg + dark text (both themes), to avoid contrast collapse.

## Dictionary (write for owner, not developer)

| Don't write | Write instead |
|---|---|
| «Ошибка» | «проблема» / «находка» |
| «Критический баг» | «блокирует клики» |
| «Контрастность» | «текст сливается с фоном» |
| «Доступное имя» | «подпись для скринридера» |
| 404 / timeout | «страница не найдена», «сайт не ответил вовремя» |
