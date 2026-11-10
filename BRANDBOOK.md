# BRANDBOOK — webscope

> Единый источник визуальной правды для продукта. Все токены — CSS-переменные в `src/webscope/webapp/templates/base.html`.

---

## 1. Принципы

- **Функция важнее формы.** Интерфейс — это инструмент, не украшение.
- **Доступность по умолчанию.** Контраст ≥4.5:1, таргеты ≥44×44px, фокус видимый, `prefers-reduced-motion` уважается.
- **Две темы — одна система.** Light/Dark через CSS-переменные, без дублирования правил.
- **Типографика — системная.** Никаких веб-шрифтов, нет FOUT/FOIT.

---

## 2. Цветовые токены

### Light (default)

| Токен | Значение | Назначение |
|---|---|---|
| `--bg` | `#f6f7f9` | Фон страницы |
| `--card` | `#ffffff` | Карточки, модалки, панели |
| `--ink` | `#1c2333` | Основной текст |
| `--muted` | `#475467` | Вторичный текст, плейсхолдеры (WCAG AA ≥4.5:1 на `--bg`) |
| `--line` | `#e4e7ec` | Разделители, границы инпутов |
| `--accent` | `#2563eb` | Primary действия, ссылки, фокус |
| `--accent-hover` | `#1d4ed8` | Hover primary |
| `--critical` | `#b42318` | Critical severity, ошибки |
| `--serious` | `#d97706` | Serious severity |
| `--serious-ink` | `#92400e` | Текст на serious-бейдже |
| `--moderate` | `#b54708` | Moderate severity |
| `--minor` | `#667085` | Minor severity |
| `--ok` | `#087443` | Success, OK |

### Dark (`[data-theme="dark"]`)

| Токен | Значение | Назначение |
|---|---|---|
| `--bg` | `#0b1026` | Фон страницы |
| `--card` | `#101625` | Карточки, модалки |
| `--ink` | `#e6e8ee` | Основной текст |
| `--muted` | `#9aa2b4` | Вторичный текст |
| `--line` | `#232a3d` | Разделители |
| `--accent` | `#4f9bff` | Primary действия |
| `--accent-hover` | `#6aa8ff` | Hover primary |
| `--critical` | `#f87171` | Critical severity |
| `--serious` | `#fbbf24` | Serious severity (amber-400) |
| `--serious-ink` | `#92400e` | Текст на serious-бейдже |
| `--moderate` | `#fb923c` | Moderate severity (orange-400) |
| `--minor` | `#9aa2b4` | Minor severity |
| `--ok` | `#22c55e` | Success, OK |

> ⚠️ В dark mode `--serious` и `--moderate` **не должны совпадать**. Используются разные оттенки amber/orange.

---

## 3. Бейджи severity

### Light — светлый фон, тёмный текст

```css
.badge.critical { background: #fee4e2; color: #b42318; }
.badge.serious  { background: #fef0c7; color: #92400e; }
.badge.moderate { background: #fdf1e3; color: #9a3412; }
.badge.minor    { background: #f2f4f7; color: #475467; }
.badge.ok       { background: #dcfae6; color: #087443; }
.badge.external { background: #eef2f6; color: #475467; }
```

### Dark — тёмный фон, светлый текст (инвертированные)

```css
:root[data-theme="dark"] .badge.critical { background: #7f1d1d; color: #fecaca; }
:root[data-theme="dark"] .badge.serious  { background: #78350f; color: #fde68a; }
:root[data-theme="dark"] .badge.moderate { background: #7c2d12; color: #fed7aa; }
:root[data-theme="dark"] .badge.minor    { background: #374151; color: #d1d5db; }
:root[data-theme="dark"] .badge.ok       { background: #14532d; color: #86efac; }
:root[data-theme="dark"] .badge.external { background: #374151; color: #d1d5db; }
```

---

## 4. Типографика

| Элемент | Размер | Line-height | Weight |
|---|---|---|---|
| Базовый текст | `16px` | `1.6` | `400` |
| `h1` | `clamp(1.75rem, 4vw, 2.25rem)` | `1.25` | `700` |
| `h2` | `clamp(1.375rem, 3vw, 1.625rem)` | `1.3` | `600` |
| `h3` | `clamp(1.25rem, 2vw, 1.375rem)` | `1.4` | `600` |
| `small` / `.small` | `14px` | `1.5` | `400` |
| Код / селекторы | `12.5px` | `1.5` | `400` |

**Макс. длина строки:** `65ch` для текстовых блоков (класс `.text-body`).

**Шрифт-стек:** системный (san Francisco / Segoe UI / Roboto / Helvetica / Arial).

---

## 5. Spacing система (базовый шаг 4px)

| Токен | Значение | Применение |
|---|---|---|
| `--space-1` | `4px` | Микро-отступы внутри компонентов |
| `--space-2` | `8px` | Gap между мелкими элементами |
| `--space-3` | `12px` | Отступы в карточках, padding кнопок |
| `--space-4` | `16px` | Стандартный gap, padding секций |
| `--space-5` | `24px` | Padding карточек, margin между блоками |
| `--space-6` | `32px` | Крупные отступы между секциями |
| `--space-7` | `48px` | Hero-секции, лендинги |
| `--space-8` | `64px` | Максимальные отступы |

> В текущем CSS используются абсолютные значения. При рефакторинге заменить на `var(--space-N)`.

---

## 6. Радиусы

