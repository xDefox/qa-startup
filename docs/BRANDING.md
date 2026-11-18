# webscope — брендбук и дизайн-система

> **Единственный источник визуальной правды.**
> Токены живут в `src/webscope/webapp/static/css/tokens.css`, компоненты — в
> `templates/_macros.html` и `static/css/components.css`. Меняете правило —
> меняете и этот файл.
>
> `docs/legacy/BRANDBOOK.md` **устарел и не является источником правды**.
> Он описывает прежнюю inline-архитектуру (`base.html` со стилями внутри)
> и старую палитру. Не используйте его значения.

---

## 1. Принципы

- **Функция важнее формы.** Интерфейс — инструмент, а не витрина.
- **Честность важнее маркетинга.** Не обещаем функций, которых нет; не
  показываем несуществующие интеграции и ключи API.
- **Доступность по умолчанию.** Контраст ≥ 4.5:1, интерактивные цели в
  интерфейсе ≥ 44×44 px (сканер проверяет цели от 24×24 px — WCAG 2.2 AA),
  видимый фокус, `prefers-reduced-motion` уважается.
- **Две темы — одна система.** Light/Dark на одних и тех же переменных,
  без дублирования правил.
- **Типографика системная.** Никаких веб-шрифтов: нет внешних запросов,
  FOUT и FOIT.
- **Ноль inline-кода.** CSP: `script-src 'self'; style-src 'self'`.
  Скрипты — только внешние файлы, стили — только CSS-файлы.

---

## 2. Файлы — где что лежит

```
src/webscope/webapp/
├── templates/
│   ├── base.html               # документ, <link> на CSS, подключение JS
│   ├── _layout.html            # brand(), app_header(), auth_header(), app_footer()
│   ├── _icons.html             # icon(name, size, class) — SVG-спрайт из макроса
│   ├── _macros.html            # библиотека компонентов (кнопки, карточки, отчёт…)
│   ├── index.html              # главная: лендинг и быстрая проверка адреса
│   ├── landing.html            # «Возможности»: проверки, прогон, отчёт, Watchdog
│   ├── site.html               # отчёт по сайту
│   ├── scan.html               # быстрая проверка по адресу
│   ├── oneshot.html            # разовая проверка
│   ├── auth.html               # вход
│   ├── dashboard.html          # кабинет: добавление сайта, сборки, список
│   ├── dashboard_organizations.html
│   ├── dashboard_integrations.html
│   ├── dashboard_settings.html
│   ├── settings.html           # настройки конкретного сайта
│   └── history.html            # история прогонов
└── static/
    ├── css/
    │   ├── tokens.css          # ТОЛЬКО переменные (цвет, spacing, радиусы, тени)
    │   ├── base.css            # reset, сетка, типографика, шапка/подвал, утилиты
    │   ├── components.css      # повторно используемые компоненты
    │   └── pages.css           # только лендинг, отчёт, auth, печать, адаптив
    └── js/
        ├── base.js             # тема, мобильное меню, window.showToast
        ├── dashboard.js        # кабинет: форма сайта, upload, auth-переключатель
        ├── oneshot.js          # сценарий разовой проверки
        ├── scan.js             # поллинг статуса скана
        ├── site.js             # отчёт: вкладки, меню скачивания, фильтры
        ├── settings.js         # настройки сайта
        └── dashboard_organizations.js
```

**Правила владения:**

| Слой | Можно | Нельзя |
|---|---|---|
| `tokens.css` | CSS-переменные | селекторы, правила |
| `base.css` | элементы, сетка, каркас | стили конкретной страницы |
| `components.css` | классы, используемые ≥ 2 страницами | одноразовая вёрстка |
| `pages.css` | лендинг, отчёт, auth, печать | новые «кнопки» и «карточки» |
| шаблон страницы | вызовы макросов, текст | `<style>`, `<script>` без `src`, `style="…"` |

---

## 3. Цветовые токены

Все цвета — только через `var(--…)`. Хардкод HEX в компонентах запрещён
(исключение — градиент логотипа `#7c5cff`, зафиксированный здесь).

### Light (по умолчанию)

