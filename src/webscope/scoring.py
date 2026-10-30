"""Оценка «здоровья» сайта и перевод технических находок на язык владельца сайта.

Для массового продукта важен не rule id, а ответ на два вопроса:
«что это значит для моего бизнеса» и «что мне сделать».
"""

from __future__ import annotations

from collections import defaultdict

from .models import Finding, Severity

# Вес находки по серьёзности для итогового балла.
_WEIGHTS = {
    Severity.CRITICAL: 15,
    Severity.SERIOUS: 8,
    Severity.MODERATE: 3,
    Severity.MINOR: 1,
}


# Сколько страниц затронуто правилом — показывается отдельно от балла.
def affected_pages(findings: list[Finding]) -> dict[str, int]:
    """Сколько раз каждое правило встречается (для показа «затронуто N страниц»)."""
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.rule] = counts.get(finding.rule, 0) + 1
    return counts


def group_by_rule(findings: list[Finding]) -> list[dict]:
    """Агрегирует находки по правилу: одна строка вместо горы дублей."""
    if not findings:
        return []

    groups: dict[str, list[Finding]] = defaultdict(list)
    for finding in findings:
        groups[finding.rule].append(finding)

    result = []
    for rule, items in groups.items():
        worst = min(items, key=lambda f: f.severity.rank)
        pages = sorted({item.url for item in items if item.url})
        selectors = [item.selector for item in items if item.selector]
        # Берём представителя с селектором/фрагментом если есть
        rep = worst
        for item in items:
            if getattr(item, "selector", None) and not getattr(rep, "selector", None):
                rep = item
                break
        result.append(
            {
                "rule": rule,
                "severity": worst.severity,
                "title": worst.title,
                "meaning": plain_impact(worst)[0],
                "fix": plain_impact(worst)[1],
                "count": len(items),
                "pages_count": len(pages),
                "pages": pages,
                "examples": pages[:3],
                "selectors_count": len(selectors),
                "representative": rep,
            }
        )

    result.sort(key=lambda g: (g["severity"].rank, -g["pages_count"], -g["count"], g["rule"]))
    return result


