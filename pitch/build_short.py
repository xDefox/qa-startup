#!/usr/bin/env python3
"""Собирает короткую версию питча webscope: 8 слайдов, ~3 минуты.

Запуск:  python3 pitch/build_short.py
Результат: pitch/webscope-pitch-3min.deckcraft + .pptx + .pdf

Длинная версия на 17 слайдов остаётся в build_deck.py и используется
как запас для вопросов.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import build_deck as bd

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "webscope-pitch-3min"
CLI = bd.CLI

INK = bd.INK
PAPER = bd.PAPER
SOFT = bd.SOFT
LINE = bd.LINE
LINE_SOFT = bd.LINE_SOFT
MUTED = bd.MUTED
LABEL = bd.LABEL
RED = bd.RED
RED_ON_DARK = bd.RED_ON_DARK
WHITE = bd.WHITE
DARK_BODY = bd.DARK_BODY
DARK_MUTED = bd.DARK_MUTED
DARK_LINE = bd.DARK_LINE
W, H, M = bd.W, bd.H, bd.M


def build() -> bd.Deck:
    bd.TOTAL = 8
    bd.TIMINGS = [10, 25, 30, 25, 30, 20, 25, 15]

    d = bd.Deck()
    d.add("file.new", {"size": [W, H], "theme": "Ember"})
    d.add("file.properties", {"title": "webscope — питч 3 минуты", "author": "webscope"})
    d.add("design.fonts", {"major": "Noto Serif", "minor": "Noto Sans"})
    d.add("slide.delete", {"index": 0})
    d.slide = -1

    # ------------------------------------------------------------ 1. титул
    d.new_slide(
        INK,
        notes=(
            "Сайт может выглядеть целым, а заявка — не проходить. webscope проверяет "
            "клики, формы и заявки раньше, чем клиент. Дальше — три минуты по делу."
        ),
    )
    d.kicker("SPACE UNIVERSITY  /  ПИТЧ  /  28.10.2026", dark=True)
    d.headline("Сайт теряет\nклиентов молча.", color=WHITE, size=54, y=112)
    d.text(
        "webscope проверяет клики, формы и заявки\nраньше, чем клиент.",
        (M, 262, 620, 64),
        16,
        DARK_BODY,
        line=1.45,
    )
    d.box((M, 352, 46, 4), RED_ON_DARK)
    d.text(
        "Малый бизнес и ИП  ·  Беларусь  ·  2026",
        (M, 374, 600, 16),
        9.5,
        DARK_MUTED,
        font="mono",
        line=1.0,
    )
    d.text(
        "демо — по запросу",
        (W - M - 220, 374, 220, 16),
        9,
        DARK_MUTED,
        align="right",
        font="mono",
        line=1.0,
    )
    d.footer(dark=True)

    # ------------------------------------------------------------ 2. проблема
    d.new_slide(
        PAPER,
        notes=(
            "Три типовых сбоя: клик, форма, релиз. Владелец узнаёт о них последним, "
            "потому что сайт формально открывается. При этом сайт меняется каждую "
            "неделю, а проверяют его раз в год."
        ),
    )
    d.kicker("01  /  ПРОБЛЕМА")
    d.headline("Сайт открывается.\nЗаявка — нет.", size=40)
    d.text(
        "Владелец узнаёт о поломке последним: из жалобы клиента или из просевшей выручки.",
        (M, 180, 832, 18),
        11.5,
        MUTED,
        line=1.2,
    )
    problems = [
        ("01", "Кнопку нельзя нажать", "Баннер, модалка или фиксированный блок перекрывает CTA."),
        ("02", "Форма не доходит", "Ошибка JS или отправка в пустоту — заявки нет."),
        ("03", "Сломалось после релиза", "Обновили сайт — отвалился скрипт или стили."),
    ]
    x = M
    for num, title, body in problems:
        d.rule(x, 230, 250, INK, 1.0)
        d.text(num, (x, 242, 40, 12), 8, RED, True, font="mono", line=1.0)
        d.text(title, (x, 262, 250, 44), 14, INK, True, line=1.15)
        d.text(body, (x, 312, 236, 48), 10, MUTED, line=1.4)
        x += 286
    d.text(
        "Сайт меняется каждую неделю. Проверяют — раз в год.",
        (M, 402, 832, 20),
        14,
        RED,
        True,
        line=1.15,
    )
    d.text(
        "Ни один из этих сбоев не виден по «сайт открывается».",
        (M, 428, 832, 18),
        10,
        MUTED,
        line=1.2,
    )
    d.footer()

    # ------------------------------------------------------------ 3. смысл
    d.new_slide(
        PAPER,
        notes=(
            "Смысл не в отчёте, а в раннем предупреждении. Владелец платит за то, чтобы "
            "узнать о поломке до клиента, получить только изменения и готовое действие. "
            "Это ответ на вопрос «зачем этим пользоваться»."
        ),
    )
    d.kicker("02  /  ЗАЧЕМ")
    d.headline("Зачем это владельцу.", size=36)
    d.text(
        "Не ещё один аудит — раннее предупреждение о том, что мешает заявке.",
        (M, 128, 832, 18),
        11.5,
        MUTED,
        line=1.2,
    )
    values = [
        ("01", "До жалобы", "Проверка по расписанию + Telegram или email."),
        ("02", "Только изменения", "Дифф с прошлым прогоном: что сломалось, что починили."),
        ("03", "Что чинить", "Селектор, фрагмент кода и конкретное действие."),
        ("04", "История", "Видно, что уже исправлено и что осталось."),
    ]
    x = M
    for num, title, body in values:
        d.rule(x, 190, 196, INK, 1.0)
        d.text(num, (x, 202, 36, 12), 8, RED, True, font="mono", line=1.0)
        d.text(title, (x, 218, 190, 22), 14, INK, True, line=1.15)
        d.text(body, (x, 254, 180, 70), 10, MUTED, line=1.45)
        x += 212
    d.rule(M, 356, 832, LINE, 0.75)
    d.text(
        "Владелец платит не за отчёт, а за то, чтобы не терять заявки.",
        (M, 378, 832, 24),
        16,
        RED,
        True,
        font="serif",
        line=1.2,
    )
    d.footer()

    # ------------------------------------------------------------ 4. продукт
    d.new_slide(
        PAPER,
        notes=(
            "В отчёте одна находка: что сломано, селектор, фрагмент кода и что делать. "
            "Не двести проблем, а одно действие. Слева — как это получается, справа — "
            "как выглядит результат."
        ),
    )
    d.kicker("03  /  ПРОДУКТ")
    d.headline("Что получает владелец.", size=36)
    d.text(
        "Одна находка: что сломано, где и как починить.",
        (M, 128, 832, 18),
        11.5,
        MUTED,
        line=1.2,
    )
    steps = [
        ("01", "Открываем как клиент", "Клики, формы, консоль, сеть, мобильная вёрстка."),
        ("02", "Подтверждаем", "Каждая находка — с селектором, кодом и причиной."),
        ("03", "Объясняем", "Отчёт владельцу + готовое ТЗ разработчику."),
    ]
    y = 190
    for num, title, body in steps:
        d.rule(M, y, 380, INK, 1.0)
        d.text(num, (M, y + 12, 34, 12), 8, RED, True, font="mono", line=1.0)
        d.text(title, (M + 44, y + 8, 330, 22), 14, INK, True, line=1.15)
        d.text(body, (M + 44, y + 34, 330, 34), 10, MUTED, line=1.4)
        y += 84
    d.rule(520, 174, 376, INK, 1.5)
    d.label("БЛОКИРУЕТ КЛИКИ", 520, 188, 376, RED)
    d.text(
        "Кнопку нельзя нажать:\nеё перекрывает баннер",
        (520, 210, 376, 48),
        15,
        INK,
        True,
        line=1.25,
    )
    d.label("СЕЛЕКТОР", 520, 274, 376)
    d.text("#cta", (520, 288, 376, 20), 11, INK, True, font="mono", line=1.0)
    d.label("ЧТО СДЕЛАТЬ", 520, 324, 376)
    d.text(
        "Убрать перекрывающий элемент или поднять кнопку по z-index.",
        (520, 340, 352, 44),
        10.5,
        MUTED,
        line=1.4,
    )
    d.text(
        "Пример отчёта. Проверка демо-стенда.",
        (520, 456, 376, 16),
        8.5,
        LABEL,
        font="mono",
        line=1.0,
    )
    d.footer()

    # ------------------------------------------------------------ 5. кому и сколько
    d.new_slide(
        PAPER,
        notes=(
            "Фокус — малый бизнес и ИП: у них сайт приносит заявки, но нет техкоманды. "
            "Solo стоит двенадцать долларов в месяц. Десять клиентов покрывают "
            "инфраструктуру, восемьдесят — сценарий, не прогноз."
        ),
    )
    d.kicker("04  /  КОМУ И ЗА СКОЛЬКО")
    d.headline("Малый бизнес и ИП.", size=40)
    d.text(
        "Тем, у кого сайт приносит заявки, но нет человека на техпроверку.",
        (M, 128, 832, 18),
        11.5,
        MUTED,
        line=1.2,
    )
    segs = [
        ("Малый бизнес", "Услуги, торговля, e-commerce. Заявка с сайта — основной канал."),
        ("ИП и самозанятые", "Лендинг, портфолио, одна страница. Настраивают сами."),
    ]
    x = M
    for title, body in segs:
        d.rule(x, 182, 380, INK, 1.0)
        d.label("СЕГМЕНТ", x, 196, 380, LABEL)
        d.text(title, (x, 214, 380, 28), 20, INK, True, font="serif", line=1.1)
        d.text(body, (x, 252, 360, 44), 10.5, MUTED, line=1.45)
        d.text("Solo  $12/мес", (x, 304, 300, 22), 13, RED, True, font="mono", line=1.0)
        x += 452
    d.rule(M, 350, 832, LINE, 0.75)
    metrics = [
        ("$12/мес", "за сайт"),
        ("10 клиентов", "покрывают инфраструктуру"),
        ("80 сайтов", "сценарий к дек. 2027"),
    ]
    x = M
    for value, caption in metrics:
        d.text(value, (x, 368, 250, 26), 16, INK, True, font="mono", line=1.0)
        d.text(caption, (x, 398, 250, 18), 9, LABEL, font="mono", line=1.2)
        x += 286
    d.text(
        "1,2 млн сайтов РФ → 250 тыс. с заявками. Free — разовая проверка.",
        (M, 446, 832, 16),
        9,
        LABEL,
        line=1.2,
    )
    d.text(
        "Веб-студии — позже. Оплата в BYN по курсу.",
        (M, 464, 832, 16),
        9,
        LABEL,
        line=1.2,
    )
    d.footer()

    # ------------------------------------------------------------ 6. конкуренты
    d.new_slide(
        PAPER,
        notes=(
            "Против Lighthouse, ручного аудита и uptime: мы проверяем клики и формы, "
            "делаем это регулярно и показываем дифф. Не соревнуемся в отчётах — "
            "соревнуемся в непрерывности."
        ),
    )
    d.kicker("05  /  ПОЧЕМУ МЫ")
    d.headline("Не ещё один аудит.", size=38)
    d.text(
        "Сравнение по тому, что видит владелец.",
        (M, 128, 832, 18),
        11.5,
        MUTED,
        line=1.2,
    )
    widths = [150, 160, 160, 170, 192]
    xs = [M]
    for w in widths[:-1]:
        xs.append(xs[-1] + w)
    y0 = 158
    d.box((M, y0, 832, 34), INK)
    d.box((xs[4], y0, widths[4], 4), RED_ON_DARK)
    heads = ["", "Lighthouse", "Ручной аудит", "Uptime", "webscope"]
    for i, name in enumerate(heads):
        if not name:
            continue
        d.text(
            name,
            (xs[i] + 10, y0 + 10, widths[i] - 20, 18),
            9.5,
            WHITE,
            i == 4,
            line=1.1,
        )
    rows = [
        ("Что видит", "метрики и правила", "всё, вручную", "сервер отвечает", "клики, формы, заявки"),
        ("Когда", "разово", "раз в 2–3 недели", "24/7, поверхностно", "еженедельно + дифф"),
        ("Цена", "$0", "$200–3 000", "$6–35/мес", "$12/мес за сайт"),
        ("Язык", "технический", "экспертный", "технический", "владельца сайта"),
    ]
    y = y0 + 34
    for row in rows:
        d.text(row[0], (xs[0] + 10, y + 10, widths[0] - 16, 34), 9, LABEL, True, line=1.3)
        for i in range(1, 5):
            strong = i == 4
            d.text(
                row[i],
                (xs[i] + 10, y + 10, widths[i] - 18, 36),
                9,
                INK if strong else MUTED,
                strong,
                line=1.35,
            )
        d.rule(M, y + 54, 832, LINE_SOFT, 0.75)
        y += 54
    d.text(
        "Преимущество: детерминированный движок · диффы · готовое ТЗ.",
        (M, 438, 832, 18),
        10.5,
        RED,
        True,
    )
    d.footer()

    # ------------------------------------------------------------ 7. статус и границы
    d.new_slide(
        PAPER,
        notes=(
            "Статус: шесть проверок, CLI, MCP, веб, история и диффы, шестьдесят шесть "
            "тестов. Границы: личные кабинеты за логином не проверяем, сложный JS покрыт "
            "не полностью, ложные срабатывания — главный риск, у веб-интерфейса пока нет "
            "авторизации. Безопасность: SSRF-защита, robots.txt, не собираем логины и пароли. "
            "Перед публичным SaaS нужны auth, лимиты и изоляция браузера."
        ),
    )
    d.kicker("06  /  СТАТУС И ГРАНИЦЫ")
    d.headline("Что работает. Что пока нет.", size=34)
    d.text(
        "Статус MVP и границы, которые вижу.",
        (M, 128, 832, 18),
        11.5,
        MUTED,
        line=1.2,
    )
    d.label("РАБОТАЕТ", M, 174, 380)
    works = [
        "6 проверок + блокировка кликов",
        "CLI, MCP и веб-интерфейс",
        "История, диффы, алерты",
        "66 тестов и CI",
    ]
    y = 194
    for item in works:
        d.box((M, y + 6, 5, 5), RED)
        d.text(item, (M + 16, y - 1, 360, 20), 10.5, INK, line=1.25)
        y += 32
    d.label("ГРАНИЦЫ", 516, 174, 380, RED)
    limits = [
        "Личные кабинеты не проверяем",
        "Сложный JS покрыт не полностью",
        "Ложные срабатывания; цель <10%",
        "Веб-интерфейс без авторизации",
    ]
    y = 194
    for item in limits:
        d.box((516, y + 6, 5, 5), RED)
        d.text(item, (532, y - 1, 364, 20), 10.5, INK, line=1.25)
        y += 32
    d.box((M, 340, 832, 130), INK)
    d.label("БЕЗОПАСНОСТЬ", M + 20, 356, 792, RED_ON_DARK)
    d.text(
        "SSRF-защита: только http/https, без private IP и credentials. robots.txt по умолчанию.\n"
        "Логины и пароли не собираем.",
        (M + 20, 376, 792, 40),
        10,
        WHITE,
        line=1.4,
    )
    d.text(
        "Перед публичным SaaS: auth, лимиты, изоляция браузера.",
        (M + 20, 424, 792, 18),
        9,
        DARK_MUTED,
        font="mono",
        line=1.0,
    )
    d.footer()

    # ------------------------------------------------------------ 8. план и запрос
    d.new_slide(
        PAPER,
        notes=(
            "До декабря три технических фокуса: точность, отчёты, стабильность. "
            "Нужны десять-двадцать тестовых сайтов, ручная разметка, восемьсот долларов "
            "и ревью. Закрываю фразой: сайт ломается тихо — давайте слышать это первыми."
        ),
    )
    d.kicker("07  /  ПЛАН")
    d.headline("До декабря — довести ядро.", size=36)
    d.text(
        "Три технических фокуса.",
        (M, 128, 832, 18),
        11.5,
        MUTED,
        line=1.2,
    )
    focuses = [
        ("ТОЧНОСТЬ", "Эталонный корпус, FP <10%", "Правила для JS-сайтов."),
        ("ОТЧЁТЫ", "HTML, JSON, SARIF", "Шаблон ТЗ для разработчика."),
        ("СТАБИЛЬНОСТЬ", "VPS, очередь, бэкапы", "Тесты и установка за 10 минут."),
    ]
    x = M
    for title, body, note in focuses:
        d.rule(x, 182, 250, INK, 1.0)
        d.label(title, x, 196, 250, RED)
        d.text(body, (x, 216, 230, 24), 13, INK, True, line=1.2)
        d.text(note, (x, 246, 230, 36), 10, MUTED, line=1.4)
        x += 286
    d.box((M, 330, 832, 140), INK)
    d.label("ЧТО НУЖНО", M + 20, 346, 400, RED_ON_DARK)
    d.text(
        "10–20 тестовых сайтов · ручная разметка · $800 · ревью",
        (M + 20, 366, 792, 22),
        11,
        WHITE,
        True,
        line=1.2,
    )
    d.text(
        "Демо — по запросу.",
        (M + 20, 398, 400, 16),
        9,
        DARK_MUTED,
        font="mono",
        line=1.0,
    )
    d.text(
        "Сайт ломается тихо.\nДавайте слышать это первыми.",
        (M + 20, 424, 792, 40),
        15,
        WHITE,
        True,
        font="serif",
        line=1.2,
    )
    d.footer()

    return d


def main() -> int:
    deck = build()
    if not CLI.exists():
        print(f"нет deckcraft-cli: {CLI}", file=sys.stderr)
        return 1
    args = [str(CLI), "run"]
    for cmd in deck.cmds:
        args += ["--cmd", cmd]
    args += ["--save", str(OUT.with_suffix(".deckcraft"))]
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout[-3000:])
        print(result.stderr[-3000:], file=sys.stderr)
        return result.returncode
    failures = [ln for ln in result.stdout.splitlines() if ln.startswith("deckcraft-cli:")]
    print(f"команд: {len(deck.cmds)}, слайдов: {deck.page}")
    for warn in deck.warnings:
        print("  !", warn)
    for line in failures:
        print("  ✗", line)
    for fmt in ("pptx", "pdf"):
        target = OUT.with_suffix(f".{fmt}")
        args = [str(CLI), "convert", str(OUT.with_suffix(".deckcraft")), str(target)]
        subprocess.run(args, capture_output=True, text=True)
        print(f"{fmt}: {'ok' if target.exists() else 'FAIL'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