| Токен | Значение | Назначение |
|---|---|---|
| `--bg` | `#f6f7fb` | фон страницы |
| `--bg-soft` | `#eef2f8` | вложенные блоки, `code`, hover secondary |
| `--card` | `#ffffff` | карточки, модалки, поля |
| `--card-soft` | `#fbfcfe` | мягкие карточки |
| `--ink` | `#131a2a` | основной текст |
| `--ink-soft` | `#26314a` | текст в `code`, чуть мягче |
| `--muted` | `#5d6b82` | вторичный текст, подписи |
| `--muted-strong` | `#475467` | muted на цветном фоне |
| `--line` | `#e2e7ef` | границы, разделители |
| `--line-strong` | `#cfd7e4` | hover-границы, активные контуры |
| `--accent` | `#2563eb` | primary, ссылки, фокус |
| `--accent-hover` | `#1d4ed8` | hover primary |
| `--accent-soft` | `#eaf0ff` | фон активных вкладок/бейджей |
| `--accent-ink` | `#1e40af` | текст на `--accent-soft` |
| `--accent-contrast` | `#ffffff` | текст на accent-кнопке |
| `--critical` | `#b42318` | critical, ошибки |
| `--critical-soft` | `#fee4e2` | фон critical-бейджа |
| `--serious` | `#d97706` | serious |
| `--serious-ink` | `#92400e` | текст serious-бейджа |
| `--serious-soft` | `#fef0c7` | фон serious-бейджа |
| `--moderate` | `#b54708` | moderate |
| `--moderate-soft` | `#fdf1e3` | фон moderate-бейджа |
| `--minor` | `#667085` | minor |
| `--minor-soft` | `#f2f4f7` | фон minor/external-бейджа |
| `--ok` | `#087443` | успех, оценка «отлично» |
| `--ok-soft` | `#dcfae6` | фон ok-бейджа |

### Dark (`[data-theme="dark"]`)

| Токен | Значение |
|---|---|
| `--bg` | `#0b1026` |
| `--bg-soft` | `#0e1530` |
| `--card` | `#111830` |
| `--card-soft` | `#141c36` |
| `--ink` | `#e8ecf5` |
| `--ink-soft` | `#d3d9e6` |
| `--muted` | `#9aa5bc` |
| `--muted-strong` | `#b3bdd0` |
| `--line` | `#232c45` |
| `--line-strong` | `#33405e` |
| `--accent` | `#6aa8ff` |
| `--accent-hover` | `#8bbcff` |
| `--accent-soft` | `#17284a` |
| `--accent-ink` | `#bfd6ff` |
| `--accent-contrast` | `#06101f` |
| `--critical` | `#f87171` |
| `--critical-soft` | `#3b1620` |
| `--serious` | `#fbbf24` |
| `--serious-ink` | `#fde68a` |
| `--serious-soft` | `#3a2a0c` |
| `--moderate` | `#fb923c` |
| `--moderate-soft` | `#3a2110` |
| `--minor` | `#9aa5bc` |
| `--minor-soft` | `#1c2439` |
| `--ok` | `#34d399` |
| `--ok-soft` | `#0f2e25` |

Тёмная тема включается тремя путями: `data-theme="dark"`,
`data-theme="light"` или системная настройка
`@media (prefers-color-scheme: dark)` (при отсутствии явного выбора).
Выбор хранится в `localStorage` под ключом `webscope-theme`.

> В dark mode `--serious` (amber) и `--moderate` (orange) **не должны
> совпадать** — это разные уровни серьёзности.

---

## 4. Severity-бейджи

Бейджи используют только семантические токены: светлый фон + тёмный текст,
в тёмной теме — приглушённый фон + светлый текст.

```css
.badge.critical { background: var(--critical-soft); color: var(--critical); }
.badge.serious  { background: var(--serious-soft);  color: var(--serious-ink); }
.badge.moderate { background: var(--moderate-soft); color: var(--moderate); }
.badge.minor    { background: var(--minor-soft);    color: var(--muted-strong); }
.badge.ok       { background: var(--ok-soft);       color: var(--ok); }
.badge.external { background: var(--minor-soft);    color: var(--muted); }
.badge.org      { background: var(--accent-soft);   color: var(--accent-ink); }
```