# Понятный владельцу сайта язык: (что это значит, что делать).
PLAIN_IMPACT: dict[str, tuple[str, str]] = {
    "content/missing-lang": (
        "Скринридер не сможет выбрать язык озвучки — часть ваших клиентов услышит текст с неверным произношением.",
        'Укажите язык страницы: <html lang="ru">',
    ),
    "content/missing-title": (
        "У страницы пустое имя вкладки и заголовок в поиске — клиент не поймёт, куда попал, и закроет вкладку.",
        "Задайте осмысленный <title> для каждой страницы.",
    ),
    "content/missing-description": (
        "В поиске вместо вашего текста показывается случайный фрагмент страницы — это снижает переходы.",
        'Добавьте <meta name="description"> с коротким описанием страницы.',
    ),
    "content/missing-viewport": (
        "Сайт не подстраивается под телефон — часть мобильных клиентов уходит сразу.",
        'Добавьте <meta name="viewport" content="width=device-width, initial-scale=1">',
    ),
    "content/missing-charset": (
        "Кириллица и другие нелатинские символы могут отображаться «кракозябрами» — это выглядит как поломка сайта.",
        'Укажите кодировку явно: <meta charset="utf-8">',
    ),
    "content/no-h1": (
        "Структура страницы не читается: заголовок сайта и разделы не выстроены иерархией.",
        "Добавьте один главный заголовок <h1> на страницу.",
    ),
    "content/multiple-h1": (
        "На странице несколько главных заголовков — поиск и скринридеры путаются в структуре.",
        "Оставьте один <h1>, остальные сделайте <h2> и ниже.",
    ),
    "content/heading-order": (
        "Заголовки идут с пропуском уровней — навигация по странице для скринридера становится непонятной.",
        "Выстройте заголовки по порядку: h2 → h3, без перескоков.",
    ),
    "content/image-alt": (
        "Картинка без описания не читается вслух и не находится поиском по картинкам.",
        'Опишите картинку в alt (для декоративных — alt="" и role="presentation").',
    ),
    "content/frame-title": (
        "Встроенный блок (видео, карта, виджет) не подписан — неясно, что он делает.",
        "Добавьте title или aria-label к iframe.",
    ),
    "content/empty-link-name": (
        "Ссылка без текста (иконка или картинка) — клиент не понимает, куда она ведёт.",
        "Добавьте ссылке подпись или aria-label.",
    ),
    "content/empty-button-name": (
        "Кнопка без подписи — клиент не понимает, что произойдёт после нажатия.",
        "Добавьте текст на кнопку или aria-label.",
    ),
    "content/duplicate-id": (
        "На странице повторяются идентификаторы — сбиваются подписи полей и якорные ссылки.",
        "Сделайте id на странице уникальными.",
    ),
    "content/duplicate-title": (
        "Страницы одного раздела имеют одинаковый заголовок — в поиске и во вкладках они не отличаются друг от друга.",
        "Дайте каждой странице уникальный <title> (добавьте название товара, города или раздела).",
    ),
    "content/duplicate-description": (
        "Страницы одного раздела имеют одинаковое описание — поиск и соцсети не видят различий.",
        "Напишите уникальное meta description для каждой страницы.",
    ),
    "content/missing-og-title": (
        "Когда ссылку копируют в мессенджер или соцсеть, карточка появляется без заголовка — выглядит пусто и непривлекательно.",
        'Добавьте <meta property="og:title" content="Заголовок страницы"> в <head>.',
    ),
    "content/missing-og-image": (
        "Ссылка при репосте без картинки: серый пустой прямоугольник вместо обложки, которую замечают в ленте.",
        'Добавьте <meta property="og:image" content="https://сайт.ru/oblozhka.png"> с обложкой 1200×630.',
    ),
    "forms/control-without-label": (
        "Поле формы без подписи — клиент не понимает, что в него вводить, и часто уходит.",
        "Свяжите каждое поле с <label> через for/id.",
    ),
    "forms/placeholder-as-label": (
        "Подпись поля исчезает, как только клиент начинает печатать, — половина форм теряется.",
        "Добавьте постоянную подпись <label>, а не только placeholder.",
    ),
    "forms/control-without-name": (
        "Поле не отправляется в форму: данные клиента теряются до того, как он их отправит.",
        "Добавьте атрибут name к полю.",
    ),
    "forms/email-without-autocomplete": (
        "Клиенту приходится вводить email вручную — лишний шаг на пути к заявке.",
        'Добавьте autocomplete="email" к email-полю.',
    ),
    "forms/submit-without-accessible-name": (
        "Кнопка отправки без подписи — клиент не понимает, что это кнопка отправки.",
        "Добавьте текст на кнопку или aria-label.",
    ),
    "forms/novalidate": (
        "Форма отключает встроенную браузерную валидацию, но своей проверки нет. Заявка может уйти с ошибками.",
        "Уберите novalidate с формы либо добавьте понятные JS-проверки и сообщения об ошибках.",
    ),
    "forms/email-wrong-type": (
        "Поле для e-mail имеет тип «text». На мобильном не появится нужная клавиатура, базовая проверка слабее.",
        'Используйте type="email" для поля ввода почты.',
    ),
    "forms/tel-missing-inputmode": (
        'Поле телефона лучше сделать с inputmode="tel" — так на мобильном будет удобнее набирать номер.',
        'Добавьте inputmode="tel" (и при необходимости pattern) к полю телефона.',
    ),
    "links/empty-href": (
        "Ссылка ведёт в никуда — клик не даёт эффекта и выглядит как поломка.",
        "Укажите реальный адрес или используйте кнопку.",
    ),
    "links/target-blank-noopener": (
        "Открытая вкладка получает доступ к вашему сайту — мелкая, но реальная дыра в безопасности.",
        'Добавьте rel="noopener" к ссылкам с target="_blank".',
    ),
    "links/mixed-content": (
        "Часть ресурсов грузится по http — браузер может заблокировать их и показать «небезопасное» предупреждение.",
        "Переведите все ресурсы страницы на https.",
    ),
    "links/broken": (
        "Ссылка ведёт на несуществующую страницу — клиент попадает на 404 и уходит.",
        "Исправьте или удалите ссылку.",
    ),
    "links/unreachable": (
        "Ссылка не открывается — вероятно, сервер недоступен или адрес неверный.",
        "Проверьте адрес и доступность сервера.",
    ),
    "console/error": (
        "В браузере клиента происходит ошибка — часть интерактива может не работать.",
        "Исправьте скрипт по тексту ошибки (файл/строка указаны в сообщении).",
    ),
    "console/warning": (
        "Браузер предупреждает о проблеме в коде — сейчас работает, но может сломаться после обновления.",
        "Устраните предупреждение в консоли.",
    ),
    "console/failed-request": (
        "Ресурс не загрузился — картинка/скрипт/шрифт может отсутствовать и ломать отображение/логику.",
        "Проверьте URL упавшего ресурса: исправьте путь, разрешения или отключите неиспользуемый ресурс.",
    ),
    "viewport/horizontal-overflow": (
        "На телефоне сайт прокручивается вбок — часть клиентов сразу уходит.",
        "Сделайте элементы адаптивными: ширина 100%, перенос текста, flex-wrap.",
    ),
    "viewport/overflowing-element": (
        "Блок или картинка вылезает за границу экрана телефона.",
        "Ограничьте ширину блока и включите перенос.",
    ),
    "viewport/target-size": (
        "Кнопки мелковаты — удобнее, если увеличить, но если по ним можно кликнуть, это не блокер.",
        "При возможности увеличьте кликабельную область, не перекрывая элемент другими блоками.",
    ),
    "interaction/button-blocked": (
        "Кнопку или ссылку нельзя кликнуть — другой элемент перекрывает её. Из-за этого клиент не может оставить заявку/заказ.",
        "Убрать/сдвинуть перекрывающий элемент, скорректировать z-index или отступы.",
    ),
}