| Токен | Значение |
|---|---|
| `--radius-sm` | `6px` (инпуты, бейджи) |
| `--radius-md` | `10px` (кнопки, карточки внутренние) |
| `--radius-lg` | `14px` (карточки, модалки) |
| `--radius-xl` | `12px` (крупные кнопки `btn-lg`) |
| `--radius-full` | `999px` (пиллы, иконки-кнопки) |

---

## 7. Тени

| Уровень | Значение | Где используется |
|---|---|---|
| `--shadow-xs` | `0 1px 1px rgba(15,23,42,0.01)` | Карточки (верхний слой) |
| `--shadow-sm` | `0 1px 2px rgba(15,23,42,0.04)` | Ховер карточек |
| `--shadow-md` | `0 4px 12px -4px rgba(15,23,42,0.1)` | Выпадашки, тултипы |
| `--shadow-lg` | `0 10px 30px -20px rgba(15,23,42,0.06)` | Карточки (основная) |
| `--shadow-xl` | `0 22px 60px -24px rgba(15,23,42,0.55)` | Модалки, попапы |

---

## 8. Анимации и motion

- **Длительность:** `120ms` (микро), `160ms` (стандарт), `200ms` (макро), `320ms` (тема).
- **Easing:** `ease-out` для входа, `ease-in` для выхода, `ease-in-out` для сложных.
- **Reduced motion:** `@media (prefers-reduced-motion: reduce)` — анимации отключены или длительность ×3.

---

## 9. Зоны касания (Touch targets)

| Элемент | Минимум | Рекомендуется |
|---|---|---|
| Кнопки, ссылки | `24×24px` (WCAG 2.2 AA) | `44×44px` (iOS HIG / Material) |
| Иконки-кнопки (theme, view-toggle) | — | `44×44px` |
| Чекбоксы, радиокнопки | `24×24px` | `28×28px` |

> Все интерактивные элементы в коде имеют `min-height: 44px; min-width: 44px` для иконок-кнопок.

---

## 10. Состояния фокуса

```css
*:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
*:focus:not(:focus-visible) { outline: none; }
```

Никаких `:focus` без `:focus-visible` — скрываем outline для мыши, показываем для клавиатуры.

---

## 11. Логотип

- **Текст:** `webscope` (нижний регистр).
- **Акцент:** точка после названия в цвет `--accent` (`webscope<span>.</span>`).
- **Размер в шапке:** `19px / 700 / -0.02em`.
- **Не использовать:** заглавные буквы, другой вес, без точки.

---

## 12. Иконки

- **Стиль:** outline, stroke `1.5–2px`, `stroke-linecap="round"`, `stroke-linejoin="round"`.
- **Размер:** `18×18px` (в кнопках), `24×24px` (в навигации), `40–48px` (иллюстративные).
- **Цвет:** `currentColor` (наследует от текста).

---

## 13. Состояния загрузки

- **Спиннер:** `18×18px`, border `2px`, `border-top-color: var(--accent)`, `animation: spin 0.8s linear infinite`.
- **Кнопка в loading:** `disabled`, текст → «Проверяем…», спиннер внутри кнопки (не отдельным блоком).
- **Прогресс-бар:** `height: 6px`, `border-radius: 3px`, fill `var(--accent)`.

---

## 14. Toast / уведомления

- Позиция: `fixed bottom: 20px right: 20px`, `z-index: 100`.
- Типы: `warning` (amber), `error` (critical), `success` (ok).
- Авто-скрытие: `5s`, анимация `slide-in/out 180ms`.

---

## 15. Доступность (a11y) чек-лист

- [ ] Контраст текста ≥4.5:1 (normal), ≥3:1 (large).
- [ ] Фокус видимый на всех интерактивных элементах.
- [ ] ARIA-labels на иконках-кнопках без текста.
- [ ] `prefers-reduced-motion` уважается.
- [ ] `color-scheme: light dark` в `:root`.
- [ ] Таблицы имеют `<th scope="col">`.
- [ ] Ошибки форм связаны через `aria-describedby`.
- [ ] Язык страницы `lang="ru"`.

---

## 16. Не делать

- ❌ Не использовать произвольные цвета вне токенов.
- ❌ Не добавлять веб-шрифты без одобрения.
- ❌ Не делать тени тяжелее `--shadow-lg` без нужды.
- ❌ Не смешивать `rem` и `px` в одном правиле (кроме `border-radius`).
- ❌ Не использовать `!important` кроме утилит Reduced Motion.
- ❌ Не делать `outline: none` без `:focus-visible` fallback.

---

## 17. Файловая структура стилей

```
src/webscope/webapp/templates/
├── base.html          # Все CSS-токены + базовые стили (inline)
├── index.html         # Главная (лендинг + форма сканирования)
├── landing.html       # Публичный лендинг (свои стили в блоке {% block scripts %})
├── site.html          # Отчёт по сайту
├── oneshot.html       # Разовая проверка
├── dashboard.html     # Кабинет пользователя
├── settings.html      # Настройки сайта
├── history.html       # История прогонов
└── auth.html          # Вход
```

> В будущем: вынести базовые стили в `/static/css/base.css`, подключать через `<link>`, оставить в `base.html` только CSS-переменные и критические inline-стили для first paint.

---

## 18. Версионирование

| Версия | Дата | Изменения |
|---|---|---|
| 1.0 | 2026-11-09 | Инициальная версия по результатам аудита |