Дополнительно: `.badge--dot` — цветная точка перед текстом,
`.status-badge.ok/.active`, `.status-badge.error/.inactive`,
`.count-badge` — числовой счётчик.

**Смысл уровней:** critical блокирует действие клиента, serious мешает
дойти до цели, moderate ухудшает опыт, minor — косметика. Цвет несёт
смысл, а не украшает.

---

## 5. Типографика

| Элемент | Размер | Line-height | Weight | Tracking |
|---|---|---|---|---|
| База (`body`) | `16px` | `1.6` | `400` | — |
| `h1` | `clamp(2rem, 4.6vw, 3.25rem)` | `1.2` | `700` | `-0.035em` |
| `h2` | `clamp(1.5rem, 2.8vw, 2rem)` | `1.2` | `700` | `-0.025em` |
| `h3` | `clamp(1.125rem, 2vw, 1.3rem)` | `1.2` | `700` | `-0.015em` |
| `h4` | `1rem` | `1.2` | `700` | `-0.01em` |
| `.small` | `14px` | `1.55` | `400` | — |
| `.tiny` | `12.5px` | `1.5` | `400` | — |
| `code`, `pre` | `0.85em` / `13px` | `1.55` | `400` | — |

- Шрифт: `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
  "Helvetica Neue", Arial, sans-serif`.
- Моно: `ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas,
  "Liberation Mono", monospace`.
- Максимальная длина строки: `65ch` (`.text-body`).
- Заголовки используют `text-wrap: balance`.

---

## 6. Spacing (шаг 4 px)

| Токен | Значение | Применение |
|---|---|---|
| `--space-1` | `4px` | микро-отступы |
| `--space-2` | `8px` | gap мелких элементов |
| `--space-3` | `12px` | padding кнопок, отступы в карточках |
| `--space-4` | `16px` | стандартный gap |
| `--space-5` | `24px` | padding карточек |
| `--space-6` | `32px` | крупные секции |
| `--space-7` | `48px` | hero, пустые состояния |
| `--space-8` | `64px` | секции лендинга |
| `--space-9` | `80px` | низ страницы |
| `--space-10` | `96px` | максимальные отступы |

Контейнеры: `--container: 1120px`, `--container-narrow: 720px`,
`--container-wide: 1280px`. Высота шапки — `--header-h: 64px`.

---

## 7. Радиусы

| Токен | Значение | Где |
|---|---|---|
| `--radius-xs` | `6px` | `code`, мелкие плашки |
| `--radius-sm` | `8px` | кнопки `sm`, инпуты, nav-ссылки |
| `--radius-md` | `12px` | карточки внутренние, тосты, `pre` |
| `--radius-lg` | `16px` | кнопки `lg`, крупные блоки |
| `--radius-xl` | `22px` | модалки, крупные панели |
| `--radius-full` | `999px` | пиллы, иконки-кнопки |

---

## 8. Тени

| Токен | Значение (light) | Где |
|---|---|---|
| `--shadow-xs` | `0 1px 2px rgba(15,23,42,.04)` | верхний слой |
| `--shadow-sm` | `0 1px 2px …, 0 4px 12px -6px …(.10)` | hover карточек |
| `--shadow-md` | `0 2px 4px …, 0 12px 28px -12px …(.18)` | выпадашки, тултипы |
| `--shadow-lg` | `0 4px 8px …, 0 24px 56px -24px …(.28)` | карточки, модалки, toast |
| `--shadow-accent` | `0 8px 24px -12px rgba(37,99,235,.55)` | primary-кнопка, логотип |

В тёмной теме тени построены на чёрном с большей непрозрачностью —
см. `tokens.css`.

---

## 9. Движение

| Токен | Значение |
|---|---|
| `--dur-fast` | `120ms` — hover, микро-переходы |
| `--dur-base` | `160ms` — стандартные переходы |
| `--dur-slow` | `240ms` — дуга оценки, появление |
| `--ease` | `cubic-bezier(0.2, 0.8, 0.2, 1)` |