# Типовые правила axe-core, которые чаще всего встречаются и которые стоит
# переводить на человеческий язык.
_AXE_IMPACT: dict[str, tuple[str, str]] = {
    "image-alt": (
        "Картинка без описания не читается вслух и не находится поиском по картинкам.",
        'Опишите картинку в alt (для декоративных — alt="" и role="presentation").',
    ),
    "button-name": (
        "Кнопка без подписи — клиент не понимает, что произойдёт после нажатия.",
        "Добавьте текст на кнопку или aria-label.",
    ),
    "link-name": (
        "Ссылка без текста — клиент не понимает, куда она ведёт.",
        "Добавьте ссылке подпись или aria-label.",
    ),
    "color-contrast": (
        "Текст сливается с фоном — часть клиентов просто не читает текст.",
        "Усильте контраст до 4.5:1 для обычного текста.",
    ),
    "link-in-text-block": (
        "Ссылки отличаются от обычного текста только цветом — их сложно заметить.",
        "Добавьте отличительный признак: подчеркивание, иконку или другой стиль, не полагаясь только на цвет.",
    ),
    "label": (
        "Поле формы без подписи — клиент не понимает, что в него вводить.",
        "Свяжите каждое поле с <label> через for/id.",
    ),
    "html-has-lang": (
        "Скринридер не сможет выбрать язык озвучки.",
        'Укажите язык страницы: <html lang="ru">',
    ),
    "document-title": (
        "У страницы пустое имя вкладки — клиент не понимает, куда попал.",
        "Задайте осмысленный <title>.",
    ),
    "landmark-one-main": (
        "Нет главного блока страницы — скринридеру сложно ориентироваться.",
        "Оберните основное содержимое в <main>.",
    ),
    "page-has-heading-one": (
        "На странице нет главного заголовка — структура страницы не читается.",
        "Добавьте один <h1>.",
    ),
    "region": (
        "Часть страницы не относится ни к одному блоку — скринридер теряет структуру.",
        "Разложите содержимое по <header>, <nav>, <main>, <footer>.",
    ),
    "frame-title": (
        "Встроенный блок (видео, карта) не подписан.",
        "Добавьте title или aria-label к iframe.",
    ),
    "heading-order": (
        "Заголовки идут с пропуском уровней — навигация по странице путается.",
        "Выстройте заголовки по порядку без перескоков.",
    ),
    "duplicate-id": (
        "На странице повторяются идентификаторы — сбиваются подписи полей.",
        "Сделайте id уникальными.",
    ),
    "tabindex": (
        "Порядок перехода по клавиатуре нарушен — до некоторых элементов невозможно добраться.",
        "Уберите лишний tabindex или задайте правильный порядок.",
    ),
    "nested-interactive": (
        "Кнопка вложена в ссылку — элементы перехватывают клики друг у друга.",
        "Разнесите интерактивные элементы по разным уровням.",
    ),
    "aria-required-attr": (
        "ARIA-разметка настроена неверно — вспомогательные технологии читают её неправильно.",
        "Исправьте атрибуты ARIA по документации.",
    ),
    "skip-link": (
        "Отсутствует ссылка для быстрого перехода к основному содержимому.",
        "Добавьте skip-link в начале страницы.",
    ),
    "meta-viewport": (
        "Настройки viewport мешают масштабированию — это затрудняет чтение на мобильных.",
        'Исправьте <meta name="viewport"> без user-scalable=no и жёстких ограничений масштаба.',
    ),
}


