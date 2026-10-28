#!/usr/bin/env python3
"""Собирает питч-дек webscope для DeckCraft через deckcraft-cli.

Запуск:  python3 pitch/build_deck.py
Результат: pitch/webscope-pitch.deckcraft + .pptx + .pdf

Визуальная система: белый лист, чёрная типографика, один сигнальный красный,
серифные заголовки + моноширинные метки. Без карточек, скруглений и теней.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from PIL import ImageFont

ROOT = Path(__file__).resolve().parent
CLI = Path("/tmp/squashfs-root/usr/bin/deckcraft-cli")
OUT = ROOT / "webscope-pitch"

# ---------------------------------------------------------------- palette
INK = "#101215"          # 18.8:1 на белом
PAPER = "#FFFFFF"
SOFT = "#F4F5F7"         # нейтральная подложка, не пастель
LINE = "#C9CDD3"
LINE_SOFT = "#E2E5E9"
MUTED = "#3C434D"        # 10:1 на белом
LABEL = "#5A626D"        # 6.2:1 на белом
RED = "#C9280B"          # 5.5:1 на белом, 5.1:1 на SOFT
RED_ON_DARK = "#FF5A3C"  # 6.1:1 на INK
GREEN = "#0B6B3A"        # 6.6:1 на белом
WHITE = "#FFFFFF"
DARK_BODY = "#D6D9DE"    # 13.3:1 на INK
DARK_MUTED = "#A7ADB7"   # 8.3:1 на INK
DARK_LINE = "#343A42"

# ---------------------------------------------------------------- fonts
FONTS = {
    "sans": (
        "Noto Sans",
        "/usr/share/fonts/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/noto/NotoSans-Bold.ttf",
    ),
    "serif": (
        "Noto Serif",
        "/usr/share/fonts/noto/NotoSerif-Regular.ttf",
        "/usr/share/fonts/noto/NotoSerif-Bold.ttf",
    ),
    "mono": (
        "Noto Sans Mono",
        "/usr/share/fonts/noto/NotoSansMono-Regular.ttf",
        "/usr/share/fonts/noto/NotoSansMono-Bold.ttf",
    ),
}

W, H = 960, 540
M = 64
TOTAL = 17

TIMINGS = [20, 45, 35, 45, 40, 35, 35, 35, 35, 35, 35, 45, 45, 35, 0, 0, 0]

_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def measure(text: str, size: float, bold: bool = False, font: str = "sans") -> float:
    _, regular, heavy = FONTS[font]
    path = heavy if bold else regular
    key = (path, int(round(size)))
    handle = _font_cache.get(key)
    if handle is None:
        handle = ImageFont.truetype(path, key[1])
        _font_cache[key] = handle
    return handle.getlength(text)


def estimate_lines(
    text: str, size: float, width: float, bold: bool = False, font: str = "sans"
) -> int:
    total = 0
    for para in text.split("\n"):
        if not para.strip():
            total += 1
            continue
        words = para.split(" ")
        line = ""
        count = 1
        for word in words:
            probe = word if not line else f"{line} {word}"
            if measure(probe, size, bold, font) <= width * 0.97:
                line = probe
            else:
                count += 1
                line = word
        total += count
    return total


class Deck:
    def __init__(self) -> None:
        self.cmds: list[str] = []
        self.warnings: list[str] = []
        self.slide = -1
        self.page = 0

    def add(self, cmd: str, params: dict | None = None) -> None:
        if params is None:
            self.cmds.append(cmd)
        else:
            self.cmds.append(f"{cmd}={json.dumps(params, ensure_ascii=False)}")

    # -- scaffolding ------------------------------------------------------
    def new_slide(self, bg: str = PAPER, notes: str = "") -> None:
        self.page += 1
        self.add("slide.new", {"layout": "blank"})
        self.slide += 1
        self.add("design.background", {"color": bg})
        sec = TIMINGS[self.page - 1] if self.page - 1 < len(TIMINGS) else 0
        if notes:
            prefix = f"[~{sec} сек] " if sec else "[приложение] "
            self.add("slide.notes", {"text": prefix + notes})

    def text(
        self,
        body: str,
        rect: tuple[float, float, float, float],
        size: float,
        color: str = INK,
        bold: bool = False,
        align: str = "left",
        anchor: str = "top",
        line: float = 1.2,
        spacing: float = 0,
        caps: bool = False,
        font: str = "sans",
        warn: bool = True,
    ) -> None:
        x, y, w, h = rect
        lines = estimate_lines(body, size, w, bold, font)
        need = lines * size * line * 1.18
        if warn and need > h * 1.08:
            self.warnings.append(
                f"слайд {self.page}: текст выше блока ({need:.0f} > {h:.0f} pt): {body[:40]!r}"
            )
        self.add("insert.textBox", {"rect": list(rect), "text": body})
        self.add("format.font", {"family": FONTS[font][0]})
        self.add("format.size", {"size": size})
        self.add("format.bold", {"on": bold})
        self.add("format.color", {"color": color})
        self.add("format.align", {"align": align})
        self.add("format.anchor", {"anchor": anchor})
        self.add("format.lineSpacing", {"lines": line})
        self.add("format.margins", {"left": 0, "top": 0, "right": 0, "bottom": 0})
        self.add("format.wrap", {"on": True})
        if spacing:
            self.add("format.spacing", {"pt": spacing})
        if caps:
            self.add("format.caps", {"caps": "all"})

    def box(
        self,
        rect: tuple[float, float, float, float],
        fill: str,
        line_color: str | None = None,
        line_width: float = 1,
    ) -> None:
        self.add("shape.insert", {"preset": "rect", "rect": list(rect), "text": ""})
        self.add("shape.fill", {"color": fill})
        if line_color:
            self.add("shape.line", {"color": line_color, "width": line_width})
        else:
            self.add("shape.line", {"none": True})

    def rule(self, x: float, y: float, w: float, color: str = LINE, width: float = 0.75) -> None:
        self.box((x, y, w, width), color)

    # -- type styles ------------------------------------------------------
    def kicker(self, text: str, dark: bool = False) -> None:
        self.text(
            text,
            (M, 32, 700, 12),
            8.5,
            DARK_MUTED if dark else LABEL,
            True,
            spacing=1.0,
            caps=True,
            font="mono",
            line=1.0,
        )
        self.rule(M, 52, W - 2 * M, DARK_LINE if dark else LINE, 0.75)

    def headline(
        self,
        text: str,
        size: float = 38,
        color: str = INK,
        y: float = 68,
        w: float = W - 2 * M,
    ) -> None:
        self.text(
            text,
            (M, y, w, size * 2.7),
            size,
            color,
            True,
            line=1.02,
            font="serif",
        )

    def footer(self, dark: bool = False) -> None:
        color = DARK_MUTED if dark else LABEL
        self.text("webscope", (M, 508, 320, 12), 8, color, font="mono", line=1.0)
        self.text(
            f"{self.page:02d} / {TOTAL}",
            (W - M - 90, 508, 90, 12),
            8,
            color,
            align="right",
            font="mono",
            line=1.0,
        )

    def label(self, text: str, x: float, y: float, w: float = 260, color: str = LABEL) -> None:
        self.text(text, (x, y, w, 12), 8, color, True, spacing=0.8, caps=True, font="mono", line=1.0)


# ---------------------------------------------------------------- slides
def build() -> Deck:
    d = Deck()
    d.add("file.new", {"size": [W, H], "theme": "Ember"})
    d.add("file.properties", {"title": "webscope — питч", "author": "webscope"})
    d.add("design.fonts", {"major": "Noto Serif", "minor": "Noto Sans"})
    d.add("slide.delete", {"index": 0})
    d.slide = -1

    # ------------------------------------------------------------ 1. титул
    d.new_slide(
        INK,
        notes=(
            "Начать с одной фразы, не с названия компании: «Сайт теряет клиентов молча». "
            "Пауза. Потом представиться: webscope — мониторинг работоспособности сайта. "
            "Сегодня: проблема, решение, рынок, экономика и план до декабря."
        ),
    )
    d.text(
        "SPACE UNIVERSITY  /  ПИТЧ  /  27.10.2026",
        (M, 32, 600, 12),
        8.5,
        DARK_MUTED,
        True,
        spacing=1.0,
        font="mono",
        line=1.0,
    )
    d.rule(M, 52, W - 2 * M, DARK_LINE, 0.75)
    d.text(
        "Сайт теряет\nклиентов молча.",
        (M, 118, 620, 128),
        54,
        WHITE,
        True,
        line=1.02,
        font="serif",
    )
    d.text(
        "webscope проверяет клики, формы и заявки раньше, чем клиент.\n"
        "Мониторинг работоспособности сайта для малого бизнеса и ИП.",
        (M, 268, 580, 58),
        15.5,
        DARK_BODY,
        line=1.45,
    )
    d.box((M, 356, 46, 4), RED_ON_DARK)
    d.text(
        "Беларусь · 2026",
        (M, 380, 400, 14),
        9,
        DARK_MUTED,
        font="mono",
        line=1.0,
    )

    # правая колонка — содержание
    index = [
        ("01", "Проблема"),
        ("02", "Решение"),
        ("03", "Рынок"),
        ("04", "Экономика"),
        ("05", "План"),
    ]
    ix, iy = 704, 126
    d.label("СОДЕРЖАНИЕ", ix, iy - 22, 192, DARK_MUTED)
    for i, (num, name) in enumerate(index):
        y = iy + i * 30
        d.text(num, (ix, y, 30, 14), 8.5, RED_ON_DARK, True, font="mono", line=1.0)
        d.text(name, (ix + 34, y, 160, 14), 10, WHITE, font="mono", line=1.0)
        d.rule(ix, y + 18, 192, DARK_LINE, 0.5)
    d.text(
        "Мониторинг сайтов  /  демо по запросу",
        (W - M - 320, 508, 320, 12),
        8,
        DARK_MUTED,
        align="right",
        font="mono",
        line=1.0,
    )

    # ------------------------------------------------------------ 2. проблема
    d.new_slide(
        PAPER,
        notes=(
            "Ключевая мысль: сайт не падает целиком — он ломается по частям, и владелец "
            "узнаёт об этом последним. Три сценария — то, что мы реально находим на демо-стендах. "
            "Не называть вымышленные цифры потерь."
        ),
    )
    d.kicker("01  /  ПРОБЛЕМА")
    d.headline("Сайт выглядит целым.\nЗаявки не приходят.")
    d.text(
        "Страница открывается, дизайн на месте — а кнопка не нажимается. Форма уходит "
        "в никуда. Скрипт падает после обновления. Владелец узнаёт об этом последним: "
        "из жалобы клиента или из просевшей выручки.",
        (M, 190, 360, 140),
        13,
        MUTED,
        line=1.55,
    )
    problems = [
        ("01", "Клиент не может нажать", "Кнопку перекрыл баннер, модалка или фиксированный блок."),
        ("02", "Заявка не доходит", "Форма падает с ошибкой или отправляет в пустоту."),
        ("03", "Сломалось после релиза", "Обновили сайт — отвалился скрипт или стили."),
    ]
    y = 178
    for num, title, body in problems:
        d.text(num, (488, y + 2, 28, 12), 8, RED, True, font="mono", line=1.0)
        d.text(title, (520, y - 2, 376, 24), 14, INK, True, line=1.15)
        d.text(body, (520, y + 22, 376, 42), 11, MUTED, line=1.4)
        d.rule(488, y + 66, 408, LINE_SOFT, 0.75)
        y += 90
    d.rule(M, 452, 60, RED, 2)
    d.text(
        "Ни один из этих сбоев не виден по «сайт открывается».",
        (M, 466, 832, 20),
        12,
        INK,
        True,
    )
    d.footer()

    # ------------------------------------------------------------ 3. почему сейчас
    d.new_slide(
        INK,
        notes=(
            "Три внешних фактора: сайты собирают на конструкторах, релизы ускорились, "
            "доступность стала требованием. Аудиты дорогие и разовые. Источник по WordPress "
            "и Tilda — Inclient, 2026; цена аудита — оценка рынка. Не обещать, что весь рынок наш."
        ),
    )
    d.kicker("02  /  ПОЧЕМУ СЕЙЧАС", dark=True)
    d.headline("Сайты меняются быстрее,\nчем их успевают проверять.", color=WHITE)
    d.rule(M, 186, W - 2 * M, RED_ON_DARK, 1.4)
    stats = [
        ("РЫНОК", "1,2 млн", "установок WordPress и Tilda\nв России — оценка, Inclient 2026"),
        ("ЦЕНА", "$200–3 000", "стоит разовый аудит —\nи устаревает на следующий день"),
        ("ПРАВО", "28.06.2025", "EAA в ЕС: доступность обязательна\nдля e-commerce и сервисов"),
    ]
    x = M
    for tag, value, caption in stats:
        d.label(tag, x, 202, 240, DARK_MUTED)
        d.text(value, (x, 220, 250, 40), 28, WHITE, True, font="mono", line=1.0)
        d.text(caption, (x, 270, 244, 64), 10.5, DARK_BODY, line=1.45)
        x += 283
    d.text(
        "Раньше сайт проверяли перед запуском. Теперь он меняется каждую неделю —\n"
        "а проверяют его по-прежнему раз в год.",
        (M, 392, 760, 58),
        15,
        WHITE,
        True,
        line=1.45,
    )
    d.footer(dark=True)

    # ------------------------------------------------------------ 4. решение
    d.new_slide(
        PAPER,
        notes=(
            "Три шага: измеряем, подтверждаем, объясняем. Главное отличие от Lighthouse — "
            "каждая находка подтверждена в браузере и у неё есть адрес: селектор и фрагмент кода. "
            "Результат можно сразу отдать разработчику или AI-агенту как ТЗ."
        ),
    )
    d.kicker("03  /  РЕШЕНИЕ")
    d.headline("Открываем сайт как клиент —\nи проверяем, что он может сделать.")
    steps = [
        ("01", "Измеряем", "Открываем страницы в реальном браузере: клики, формы, консоль, сеть, мобильная вёрстка."),
        ("02", "Подтверждаем", "Каждая находка — с селектором, фрагментом кода и причиной. Без «кажется, что сломано»."),
        ("03", "Объясняем", "Отчёт на языке владельца + готовое ТЗ для разработчика или AI-агента."),
    ]
    x = M
    for num, title, body in steps:
        d.text(num, (x, 184, 50, 30), 24, RED, True, font="mono", line=1.0)
        d.rule(x, 226, 250, INK, 1.0)
        d.text(title, (x, 240, 250, 28), 20, INK, True, line=1.1, font="serif")
        d.text(body, (x, 280, 244, 110), 11.5, MUTED, line=1.5)
        x += 283
    d.box((M, 420, 832, 64), INK)
    d.text(
        "Не «доступность 74%», а «кнопку #cta нельзя нажать: её перекрывает .cookie».",
        (M + 20, 439, 792, 26),
        10.5,
        WHITE,
        anchor="middle",
        font="mono",
        line=1.2,
    )
    d.footer()

    # ------------------------------------------------------------ 5. отчёт
    d.new_slide(
        PAPER,
        notes=(
            "Показать, что получает владелец. Слева — фрагмент отчёта: сверху блок «блокирует клики», "
            "ниже селектор и фрагмент кода. Справа — четыре свойства. Подчеркнуть: сначала то, "
            "что мешает заявке, а не мелкие a11y-замечания."
        ),
    )
    d.kicker("04  /  ПРОДУКТ")
    d.headline("Отчёт, который говорит,\nчто делать.")
    cx, cy, cw, ch = M, 176, 480, 312
    d.box((cx, cy, cw, ch), PAPER, INK, 1.2)
    d.box((cx, cy, cw, 44), INK)
    d.box((cx + 18, cy + 17, 8, 8), RED_ON_DARK)
    d.text("БЛОКИРУЕТ КЛИКИ", (cx + 34, cy + 14, 300, 16), 9, WHITE, True, spacing=0.8, caps=True, font="mono", line=1.0)
    d.text("01", (cx + cw - 44, cy + 14, 28, 16), 8, DARK_MUTED, align="right", font="mono", line=1.0)
    d.text(
        "Кнопку нельзя нажать: её\nперекрывает баннер",
        (cx + 18, cy + 60, cw - 36, 50),
        15,
        INK,
        True,
        line=1.2,
    )
    d.label("СЕЛЕКТОР", cx + 18, cy + 122, 120)
    d.box((cx + 18, cy + 138, 64, 22), SOFT, LINE, 0.75)
    d.text("#cta", (cx + 26, cy + 141, 50, 16), 10, RED, True, font="mono", line=1.0)
    d.box((cx + 18, cy + 170, cw - 36, 44), SOFT)
    d.text(
        '<button id="cta" class="cta">\nОставить заявку</button>',
        (cx + 26, cy + 176, cw - 52, 34),
        8.5,
        INK,
        font="mono",
        line=1.45,
    )
    d.rule(cx + 18, cy + 226, cw - 36, LINE, 0.75)
    d.label("ЧТО СДЕЛАТЬ", cx + 18, cy + 238, 160)
    d.text(
        "Убрать перекрывающий элемент или поднять кнопку по z-index.\nПроверить на мобильном.",
        (cx + 18, cy + 254, cw - 36, 34),
        9.5,
        MUTED,
        line=1.4,
    )
    points = [
        ("01", "Сначала — то, что мешает заявке"),
        ("02", "Селектор и код: не надо искать причину"),
        ("03", "Оценка 0–100 и план из трёх действий"),
        ("04", "Отчёт открывается по ссылке — без установки"),
    ]
    y = 184
    for num, point in points:
        d.text(num, (576, y + 1, 28, 12), 8, RED, True, font="mono", line=1.0)
        d.text(point, (606, y - 2, 290, 40), 11.5, INK, True, line=1.3)
        d.rule(576, y + 46, 320, LINE_SOFT, 0.75)
        y += 56
    d.text(
        "Пример отчёта. Проверка демо-стенда.",
        (576, 426, 320, 16),
        8.5,
        LABEL,
        font="mono",
        line=1.2,
    )
    d.footer()

    # ------------------------------------------------------------ 6. модель
    d.new_slide(
        PAPER,
        notes=(
            "Разовая проверка — товар, её заменяет бесплатный Lighthouse. Платить будут за "
            "непрерывность: еженедельный прогон, дифф с прошлым, алерт. Это причина подписки. "
            "Единица оплаты — сайт, а не пользователь. Цена Solo — 12 долларов в месяц."
        ),
    )
    d.kicker("05  /  МОДЕЛЬ ПРОДУКТА")
    d.headline("Разовая проверка — товар.\nРегулярная — услуга.")
    d.label("РАЗОВЫЙ АУДИТ", M, 190, 340, RED)
    d.text(
        "Нашли 40 проблем.\nДальше — сами.",
        (M, 210, 360, 64),
        22,
        INK,
        True,
        line=1.15,
        font="serif",
    )
    left_items = [
        "2–3 недели ожидания",
        "Отчёт устаревает на следующий день",
        "Непонятно, что из этого важное",
        "Никто не проверяет, починили ли",
    ]
    for i, item in enumerate(left_items):
        y = 292 + i * 30
        d.text("—", (M, y, 18, 16), 11, LABEL, True, line=1.0)
        d.text(item, (M + 22, y - 1, 340, 18), 11.5, MUTED, line=1.2)
    d.box((476, 176, 420, 280), INK)
    d.label("WEBSCOPE", 496, 194, 340, RED_ON_DARK)
    d.text(
        "Каждую неделю —\nтолько изменения.",
        (496, 214, 360, 64),
        22,
        WHITE,
        True,
        line=1.15,
        font="serif",
    )
    right_items = [
        "$12/мес за сайт",
        "Дифф: что сломалось с прошлого раза",
        "Алерт в Telegram или на почту",
        "История и тренд — видно, что чинят",
    ]
    for i, item in enumerate(right_items):
        y = 292 + i * 30
        d.text("→", (496, y - 1, 18, 16), 11, RED_ON_DARK, True, line=1.0)
        d.text(item, (518, y - 1, 358, 18), 11.5, DARK_BODY, line=1.2)
    d.text(
        "Подписка держится на диффе, а не на отчёте.",
        (M, 474, 832, 20),
        11.5,
        INK,
        True,
    )
    d.footer()

    # ------------------------------------------------------------ 7. клиенты
    d.new_slide(
        PAPER,
        notes=(
            "Фокус — малый бизнес и ИП. Это владельцы сайтов, которые теряют заявки и не имеют "
            "человека на техпроверку. Под «агентствами» я имел в виду веб-студии и фрилансеров "
            "с клиентскими сайтами, а не QA-подрядчиков. Но продажа через них требует времени, "
            "поэтому сейчас они не приоритет."
        ),
    )
    d.kicker("06  /  КЛИЕНТЫ")
    d.headline("Сначала — малый бизнес и ИП.", size=34)
    d.text(
        "Тем, у кого сайт приносит заявки, но нет человека на техпроверку.",
        (M, 132, 832, 18),
        11.5,
        MUTED,
        line=1.2,
    )
    segs = [
        (
            "Малый бизнес",
            "ОСНОВНОЙ СЕГМЕНТ",
            "Локальные услуги, торговля, e-commerce. Сайт приносит заявки, своего разработчика нет.",
            ["кафе, салоны, ремонт, магазины", "заявка с сайта — основной канал", "нет техкоманды"],
        ),
        (
            "ИП и самозанятые",
            "ВТОРОЙ СЕГМЕНТ",
            "Лендинг, портфолио, одна страница. Настраивают сами, документацию не читают.",
            ["лендинг или визитка", "нужна проверка в один клик", "платят из личных денег"],
        ),
    ]
    x = M
    for title, tag, body, bullets in segs:
        d.rule(x, 170, 380, INK, 1.0)
        d.label(tag, x, 184, 380, RED if tag == "ОСНОВНОЙ СЕГМЕНТ" else LABEL)
        d.text(title, (x, 202, 380, 28), 20, INK, True, line=1.1, font="serif")
        d.text(body, (x, 240, 360, 54), 11, MUTED, line=1.5)
        for j, bullet in enumerate(bullets):
            by = 306 + j * 26
            d.box((x, by + 6, 5, 5), RED)
            d.text(bullet, (x + 16, by, 340, 18), 10, MUTED, line=1.2)
        d.text("$12/мес", (x, 392, 80, 26), 16, RED, True, font="mono", line=1.0)
        d.label("ЗА САЙТ В МЕСЯЦ", x + 90, 398, 290, LABEL)
        x += 452
    d.text(
        "Веб-студии и фрилансеры — не приоритет: длинный цикл продажи и чужие клиенты. Вернёмся после стабильного MVP.",
        (M, 456, 832, 18),
        10,
        MUTED,
        line=1.3,
    )
    d.footer()

    # ------------------------------------------------------------ 8. рынок
    d.new_slide(
        PAPER,
        notes=(
            "Фокус — малый бизнес и ИП. 1,2 млн установок WordPress и Tilda в России — оценка "
            "Inclient, 2026; 250 тысяч — те, у кого есть заявки и бюджет. 80 платящих сайтов — "
            "сценарий, не прогноз; консервативный — 40. TAM и SAM в деньгах — оценка сверху."
        ),
    )
    d.kicker("07  /  РЫНОК")
    d.headline("Рынок — малый бизнес и ИП.", size=34, w=600)
    d.text(
        "Верхняя оценка — весь рынок; сценарий — 80 сайтов, а не миллиарды.",
        (M, 132, 600, 18),
        11.5,
        MUTED,
        line=1.2,
    )
    d.label("В ДЕНЬГАХ", 704, 146, 192, LABEL)
    rows = [
        ("TAM", "1,2 млн", "сайтов на WordPress и Tilda в РФ — оценка, Inclient 2026", "$170 млн/год", "оценка сверху"),
        ("SAM", "250 тыс.", "принимают заявки и могут платить — оценка ~20%", "$36 млн/год", "оценка"),
        ("SOM", "80", "платящих сайтов малого бизнеса и ИП к дек. 2027 — сценарий", "$17 тыс. ARR", "сценарий"),
    ]
    y = 172
    for tag, count, desc, money, note in rows:
        d.label(tag, M, y + 6, 50)
        d.text(count, (120, y, 190, 40), 30, INK, True, font="mono", line=1.0)
        d.text(desc, (320, y + 2, 360, 50), 11, MUTED, line=1.45)
        d.text(money, (704, y + 2, 192, 18), 11.5, INK, True, align="right", font="mono", line=1.0)
        d.text(note, (704, y + 22, 192, 14), 8, LABEL, align="right", font="mono", line=1.0)
        d.rule(M, y + 70, 832, LINE_SOFT, 0.75)
        y += 80
    d.box((688, 172, 0.75, 250), LINE)
    d.text(
        "Фокус — малый бизнес и ИП; веб-студии — позже. TAM/SAM — оценки сверху, не прогноз.\n"
        "Цены в USD, оплата в BYN по курсу.",
        (M, 430, 832, 44),
        9.5,
        LABEL,
        line=1.5,
    )
    d.footer()

    # ------------------------------------------------------------ 9. конкуренты
    d.new_slide(
        PAPER,
        notes=(
            "Не спорим с Lighthouse: он бесплатный и хороший. Но он технический и разовый. "
            "Ручной аудит — дорого и долго. Uptime-мониторинг видит только «сервер отвечает». "
            "Наше преимущество — поведение в браузере, диффы и машинное ТЗ."
        ),
    )
    d.kicker("08  /  КОНКУРЕНТЫ")
    d.headline("Мы не соревнуемся в отчётах.\nМы соревнуемся в непрерывности.", size=34)
    widths = [150, 160, 160, 170, 192]
    xs = [M]
    for w in widths[:-1]:
        xs.append(xs[-1] + w)
    y0 = 170
    d.box((M, y0, 832, 40), INK)
    d.box((xs[4], y0, widths[4], 4), RED_ON_DARK)
    heads = ["", "Lighthouse", "Ручной аудит", "Uptime-мониторинг", "webscope"]
    for i, name in enumerate(heads):
        if not name:
            continue
        d.text(
            name,
            (xs[i] + 10, y0 + 12, widths[i] - 20, 18),
            9.5,
            WHITE,
            i == 4,
            line=1.1,
        )
    rows = [
        ("Что проверяет", "метрики и правила", "всё, вручную", "сервер отвечает", "клики, формы, заявки"),
        ("Когда", "разово", "раз в 2–3 недели", "24/7, поверхностно", "еженедельно + дифф"),
        ("Цена", "$0", "$200–3 000", "$6–35/мес", "$12/мес за сайт"),
        ("Язык отчёта", "технический", "экспертный", "технический", "владельца сайта"),
    ]
    d.box((xs[4], y0 + 40, widths[4], 232), SOFT)
    y = y0 + 40
    for row in rows:
        d.text(row[0], (xs[0] + 10, y + 12, widths[0] - 16, 36), 9, LABEL, True, line=1.3)
        for i in range(1, 5):
            strong = i == 4
            d.text(
                row[i],
                (xs[i] + 10, y + 12, widths[i] - 18, 38),
                9,
                INK if strong else MUTED,
                strong,
                line=1.35,
            )
        d.rule(M, y + 58, 832, LINE_SOFT, 0.75)
        y += 58
    d.text(
        "Преимущество: детерминированный движок · диффы · готовое ТЗ для AI-агента",
        (M, 466, 832, 18),
        10.5,
        RED,
        True,
    )
    d.footer()

    # ------------------------------------------------------------ 10. стек
    d.new_slide(
        PAPER,
        notes=(
            "Технологии выбраны под ограничение «один VPS, ноль DevOps». Playwright даёт "
            "реальный браузер. axe-core — отраслевой стандарт. MCP — канал в AI-инструменты. "
            "Принципиально: LLM не создаёт находки, только объясняет подтверждённые."
        ),
    )
    d.kicker("09  /  ФОРМАТ И СТЕК")
    d.headline("Детерминированное ядро.\nЧеловеческий интерфейс.", size=36)
    flow = [
        ("01", "Краулер", "robots.txt, sitemap,\nгруппировка по шаблонам"),
        ("02", "Браузер", "Playwright: клики,\nформы, консоль, сеть"),
        ("03", "Оценка и дифф", "0–100, что изменилось\nс прошлого прогона"),
        ("04", "Отчёт и ТЗ", "JSON, HTML, SARIF,\nпромпт для агента"),
    ]
    x = M
    for i, (num, title, body) in enumerate(flow):
        d.rule(x, 180, 180, INK, 1.0)
        d.text(num, (x, 190, 40, 12), 8, RED, True, font="mono", line=1.0)
        d.text(title, (x, 206, 180, 20), 12, INK, True, line=1.15)
        d.text(body, (x, 230, 170, 48), 9.5, MUTED, line=1.42)
        if i < 3:
            d.text("→", (x + 184, 206, 24, 18), 12, RED, True, line=1.0)
        x += 216
    d.rule(M, 306, 832, LINE, 0.75)
    d.label("ФОРМАТ", M, 322, 120)
    d.text(
        "Веб-приложение для владельца  ·  CLI для разработчика  ·  MCP для AI-агента",
        (M, 340, 832, 20),
        11.5,
        INK,
        line=1.2,
    )
    d.label("СТЕК", M, 380, 120)
    d.text(
        "Python 3.13  ·  Playwright  ·  axe-core  ·  FastAPI  ·  SQLite  ·  MCP",
        (M, 398, 832, 20),
        10,
        INK,
        font="mono",
        line=1.2,
    )
    d.text(
        "Принцип: LLM не создаёт находки — только объясняет подтверждённые. Поэтому отчёт воспроизводим.",
        (M, 440, 832, 18),
        9.5,
        MUTED,
        line=1.3,
    )
    d.footer()

    # ------------------------------------------------------------ 11. статус
    d.new_slide(
        PAPER,
        notes=(
            "Только статус продукта: что уже собрано и работает, без бизнес-метрик. "
            "Цифры: 66 автотестов, 6 проверок, около 3 секунд на страницу. "
            "Следующий шаг — точность на реальных сайтах и установка без ручной настройки."
        ),
    )
    d.kicker("10  /  СДЕЛАНО")
    d.headline("Что уже работает.")
    checks = [
        "6 проверок + детектор блокировки кликов",
        "Краулер, история, диффы и алерты",
        "CLI, MCP-сервер и веб-интерфейс",
        "Форматы: JSON, SARIF, JUnit, HTML, plain",
        "CI: сборка, тесты, экспорт",
    ]
    y = 190
    for item in checks:
        d.box((M, y + 6, 5, 5), RED)
        d.text(item, (M + 16, y - 1, 430, 20), 11.5, INK, line=1.25)
        y += 34
    kpis = [("66", "автотестов"), ("6", "проверок"), ("≈3 с", "на страницу")]
    x = 560
    for i, (value, caption) in enumerate(kpis):
        if i:
            d.box((x - 12, 190, 0.75, 44), LINE)
        d.text(value, (x, 190, 100, 38), 26, INK, True, font="mono", line=1.0)
        d.text(caption, (x, 232, 100, 26), 8.5, LABEL, font="mono", line=1.2)
        x += 112
    d.box((M, 340, 832, 130), INK)
    d.text(
        "Собрано ядро. Следующий шаг — точность на реальных сайтах,\n"
        "отчёты и установка без ручной настройки.",
        (M + 20, 360, 792, 90),
        14,
        WHITE,
        line=1.5,
        anchor="middle",
    )
    d.footer()

    # ------------------------------------------------------------ 12. экономика
    d.new_slide(
        PAPER,
        notes=(
            "Экономика намеренно тихая. Десять клиентов покрывают инфраструктуру — без зарплат. "
            "ARPU, CAC и отток — гипотезы, а не факт; уточним по факту. Базовая маржа "
            "около 85 процентов после платежей и LLM. Бюджет до декабря — 800 долларов и четыре "
            "недели работы."
        ),
    )
    d.kicker("11  /  ЭКОНОМИКА")
    d.headline("Десять клиентов покрывают\nинфраструктуру.", size=36)
    d.text(
        "Без зарплат. Это нижняя граница, а не модель роста.",
        (M, 158, 760, 18),
        11,
        MUTED,
        line=1.2,
    )
    tiers = [
        ("Free", "$0", "1 сайт · разовая проверка"),
        ("Solo", "$12/мес", "1 сайт · еженедельно · алерты"),
        ("Studio", "$59/мес", "10 сайтов · брендированный отчёт"),
        ("Agency", "$149/мес", "40 сайтов · API · white-label"),
    ]
    y = 196
    for name, price, body in tiers:
        d.text(name, (M, y, 80, 18), 10.5, INK, True, line=1.15)
        d.text(price, (M + 86, y - 1, 130, 20), 11.5, RED, True, font="mono", line=1.0)
        d.text(body, (M + 230, y, 240, 20), 9.5, MUTED, line=1.2)
        d.rule(M, y + 28, 460, LINE_SOFT, 0.75)
        y += 42
    metrics = [
        ("ARPU", "$18/мес"),
        ("ВАЛОВАЯ МАРЖА", "≈ 85%"),
        ("CAC", "≈ $30"),
        ("ОТТОК", "12%/мес"),
        ("LTV / CAC", "≈ 4×"),
        ("БЕЗУБЫТОЧНОСТЬ", "10 клиентов"),
    ]
    mx, my = 548, 196
    for i, (name, value) in enumerate(metrics):
        col = i % 2
        row = i // 2
        px = mx + col * 168
        py = my + row * 58
        d.text(name, (px, py, 154, 12), 7.5, LABEL, True, spacing=0.6, caps=True, font="mono", line=1.0)
        d.text(value, (px, py + 16, 156, 26), 13, INK, True, font="mono", line=1.0)
    d.rule(M, 370, 832, LINE, 0.75)
    d.label("БЮДЖЕТ ЗАПУСКА", M, 384, 200)
    d.text("$800  +  4 недели full-time", (M, 400, 460, 24), 14, RED, True, font="mono", line=1.0)
    d.label("СЦЕНАРИЙ ДО ДЕК 2027", 548, 384, 240)
    d.text("80 сайтов · MRR $1 440", (548, 400, 348, 22), 12.5, INK, True, line=1.2)
    d.text("выручка 2027 ≈ $9 тыс.", (548, 424, 348, 16), 9, MUTED, font="mono", line=1.0)
    d.text(
        "* 10 клиентов при ARPU $18 и марже 85%; постоянные ≈ $150/мес (инфраструктура, LLM, почта, бухгалтерия), без зарплат.\n"
        "ARPU, маржа, CAC и отток — гипотезы; уточним по факту.\n"
        "Цены в USD, оплата в BYN по курсу.",
        (M, 452, 832, 48),
        8.5,
        LABEL,
        line=1.5,
    )
    d.footer()

    # ------------------------------------------------------------ 13. план
    d.new_slide(
        PAPER,
        notes=(
            "Технический план до декабря: точность, отчёты, стабильность, MCP/CLI, тесты, демо. "
            "Без интервью, пилотов и продаж. Критерий — стабильный прогон на 20 сайтах, "
            "не больше одного критического ложного срабатывания на демо-наборе и установка за 10 минут."
        ),
    )
    d.kicker("12  /  ПЛАН")
    d.headline("План до декабря: довести ядро.", size=34)
    weeks = [
        ("27 окт – 2 ноя", "Точность детектора", "Эталонный корпус, ложные срабатывания, правила для JS-сайтов."),
        ("3–9 ноя", "Отчёты и ТЗ", "HTML/JSON/SARIF, шаблоны для владельца и разработчика."),
        ("10–16 ноя", "Стабильность", "VPS, очередь, логи, бэкапы, повторные прогоны."),
        ("17–23 ноя", "MCP и CLI", "Быстрый старт, примеры, установка без ручной настройки."),
        ("24–30 ноя", "Тесты и метрики", "Регрессия на фикстурах, время прогона, покрытие проверок."),
        ("1–6 дек", "Демо и защита", "Живой прогон, ограничения, план после защиты."),
    ]
    y = 170
    for i, (date, title, body) in enumerate(weeks):
        d.text(date, (M, y, 126, 14), 9, RED, True, font="mono", line=1.0)
        d.text(title, (M + 136, y - 2, 230, 20), 12, INK, True, line=1.15)
        d.text(body, (M + 380, y - 1, 452, 30), 10, MUTED, line=1.3)
        if i < len(weeks) - 1:
            d.rule(M, y + 32, 832, LINE_SOFT, 0.75)
        y += 42
    d.box((M, 438, 832, 54), INK)
    d.text(
        "Критерий: 20 тестовых сайтов без ручных правок · ≤1 критическое ложное срабатывание на демо-наборе · установка за 10 минут",
        (M + 18, 452, 796, 26),
        10.5,
        WHITE,
        True,
        anchor="middle",
        line=1.2,
    )
    d.footer()

    # ------------------------------------------------------------ 14. дальше
    d.new_slide(
        INK,
        notes=(
            "Вместо продаж и пилотов прошу технические ресурсы: 10–20 сайтов для проверки, "
            "ручную разметку 2–3 сайтов, 800 долларов на инфраструктуру и тестовые устройства, "
            "1–2 часа ревью архитектуры. Это следующий шаг, а не продажа."
        ),
    )
    d.kicker("13  /  ДАЛЬШЕ", dark=True)
    d.headline("Что нужно\nдля следующего шага.", color=WHITE, size=40, y=118)
    asks = [
        ("10–20 сайтов", "свои и знакомых — без продаж"),
        ("Разметка", "2–3 сайта вручную: эталон для проверки ошибок"),
        ("$800", "инфраструктура, API, тестовые устройства"),
        ("Ревью", "1–2 часа: архитектура и LLM"),
    ]
    x = M
    for title, body in asks:
        d.rule(x, 268, 180, RED_ON_DARK, 2)
        d.text(title, (x, 282, 176, 30), 15, WHITE, True, line=1.1)
        d.text(body, (x, 318, 168, 58), 10, DARK_BODY, line=1.45)
        x += 216
    d.rule(M, 410, 832, DARK_LINE, 0.75)
    d.text(
        "Сайт ломается тихо. Давайте слышать это первыми.",
        (M, 428, 700, 26),
        16,
        WHITE,
        True,
        font="serif",
        line=1.2,
    )
    d.text(
        "webscope  ·  демо и код — по запросу",
        (M, 476, 500, 16),
        9,
        DARK_MUTED,
        font="mono",
        line=1.0,
    )
    d.text("Вопросы.", (W - M - 160, 476, 160, 16), 9, DARK_MUTED, align="right", font="mono", line=1.0)

    # ------------------------------------------------------------ приложение А
    d.new_slide(PAPER, notes="Приложение для вопросов: что именно проверяем и с какой серьёзностью.")
    d.kicker("ПРИЛОЖЕНИЕ А")
    d.headline("Что проверяем", size=30, y=64)
    rules = [
        ("Клики и ссылки", "перекрытые элементы, href=\"#\", target=_blank без noopener, битые ссылки"),
        ("Формы", "поля без подписи, email как text, novalidate, кнопки без имени"),
        ("Консоль и сеть", "ошибки JS, 404/500 на ресурсах, упавшие запросы"),
        ("Доступность", "axe-core: WCAG 2.0/2.1/2.2 A/AA + best practice"),
        ("Контент", "lang, title, description, viewport, alt, порядок заголовков, дубли id"),
        ("Мобильные", "горизонтальный скролл на 320/768, цели касания < 24×24"),
    ]
    y = 122
    for name, body in rules:
        d.text(name, (M, y, 180, 18), 11.5, INK, True, line=1.2)
        d.text(body, (M + 196, y, 636, 18), 10.5, MUTED, line=1.25)
        d.rule(M, y + 26, 832, LINE_SOFT, 0.75)
        y += 38
    d.text(
        "Серьёзность: critical → serious → moderate → minor. В топ-3 — только то, что мешает заявке.",
        (M, 392, 832, 18),
        9.5,
        LABEL,
        line=1.3,
    )
    d.footer()

    # ------------------------------------------------------------ приложение Б
    d.new_slide(
        PAPER,
        notes=(
            "Базовый сценарий — 80 платящих сайтов к декабрю 2027, MRR 1 440 долларов. "
            "TAM и SAM в деньгах — оценка сверху, не прогноз. Консервативный вариант — 40 сайтов. "
            "Затраты 2027 — около 4 тысяч долларов без зарплат."
        ),
    )
    d.kicker("ПРИЛОЖЕНИЕ Б")
    d.headline("Сценарий по клиентам и выручке", size=30, y=64)
    d.text(
        "Базовый сценарий — 80 платящих сайтов к декабрю 2027; консервативный — 40.",
        (M, 102, 760, 16),
        9.5,
        LABEL,
        line=1.2,
    )
    data = [("ноя 26", 3), ("фев 27", 10), ("май 27", 24), ("авг 27", 50), ("дек 27", 80)]
    base_y, max_h, max_v = 340, 180, 80
    bar_w, gap = 58, 44
    start_x = 96
    d.label("ПЛАТЯЩИХ САЙТОВ", M, 120, 300)
    d.rule(M, base_y, 600, LINE, 0.75)
    for i, (label, value) in enumerate(data):
        bh = max(8, max_h * value / max_v)
        bx = start_x + i * (bar_w + gap)
        d.box((bx, base_y - bh, bar_w, bh), RED if i == len(data) - 1 else INK)
        d.text(str(value), (bx - 6, base_y - bh - 20, bar_w + 12, 16), 10, INK, True, "center", font="mono", line=1.0)
        d.text(label, (bx - 10, base_y + 8, bar_w + 20, 14), 9, LABEL, align="center", font="mono", line=1.0)
    # сценарии
    sx = 620
    d.label("СЦЕНАРИИ", sx, 150, 276)
    scen = [
        ("Базовый · 80 сайтов", "MRR $1 440"),
        ("Консервативный · 40", "MRR $720"),
    ]
    y = 172
    for name, value in scen:
        d.text(name, (sx, y, 180, 18), 9.5, MUTED, line=1.2)
        d.text(value, (sx + 180, y, 96, 18), 9.5, INK, True, align="right", font="mono", line=1.0)
        d.rule(sx, y + 24, 276, LINE_SOFT, 0.75)
        y += 38
    d.text(
        "Безубыточность: 10 клиентов при ARPU $18 — только инфраструктура.\n"
        "С временем основателя ($500/мес) — ≈ 43 клиента.",
        (sx, 262, 276, 54),
        8.5,
        LABEL,
        line=1.4,
    )
    d.text(
        "80 к декабрю 2027  →  MRR $1 440  →  выручка 2027 ≈ $9 тыс.",
        (M, 368, 620, 20),
        11.5,
        INK,
        True,
        line=1.2,
    )
    d.text(
        "Допущения: ARPU $18, отток 12%/мес, CAC $30 — гипотезы. Затраты 2027 ≈ $4 тыс. без зарплат.",
        (M, 398, 832, 18),
        9,
        LABEL,
        line=1.3,
    )
    d.text(
        "TAM $170 млн/год  ·  SAM $36 млн/год  ·  SOM $17 тыс. ARR — оценки сверху, не прогноз.",
        (M, 434, 832, 18),
        8.5,
        LABEL,
        font="mono",
        line=1.3,
    )
    d.footer()

    # ------------------------------------------------------------ приложение В
    d.new_slide(
        PAPER,
        notes=(
            "Приложение для вопросов про деньги и риски. Бюджет — только запуск до защиты, "
            "без зарплат. Риски названы честно, у каждого есть митигация. Отдельно — курс и платежи: "
            "цены в долларах, оплата в белорусских рублях."
        ),
    )
    d.kicker("ПРИЛОЖЕНИЕ В")
    d.headline("Бюджет запуска и риски", size=30, y=64)
    d.label("КУДА ИДУТ ДЕНЬГИ · ЗАПУСК", M, 118, 420)
    budget = [
        ("Инфраструктура: VPS, домен, TLS", "$120"),
        ("LLM API, почта, телеметрия", "$60"),
        ("Юридика: оферта, политика, платежи", "$200"),
        ("Тест трафика: Meta, Google", "$250"),
        ("Резерв", "$170"),
    ]
    y = 142
    for name, value in budget:
        d.text(name, (M, y, 360, 18), 10, MUTED, line=1.2)
        d.text(value, (M + 380, y, 60, 18), 10, INK, True, align="right", font="mono", line=1.0)
        d.rule(M, y + 24, 440, LINE_SOFT, 0.75)
        y += 34
    d.text("Итого", (M, y + 2, 200, 20), 11, INK, True, line=1.2)
    d.text("$800", (M + 360, y + 2, 80, 20), 14, RED, True, align="right", font="mono", line=1.0)
    d.text(
        "Ресурсы: 1 основатель full-time 4 недели; дизайн и разработка — своими силами; "
        "поддержка первых клиентов — 2 часа в день. Постоянные расходы ≈ $150/мес. "
        "Зарплаты основателя и команды в бюджет не входят.",
        (M, y + 34, 440, 64),
        9,
        MUTED,
        line=1.45,
    )

    d.label("РИСКИ И ЧТО ДЕЛАЕМ", 540, 118, 356)
    risks = [
        ("Ложные срабатывания", "каждая находка подтверждена в браузере; цель FP < 10%"),
        ("Отток после починки", "малый бизнес и ИП + регулярные проверки"),
        ("Дорогой трафик", "SEO по «проверка сайта» + бесплатная проверка"),
        ("Юридика и robots", "уважаем robots.txt; только свои и клиентские сайты"),
        ("Курс и платежи", "цены в USD, оплата в BYN; резерв на конвертацию"),
    ]
    y = 142
    for name, body in risks:
        d.text(name, (540, y, 356, 18), 10, INK, True, line=1.2)
        d.text(body, (540, y + 18, 356, 30), 8.5, MUTED, line=1.35)
        y += 50
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