- Тема переключается с классом `.theme-transition` (260 ms).
- Спиннер: `0.8s linear infinite`; при `prefers-reduced-motion: reduce`
  анимация замедляется до `2.4s` (не отключается полностью — прогресс
  должен быть виден).
- `html { scroll-behavior: smooth }`; при reduced motion поведение
  остаётся нативным.

---

## 10. Зоны касания и фокус

| Элемент | Минимум |
|---|---|
| Кнопки/ссылки | `24×24px` (WCAG 2.2 AA) |
| Иконки-кнопки, переключатели вида | `44×44px` |
| Поля ввода | `min-height: 44px` |
| Чекбоксы | `18×18px` + кликабельная строка `.check-row` |

```css
:where(a, button, input, select, textarea, summary, [tabindex]):focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
```

Outline скрывается только для мыши через `:focus:not(:focus-visible)`.

---

## 11. Логотип

- Текст: `webscope`, нижний регистр, `19px / 700 / -0.025em`.
- Точка после названия — `--accent` (`.brand__dot`).
- Знак `.brand__mark`: `28×28px`, радиус `9px`, градиент
  `linear-gradient(145deg, var(--accent), #7c5cff)`, белая иконка `scan`
  `17×17px`, `--shadow-accent`.
- Ссылка ведёт на `/`, `aria-label="webscope — на главную"`.
- Не использовать заглавные буквы, другой вес, логотип без точки или без знака.

---

## 12. Иконки

- Библиотека — `templates/_icons.html`, вызов:
  `{% from "_icons.html" import icon %}{{ icon("check", 18) }}`.
- Стиль: outline, `stroke-width="1.8"`, `stroke-linecap="round"`,
  `stroke-linejoin="round"`, `fill="none"`, `currentColor`.
- Размеры: `17px` в логотипе, `18px` в кнопках и навигации, `19–20px`
  в шапке, `24px` в крупных действиях.
- SVG всегда `aria-hidden="true" focusable="false"`; смысл передаётся
  текстом или `aria-label` на кнопке.

---

## 13. Состояние загрузки

- Спиннер `.spinner` / `.scan-spinner`: `18×18px`, border `2px`,
  `border-top-color: var(--accent)`.
- `.scan-progress` — inline-плашка с текстом и бегущей полосой снизу;
  используется на экране скана.
- `.progress-bar` + `.progress-fill` — загрузка локальной сборки,
  высота `6px`, радиус `3px`.
- Кнопка в loading: `disabled`, текст меняется на «Проверяем…»,
  спиннер внутри кнопки.
- Прогресс всегда сопровождается текстом, а не только анимацией.

---

## 14. Toast / уведомления

- Контейнер `#toast-container`: `fixed`, `right: 20px`, `bottom: 20px`,
  `z-index: 100`, ширина до `360px`.
- Типы: `success` (ok), `warning` (serious), `error` (critical).
- API: `window.showToast(message, type)` из `base.js`.
- Авто-скрытие через `5s`, анимация `toast-in/out 180ms`.
- `role="alert"` для ошибок, `role="status"` для остальных.
- Flush-сообщения страниц — `.flash` / `.alert` с вариантами
  `success | error | warning | info`.

---

## 15. Библиотека компонентов (`_macros.html`)

Вызов: `{% from "_macros.html" import btn, card, page_header %}`.

### Действия и навигация
`btn`, `btn_primary`, `btn_secondary`, `btn_outline`, `btn_danger`,
`btn_lg`, `btn_sm`, `icon_btn`, `pill`, `pagination`, `section_divider`.

### Контент
`card`, `section`, `hero`, `quick_scan_form`, `page_header`,
`breadcrumbs`, `table`, `feature_grid`, `empty_state`, `loading_state`,
`error_state`, `alert`, `flash`.

### Формы
`field`, `input`, `textarea`, `select`, `checkbox`, `radio_group`,
`hidden_input`, `form_actions`, `csrf_input`, `method_override`.