# Находки о самом сканере, а не о сайте: «проверено 20 из 120 ссылок»,
# «элементов больше лимита». Владельцу сайта исправлять тут нечего, поэтому
# в балл и в план действий они не идут — иначе чистая страница получает 99.
DIAGNOSTIC_RULES = frozenset(
    {
        "links/limit-reached",
    }
)


def is_diagnostic(finding: Finding) -> bool:
    """Сообщение о полноте проверки, а не дефект страницы."""
    return finding.rule in DIAGNOSTIC_RULES


def is_site_defect(finding: Finding) -> bool:
    """Дефект самого сайта? Ошибки чужих виджетов (трекеры, карты, SDK) — нет."""
    owner = (finding.details or {}).get("owner")
    return owner in (None, "", "site")


def compute_score(findings: list[Finding]) -> int:
    """Итоговый балл «здоровья» сайта: 0–100.

    Считается по уникальным правилам, а не по числу страниц: если один и тот же
    дефект повторяется на 30 страницах каталога, это одна проблема, а не тридцать.
    Иначе балл скачет в зависимости от размера сайта и перестаёт быть понятным.
    """
    own = [finding for finding in findings if is_site_defect(finding) and not is_diagnostic(finding)]
    if not own:
        return 100

    worst: dict[str, Severity] = {}
    for finding in own:
        current = worst.get(finding.rule)
        if current is None or finding.severity.rank < current.rank:
            worst[finding.rule] = finding.severity

    penalty = sum(_WEIGHTS[severity] for severity in worst.values())
    return max(0, min(100, 100 - penalty))


def score_label(score: int) -> str:
    """Человекочитаемая оценка."""
    if score >= 90:
        return "отлично"
    if score >= 75:
        return "хорошо"
    if score >= 55:
        return "нормально, но есть над чем работать"
    if score >= 30:
        return "плохо"
    return "критично плохо"


def plain_impact(finding: Finding) -> tuple[str, str]:
    """Возвращает (что это значит, что делать) для находки."""
    if finding.rule in PLAIN_IMPACT:
        return PLAIN_IMPACT[finding.rule]
    if finding.rule in _AXE_IMPACT:
        return _AXE_IMPACT[finding.rule]
    msg = finding.message or finding.title or ""
    if msg.strip().startswith(("Ensure", "Elements", "All page content")):
        msg = finding.title or msg
    return (
        msg or finding.title or "Есть проблема с элементом на странице.",
        "Исправьте конкретный элемент по селектору/фрагменту выше. При необходимости посмотрите справку по правилу.",
    )


def top_actions(findings: list[Finding], limit: int = 3) -> list[Finding]:
    """Топ находок, которые стоит закрыть первыми: по серьёзности и количеству страниц."""
    findings = [finding for finding in findings if not is_diagnostic(finding)]
    counts = affected_pages(findings)

    def sort_key(finding: Finding) -> tuple[int, int, str]:
        return (finding.severity.rank, -counts.get(finding.rule, 1), finding.rule)

    unique: dict[str, Finding] = {}
    for finding in sorted(findings, key=sort_key):
        unique.setdefault(finding.rule, finding)
    return list(unique.values())[:limit]
