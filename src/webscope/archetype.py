"""Определение архетипа сайта: фреймворк, CMS, UI-кит.

Зачем: общность сайтов не в CSS-классах (они уникальны для каждого проекта), а в
семантике и ролях. Но у сайтов на разных стеках *разные* типичные проблемы:
SPA без SSR-контента, темы WordPress, переполнение сетки Bootstrap, компонентные
паттерны MUI/Ant Design. Архетип позволяет включать профильные проверки и не шуметь.
"""

from __future__ import annotations

from typing import Any

# Признаки фреймворков: маркер в разметке/скриптах.
_FRAMEWORK_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("next", ("__NEXT_DATA__", "__next_f", "/_next/")),
    ("nuxt", ("__NUXT__", "/_nuxt/")),
    ("remix", ("__remixContext", "/build/")),
    ("angular", ("ng-version", "ng-app", "angular.min.js")),
    ("vue", ("data-v-", "__VUE__", "vue.runtime")),
    ("svelte", ("svelte-", "__sveltekit")),
    ("react", ("data-reactroot", "react-dom", "__REACT_DEVTOOLS")),
    ("astro", ("astro-island", "astro-root")),
)

# Признаки CMS: генератор и служебные пути.
_CMS_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("shopify", ("cdn.shopify.com", "shopify.theme", "ShopifyAnalytics")),
    ("wordpress", ("wp-content", "wp-includes", "wp-json")),
    ("wix", ("wix.com", "wixstatic")),
    ("webflow", ("webflow.js", "data-wf-page")),
    ("tilda", ("tilda", "tildastatic")),
    ("hubspot", ("hs-scripts", "hubspot")),
)

# Признаки UI-китов: характерные классы.
_UI_KIT_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ant-design", ("ant-btn", "ant-input", "ant-select", "ant-card")),
    ("mui", ("MuiButton", "MuiInputBase", "MuiTextField", "mui-", "makeStyles")),
    ("bootstrap", ("btn btn-", "col-md-", "col-lg-", "container-fluid", "navbar-expand")),
    ("tailwind", ("tailwindcss", "text-sm", "px-4", "flex items-center", "bg-gray-")),
    ("foundation", ("grid-x", "cell small-", "button-group")),
    ("bulma", ("navbar-item", "button is-primary", "columns")),
)

# Хинты на фреймворк из собранных глобальных переменных.
_FRAMEWORK_GLOBALS: tuple[tuple[str, str], ...] = (
    ("next", "__NEXT_DATA__"),
    ("nuxt", "__NUXT__"),
    ("react", "React"),
    ("vue", "Vue"),
    ("angular", "ng"),
)


def _contains_any(haystack: str, needles: tuple[str, ...]) -> bool:
    return any(needle in haystack for needle in needles)


def detect_archetype(
    html: str,
    script_srcs: list[str] | None = None,
    class_names: list[str] | None = None,
    meta_generator: str | None = None,
    globals_present: list[str] | None = None,
) -> dict[str, Any]:
    """Определяет стек сайта.

    Возвращает словарь с ключами ``framework``, ``cms``, ``ui_kit`` и ``signals``
    (список, по каким признакам сделан вывод) — чтобы отчёт был объяснимым.
    """
    html = html or ""
    script_srcs = script_srcs or []
    class_names = class_names or []
    globals_present = globals_present or []
    meta_generator = meta_generator or ""

    blob = " ".join([html, " ".join(script_srcs), " ".join(class_names), meta_generator]).lower()
    class_blob = " ".join(class_names).lower()

    signals: list[str] = []

    framework = _detect_first(_FRAMEWORK_MARKERS, blob, class_blob, signals, "framework")
    if framework is None:
        framework = _detect_from_globals(globals_present, signals)

    cms = _detect_first(_CMS_MARKERS, blob, class_blob, signals, "cms")
    ui_kit = _detect_first(_UI_KIT_MARKERS, blob, class_blob, signals, "ui_kit")

    return {
        "framework": framework,
        "cms": cms,
        "ui_kit": ui_kit,
        "signals": signals,
    }


def _detect_first(
    markers: tuple[tuple[str, tuple[str, ...]], ...],
    blob: str,
    class_blob: str,
    signals: list[str],
    kind: str,
) -> str | None:
    for name, needles in markers:
        for needle in needles:
            low = needle.lower()
            haystack = class_blob if kind == "ui_kit" and low in class_blob else blob
            if low in haystack:
                signals.append(f"{kind}:{name}")
                return name
    return None


def _detect_from_globals(globals_present: list[str], signals: list[str]) -> str | None:
    for name, marker in _FRAMEWORK_GLOBALS:
        if marker in globals_present:
            signals.append(f"framework:{name}")
            return name
    return None


def profile_notes(archetype: dict[str, Any]) -> list[str]:
    """Человекочитаемые пометки по архетипу — попадают в отчёт."""
    notes: list[str] = []
    framework = archetype.get("framework")
    cms = archetype.get("cms")
    ui_kit = archetype.get("ui_kit")

    if framework in {"next", "nuxt", "react", "vue", "angular", "svelte", "astro"}:
        notes.append("SPA/SSR-фреймворк: часть контента рендерится на клиенте — проверяем доступность после гидрации.")
    if cms:
        notes.append(f"CMS: {cms} — тема и плагины задают шаблон, проверяем по типам страниц.")
    if ui_kit:
        notes.append(f"UI-кит: {ui_kit} — типовые компоненты, типовые a11y-паттерны.")
    return notes