### Отчёт
`report_mock`, `score_dial`, `score_chart`, `run_selector`,
`download_button` / `download_menu`, `view_toggle`, `findings_table`,
`findings_list`, `diff_card`, `blockers_card`, `scan_progress`.

### Кабинет
`dashboard_tabs`, `site_row`, `orgs_table`, `package_card`,
`packages_grid`, `plan_card`, `auth_fields` / `auth_block`,
`watchdog_section`, `steps_grid`, `problem_cards`.

### Каркас (`_layout.html`)
`brand`, `app_header(request)`, `auth_header()`, `app_footer()`.

**Не дублируйте разметку страницы.** Если блок встречается дважды —
он переезжает в макрос; если стиль встречается дважды — в
`components.css`.

---

## 16. Голос продукта (copy)

- Обращение — на «вы», без давления и восклицательных знаков.
- Заголовок говорит, **что делает продукт**: «Сайт открывается. Заявка — нет»,
  «Возможности».
- Подзаголовок объясняет **пользу**, а не технологию.
- Числа и сроки — только реальные. Не пишем «за 30 секунд», если скан
  идёт минуту.
- Не обещаем: AI-анализ, автоматические правки, API-ключи, интеграции,
  которых нет в коде.
- Статусы — по-русски и однозначно: `выключено`, `каждые 6 часов`,
  `вход на сайт включён`, а не `off` / `auth`.
- Ошибки: что случилось + что сделать. Без «Oops!» и «Что-то пошло не так»
  без продолжения.
- Кнопки — глагол + объект: «Проверить сайт», «Скачать отчёт»,
  «Сохранить настройки». Не «Отправить», не «ОК».
- Для запуска скана есть **одна формулировка — «Проверить сайт»**. Не
  плодим «Проверить бесплатно», «Проверить свой сайт», «Перепроверить»
  и «Запустить проверку».
- **Один главный CTA на страницу.** Если в герое уже есть форма или
  кнопка «Проверить сайт», шапка и финальный блок не повторяют её.
  Допустим один вторичный переход — например, «Посмотреть возможности».
- Не давим покупкой. Вместо «Купите пакет» — нейтральное «Разовая
  проверка» и описание того, что входит. Тарифы показываем как
  информацию, без кнопок «Купить».
- Не используем англицизмы там, где есть русский термин: «отчёт»,
  «проверка», «находки», «расписание».

---

## 17. Доступность — чек-лист

- [ ] Контраст текста ≥ 4.5:1, крупного — ≥ 3:1.
- [ ] Видимый `:focus-visible` на всех интерактивных элементах.
- [ ] `aria-label` на иконках-кнопках без текста.
- [ ] `prefers-reduced-motion` уважается.
- [ ] `color-scheme: light dark` в `tokens.css`.
- [ ] Таблицы: `<th scope="col">`, подписи к полям связаны.
- [ ] Ошибки форм — `aria-describedby` + `.field-error`.
- [ ] `lang="ru"` на `<html>`, skip-link на `#main`.
- [ ] Мобильная навигация закрывается по `Escape` и клику вне.
- [ ] Никаких `style="…"` и inline-скриптов (CSP).

---

## 18. Не делать

- ❌ Не хардкодить цвета, отступы, радиусы и тени вне `tokens.css`.
- ❌ Не добавлять веб-шрифты и внешние CDN.
- ❌ Не писать `<style>` и `<script>` без `src` в шаблонах.
- ❌ Не добавлять `style="…"` в разметку (в том числе для графиков).
- ❌ Не дублировать карточки/кнопки/таблицы по страницам.
- ❌ Не использовать `!important`, кроме утилит и `[hidden]`.
- ❌ Не убирать outline без `:focus-visible`-альтернативы.
- ❌ Не обещать функции, которых нет в коде.
- ❌ Не смешивать русский и английский в одном статусе.

---

## 19. Версионирование

| Версия | Дата | Изменения |
|---|---|---|
| 1.0 | 2026-11-09 | Инициальная версия по результатам аудита |
| 2.0 | 2026-11-17 | Переход на `tokens.css` + `base/components/pages`, библиотеку макросов, SVG-график вместо Chart.js, честные тексты; legacy-брендбук помечен устаревшим |
