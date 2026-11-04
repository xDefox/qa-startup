#!/usr/bin/env python3
"""Собирает питч-дек webscope для DeckCraft через deckcraft-cli.

Запуск:  python3 pitch/build_deck.py
Результат: pitch/webscope-pitch.deckcraft + .pptx + .pdf
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import ImageFont

ROOT = Path(__file__).resolve().parent
CLI = Path("/tmp/squashfs-root/usr/bin/deckcraft-cli")
OUT = ROOT / "webscope-pitch"

# ---------------------------------------------------------------- palette
INK = "#1A1A1A"
CREAM = "#FFFCF7"
SAND = "#F6EDE3"
PANEL = "#FBF4EC"
LINE = "#E7D9CB"
MUTED = "#6F6258"
ACCENT = "#D9480F"
ACCENT_DARK = "#B03A0A"
AMBER = "#B54708"
RED = "#B42318"
GREEN = "#087443"
WHITE = "#FFFFFF"

FONT = "/usr/share/fonts/noto/NotoSans-Regular.ttf"
FONT_BOLD = "/usr/share/fonts/noto/NotoSans-Bold.ttf"

W, H = 960, 540
M = 64

# ориентировочный хронометраж: 14 слайдов ≈ 8,5 минут + запас на вопросы
TIMINGS = [20, 45, 35, 45, 40, 35, 35, 35, 35, 35, 35, 45, 45, 35, 0, 0, 0]

_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def measure(text: str, size: float, bold: bool = False) -> float:
    """Ширина строки в пунктах (1 pt = 1 px при scale 1)."""
    key = (FONT_BOLD if bold else FONT, int(round(size)))
    font = _font_cache.get(key)
    if font is None:
        font = ImageFont.truetype(key[0], key[1])
        _font_cache[key] = font
    return font.getlength(text)


def estimate_lines(text: str, size: float, width: float, bold: bool = False) -> int:
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
            if measure(probe, size, bold) <= width * 0.97:
                line = probe
            else:
                count += 1
                line = word
        total += count
    return total


# ---------------------------------------------------------------- builder
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

    # -- slide scaffolding ------------------------------------------------
    def new_slide(self, bg: str = CREAM, notes: str = "") -> None:
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
        line: float = 1.15,
        space_after: float = 0,
        spacing: float = 0,
        caps: int | None = None,
        warn: bool = True,
    ) -> None:
        x, y, w, h = rect
        lines = estimate_lines(body, size, w, bold)
        need = lines * size * line * 1.18 + space_after * max(0, lines - 1)
        if warn and need > h * 1.08:
            self.warnings.append(
                f"слайд {self.page}: текст выше блока ({need:.0f} > {h:.0f} pt): {body[:40]!r}"
            )
        self.add("insert.textBox", {"rect": list(rect), "text": body})
        self.add("format.font", {"family": "Noto Sans"})
        self.add("format.size", {"size": size})
        self.add("format.bold", {"on": bold})
        self.add("format.color", {"color": color})
        self.add("format.align", {"align": align})
        self.add("format.anchor", {"anchor": anchor})
        self.add("format.lineSpacing", {"lines": line})
        self.add("format.margins", {"left": 0, "top": 0, "right": 0, "bottom": 0})
        self.add("format.wrap", {"on": True})
        if space_after:
            self.add("format.paragraph", {"spaceAfter": space_after})
        if spacing:
            self.add("format.spacing", {"pt": spacing})
        if caps == 1:
            self.add("format.caps", {"caps": "all"})

    def box(
        self,
        rect: tuple[float, float, float, float],
        fill: str,
        line_color: str | None = None,
        line_width: float = 1,
        radius: bool = True,
        shadow: bool = False,
    ) -> None:
        self.add("shape.insert", {"preset": "roundRect" if radius else "rect", "rect": list(rect), "text": ""})
        self.add("shape.fill", {"color": fill})
        if line_color:
            self.add("shape.line", {"color": line_color, "width": line_width})
        else:
            self.add("shape.line", {"none": True})
        if radius:
            self.add("shape.smoothCorners", {"smoothing": 18, "radius": 10})
        if shadow:
            self.add(
                "shape.effects",
                {"shadow": {"color": "#3D2B1F", "blur": 22, "dist": 5, "dir": 90}},
            )

    def rule(self, x: float, y: float, w: float, color: str = LINE, width: float = 0.75) -> None:
        self.add("shape.insert", {"preset": "rect", "rect": [x, y, w, width], "text": ""})
        self.add("shape.fill", {"color": color})
        self.add("shape.line", {"none": True})

    def icon(self, name: str, rect: tuple[float, float, float, float], color: str) -> None:
        self.add("insert.icon", {"name": name, "rect": list(rect)})
        self.add("format.color", {"color": color})
        self.add("shape.line", {"color": color, "width": 1.4})

    def kicker(self, text: str, color: str = ACCENT_DARK) -> None:
        self.text(text, (M, 40, 620, 16), 9.5, color, True, spacing=1.4, caps=1, line=1.0)

    def headline(self, text: str, size: float = 34, color: str = INK, y: float = 66, w: float = 832) -> None:
        self.text(text, (M, y, w, size * 2.4), size, color, True, line=0.98)

    def footer(self, dark: bool = False, label: str = "webscope") -> None:
        color = "#9C8B7D" if dark else "#75665A"
        self.text(f"{label}", (M, 508, 300, 12), 8.5, color, line=1.0)
        self.text(f"{self.page:02d}", (W - M - 40, 508, 40, 12), 8.5, color, False, "right", line=1.0)

    def num(self, value: str, caption: str, x: float, y: float, w: float, color: str = INK, size: float = 40) -> None:
        self.text(value, (x, y, w, size * 1.25), size, color, True, line=0.95)
        self.text(caption, (x, y + size * 1.15, w, 44), 11, MUTED, line=1.25)


# ---------------------------------------------------------------- slides
def build() -> Deck:
    d = Deck()
    d.add("file.new", {"size": [W, H], "theme": "Ember"})
    d.add("file.properties", {"title": "webscope — питч", "author": "webscope"})
    d.add("design.fonts", {"major": "Noto Sans", "minor": "Noto Sans"})
    # убираем дефолтный слайд
    d.add("slide.delete", {"index": 0})
    d.slide = -1

    # ------------------------------------------------------------ 1. титул
    d.new_slide(INK, notes=(
        "Начать с одной фразы, не с названия компании: «Сайт ломается тихо». "
        "Пауза. Потом представиться: webscope — мониторинг работоспособности сайта. "
        "Сегодня: проблема, кому продаём, сколько стоит, что будет к декабрю."
    ))
    d.box((M, 64, 46, 5), ACCENT, radius=False)
    d.text("SPACE UNIVERSITY  ·  ПИТЧ  ·  27 ОКТЯБРЯ 2026", (M, 86, 720, 14), 9.5, "#C9B7A6", True, spacing=1.3, caps=1)
    d.text("Сайт теряет\nклиентов молча", (M, 140, 700, 200), 62, CREAM, True, line=0.95)
    d.text(
        "webscope находит сломанные кнопки, формы и ошибки\nраньше, чем клиент",
        (M, 356, 680, 60), 19, "#E8D9C9", line=1.35,
    )
    d.rule(M, 452, 832, "#3A2E24", 1)
    d.text("Мониторинг работоспособности сайта для малого бизнеса и агентств", (M, 470, 600, 16), 10, "#A89A8C")
    d.text("webscope", (W - M - 200, 470, 200, 16), 10, "#A89A8C", False, "right")

    # ------------------------------------------------------------ 2. проблема
    d.new_slide(CREAM, notes=(
        "Ключевая мысль: сайт не падает целиком — он ломается по частям, и владелец "
        "узнаёт об этом последним. Три сценария на карточках — это то, что мы реально "
        "находим на демо-стендах. Не называть вымышленные цифры потерь."
    ))
    d.kicker("01 / ПРОБЛЕМА")
    d.headline("Сайт выглядит целым.\nЗаявки не приходят.")
    d.text(
        "Страница открывается, дизайн на месте — а кнопка не нажимается. Форма уходит в никуда. "
        "Скрипт падает после обновления. Владелец узнаёт об этом последним: из жалобы клиента "
        "или из просевшей выручки.",
        (M, 176, 500, 90), 13.5, MUTED, line=1.5,
    )
    cards = [
        ("circle-alert", "Клиент не может нажать", "Кнопку перекрыл баннер, модалка или фиксированный блок."),
        ("mail", "Заявка не доходит", "Форма падает с ошибкой или отправляет в пустоту."),
        ("triangle-alert", "Сломалось после релиза", "Обновили сайт — отвалился скрипт или стили."),
    ]
    x = M
    for icon, title, body in cards:
        d.box((x, 300, 266, 150), PANEL, LINE, 1)
        d.icon(icon, (x + 20, 320, 20, 20), ACCENT)
        d.text(title, (x + 20, 352, 226, 20), 13, INK, True, line=1.15)
        d.text(body, (x + 20, 378, 226, 58), 11, MUTED, line=1.35)
        x += 283
    d.text(
        "Ни один из этих сбоев не виден по «сайт открывается».",
        (M, 472, 832, 18), 11.5, ACCENT_DARK, True,
    )
    d.footer()

    # ------------------------------------------------------------ 3. почему сейчас
    d.new_slide(SAND, notes=(
        "Три внешних фактора: сайты собирают на конструкторах, релизы ускорились, "
        "доступность стала требованием. Digital-аудиты при этом дорогие и разовые. "
        "Источник цифр по Tilda и WordPress — Inclient, 2026; цена аудита — рынок РФ, 15–300 тыс."
    ))
    d.kicker("02 / ПОЧЕМУ СЕЙЧАС", ACCENT_DARK)
    d.headline("Сайты меняются быстрее,\nчем их успевают проверять.")
    stats = [
        ("1,2 млн", "установок WordPress и Tilda\nв России"),
        ("15–300 тыс ₽", "стоит разовый аудит —\nи устаревает на следующий день"),
        ("28.06.2025", "EAA в ЕС: доступность обязательна\nдля e-commerce и сервисов"),
    ]
    x = M
    for value, caption in stats:
        d.text(value, (x, 230, 250, 44), 30, INK, True, line=1.0)
        d.text(caption, (x, 284, 244, 60), 11, MUTED, line=1.4)
        x += 283
    d.rule(M, 376, 832, "#DCCBBA", 1)
    d.text(
        "Раньше сайт проверяли перед запуском. Теперь он меняется каждую неделю — "
        "а проверяют его по-прежнему раз в год.",
        (M, 400, 760, 50), 15, INK, True, line=1.4,
    )
    d.footer()

    # ------------------------------------------------------------ 4. решение
    d.new_slide(CREAM, notes=(
        "Три шага: измеряем, подтверждаем, объясняем. Главное отличие от Lighthouse — "
        "каждая находка подтверждена в браузере и у неё есть адрес: селектор и фрагмент кода. "
        "И третье: результат можно сразу отдать AI-агенту как ТЗ."
    ))
    d.kicker("03 / РЕШЕНИЕ")
    d.headline("Открываем сайт как клиент —\nи проверяем, что он может сделать.")
    steps = [
        ("01", "Измеряем", "Открываем страницы в реальном браузере: клики, формы, консоль, сеть, мобильная вёрстка."),
        ("02", "Подтверждаем", "Каждая находка — с селектором, фрагментом кода и объяснением причины. Без «кажется, что сломано»."),
        ("03", "Объясняем и чиним", "Отчёт на языке владельца + готовое ТЗ для разработчика или AI-агента."),
    ]
    x = M
    for number, title, body in steps:
        d.text(number, (x, 196, 60, 26), 12, ACCENT, True, line=1.0)
        d.rule(x, 220, 250, "#DCCBBA", 1)
        d.text(title, (x, 238, 250, 26), 19, INK, True, line=1.1)
        d.text(body, (x, 276, 244, 120), 12, MUTED, line=1.45)
        x += 283
    d.box((M, 420, 832, 64), INK, None, radius=True)
    d.text(
        "Не «оценка доступности 74%», а «кнопку #cta нельзя нажать: её перекрывает .cookie».",
        (M + 24, 436, 784, 34), 12.5, CREAM, False, anchor="middle",
    )
    d.footer()

    # ------------------------------------------------------------ 5. отчёт
    d.new_slide(CREAM, notes=(
        "Показать, что получает владелец. Слева — фрагмент отчёта: сверху блок «блокирует клики», "
        "ниже селектор и фрагмент. Справа — четыре свойства отчёта. Подчеркнуть: сначала то, "
        "что мешает заявке, а не «мелкие» a11y-замечания."
    ))
    d.kicker("04 / ПРОДУКТ")
    d.headline("Отчёт, который говорит,\nчто делать.")
    # макет отчёта
    cx, cy, cw, ch = M, 186, 470, 296
    d.box((cx, cy, cw, ch), WHITE, LINE, 1, shadow=True)
    d.box((cx, cy, cw, 46), INK, None, radius=False)
    d.icon("circle-alert", (cx + 18, cy + 15, 16, 16), "#F87171")
    d.text("БЛОКИРУЕТ КЛИКИ", (cx + 44, cy + 13, 300, 20), 10, CREAM, True, spacing=1.0, caps=1)
    d.text("Кнопку нельзя нажать: её\nперекрывает баннер", (cx + 20, cy + 62, cw - 40, 48), 15, INK, True, line=1.2)
    d.text("СЕЛЕКТОР", (cx + 20, cy + 126, 100, 12), 8, "#75665A", True, spacing=0.8, caps=1)
    d.box((cx + 20, cy + 142, 86, 24), SAND, None, radius=True)
    d.text("#cta", (cx + 30, cy + 145, 66, 18), 11, ACCENT_DARK, True, line=1.0)
    d.text("<button id=\"cta\" class=\"cta\">", (cx + 20, cy + 180, cw - 40, 16), 10, MUTED, line=1.2)
    d.text("Оставить заявку</button>", (cx + 20, cy + 196, cw - 40, 16), 10, MUTED, line=1.2)
    d.rule(cx + 20, cy + 226, cw - 40, LINE, 1)
    d.text("ЧТО СДЕЛАТЬ", (cx + 20, cy + 240, 120, 12), 8, "#75665A", True, spacing=0.8, caps=1)
    d.text(
        "Убрать перекрывающий элемент или поднять\nкнопку по z-index. Проверить на мобильном.",
        (cx + 20, cy + 256, cw - 40, 32), 10, MUTED, line=1.35,
    )
    # свойства
    points = [
        ("Сначала — то, что мешает заявке"),
        ("Селектор и код: не надо искать причину"),
        ("Оценка 0–100 и план из трёх действий"),
        ("Отчёт открывается по ссылке — без установки"),
    ]
    y = 196
    for point in points:
        d.icon("check", (548, y + 1, 15, 15), GREEN)
        d.text(point, (574, y, 322, 34), 11.5, INK, line=1.3)
        y += 48
    d.text("Пример отчёта. Проверка демо-стенда.", (548, 408, 322, 26), 9, "#75665A", line=1.3)
    d.footer()

    # ------------------------------------------------------------ 6. продукт: подписка
    d.new_slide(CREAM, notes=(
        "Разовая проверка — товар, её заменяет бесплатный Lighthouse. Платить будут за "
        "непрерывность: еженедельный прогон, дифф с прошлым, алерт. Это и есть причина "
        "подписки. Единица оплаты — сайт, а не пользователь."
    ))
    d.kicker("05 / МОДЕЛЬ ПРОДУКТА")
    d.headline("Разовая проверка — товар.\nРегулярная — услуга.")
    # слева
    d.box((M, 186, 398, 270), PANEL, LINE, 1)
    d.text("РАЗОВЫЙ АУДИТ", (M + 24, 206, 340, 14), 9, "#75665A", True, spacing=0.9, caps=1)
    d.text("Нашли 40 проблем.\nДальше — сами.", (M + 24, 232, 340, 62), 20, INK, True, line=1.15)
    for i, item in enumerate([
        "2–3 недели ожидания",
        "Отчёт устаревает на следующий день",
        "Непонятно, что из этого важное",
        "Никто не проверяет, починили ли",
    ]):
        d.text("—", (M + 24, 306 + i * 30, 14, 18), 11, "#A8978A", True, line=1.2)
        d.text(item, (M + 42, 306 + i * 30, 330, 18), 11.5, MUTED, line=1.2)
    # справа
    d.box((M + 422, 186, 410, 270), INK, None, radius=True)
    d.text("WEBSCOPE", (M + 446, 206, 340, 14), 9, "#E8A07A", True, spacing=0.9, caps=1)
    d.text("Каждую неделю\nтолько изменения.", (M + 446, 232, 360, 62), 20, CREAM, True, line=1.15)
    for i, item in enumerate([
        "990 ₽/мес за сайт",
        "Дифф: что сломалось с прошлого раза",
        "Алерт в Telegram или на почту",
        "История и тренд — видно, что чинят",
    ]):
        d.icon("check", (M + 446, 308 + i * 30, 13, 13), "#F59F00")
        d.text(item, (M + 468, 306 + i * 30, 330, 18), 11.5, "#F0E3D6", line=1.2)
    d.text(
        "Подписка держится на диффе, а не на отчёте.",
        (M, 476, 832, 18), 11.5, ACCENT_DARK, True,
    )
    d.footer()

    # ------------------------------------------------------------ 7. клиенты
    d.new_slide(SAND, notes=(
        "Три сегмента, но входить будем через агентства: один разговор приносит портфель "
        "из 10–50 сайтов. Владелец малого бизнеса — конечный пользователь отчёта, "
        "in-house команда — канал через MCP и open-source ядро."
    ))
    d.kicker("06 / КЛИЕНТЫ", ACCENT_DARK)
    d.headline("Три сегмента — один продукт.")
    segs = [
        ("Владелец малого бизнеса", "Услуги, e-commerce, студии. Нет техкоманды. Платит, чтобы не терять заявки.", "990 ₽/мес", False),
        ("Агентство или студия", "10–50 клиентских сайтов. Продаёт мониторинг как услугу, экономит часы QA.", "4 900–12 900 ₽/мес", True),
        ("In-house команда", "Разработчики и AI-агенты. MCP: скан → ТЗ → правка → повторный скан.", "open-source ядро", False),
    ]
    x = M
    for title, body, price, hot in segs:
        fill = INK if hot else PANEL
        head = CREAM if hot else INK
        sub = "#E8D9C9" if hot else MUTED
        d.box((x, 186, 266, 250), fill, None if hot else LINE, 1, shadow=hot)
        d.text(title, (x + 20, 208, 226, 44), 14, head, True, line=1.15)
        d.text(body, (x + 20, 262, 226, 100), 11, sub, line=1.4)
        d.rule(x + 20, 372, 226, "#4A3B2E" if hot else LINE, 1)
        d.text(price, (x + 20, 386, 226, 24), 13, "#F59F00" if hot else ACCENT_DARK, True, line=1.1)
        if hot:
            d.text("ОСНОВНОЙ КАНАЛ", (x + 20, 414, 226, 12), 7.5, "#B9A896", True, spacing=0.8)
        x += 283
    d.text(
        "Один клиент-агентство = портфель сайтов. Поэтому продажи начинаем с них.",
        (M, 466, 832, 18), 11.5, INK, True,
    )
    d.footer()

    # ------------------------------------------------------------ 8. рынок
    d.new_slide(CREAM, notes=(
        "Оценка снизу вверх, только РФ и только сайты малого бизнеса. TAM — все, кто "
        "теоретически может платить; SAM — те, у кого есть заявки и бюджет; SOM — "
        "реалистичная цель за 12 месяцев. Цифры консервативные: 990 ₽/мес, без апсейла."
    ))
    d.kicker("07 / РЫНОК")
    d.headline("Большой рынок начинается\nс одного сайта.")
    tiers = [
        ("TAM", "1,2 млн", "сайтов на WordPress и Tilda в РФ", "× 990 ₽ × 12", "14,3 млрд ₽/год", "#EFE2D5"),
        ("SAM", "250 тыс.", "из них принимают заявки и готовы платить", "× 990 ₽ × 12", "3,0 млрд ₽/год", "#E6D3C1"),
        ("SOM · 12 мес", "150", "платящих сайтов за 12 месяцев", "× 990 ₽ × 12", "1,8 млн ₽/год", INK),
    ]
    x = M
    for name, value, caption, formula, total, fill in tiers:
        dark = fill == INK
        d.box((x, 186, 266, 220), fill, None, radius=True)
        d.text(name, (x + 20, 202, 226, 12), 8.5, "#C9B7A6" if dark else "#75665A", True, spacing=0.9)
        d.text(value, (x + 20, 226, 226, 48), 34, CREAM if dark else INK, True, line=1.0)
        d.text(caption, (x + 20, 282, 220, 42), 10.5, "#D8C8B8" if dark else MUTED, line=1.35)
        d.text(formula, (x + 20, 330, 220, 14), 9, "#B9A896" if dark else "#75665A", line=1.2)
        d.text(total, (x + 20, 360, 226, 26), 13, "#F59F00" if dark else ACCENT_DARK, True, line=1.1)
        x += 283
    d.text(
        "1,2 млн — установки WordPress и Tilda (Inclient, 2026). SAM — оценка: каждый пятый сайт "
        "принимает заявки. Цена — 990 ₽/мес, без апсейла и других стран.",
        (M, 430, 800, 52), 9.5, "#75665A", line=1.45,
    )
    d.footer()

    # ------------------------------------------------------------ 9. конкуренты
    d.new_slide(CREAM, notes=(
        "Не спорим с Lighthouse: он бесплатный и хороший. Но он технический и разовый. "
        "Аудит-агентство — дорого и долго. Uptime-мониторинг видит только «сервер отвечает». "
        "Наше преимущество — поведение в браузере + диффы + машинное ТЗ."
    ))
    d.kicker("08 / КОНКУРЕНТЫ")
    d.headline("Мы не соревнуемся в отчётах.\nМы соревнуемся в непрерывности.")

    cols = [
        ("", 0.0, 170),
        ("Lighthouse", 1.0, 168),
        ("Аудит-агентство", 2.0, 168),
        ("Uptime-мониторинг", 3.0, 168),
        ("webscope", 4.0, 168),
    ]
    x0, y0 = M, 180
    widths = [156, 166, 166, 166, 178]
    xs = [M]
    for w in widths[:-1]:
        xs.append(xs[-1] + w)
    # колонка webscope подсвечивается до текста, иначе закрасит его
    d.box((xs[4], y0 + 44, widths[4], 248), CREAM, INK, 1.2, radius=False)
    # шапка
    d.box((xs[4], y0, widths[4], 44), INK, None, radius=False)
    for i, (name, _, _) in enumerate(cols):
        if i == 4:
            d.text(name, (xs[i] + 12, y0 + 13, widths[i] - 24, 20), 10.5, "#F59F00", True, line=1.1)
        else:
            d.text(name, (xs[i] + 10, y0 + 13, widths[i] - 20, 20), 10.5, INK if name else MUTED, True, line=1.1)
    rows = [
        ("Что проверяет", "метрики и правила", "всё, вручную", "сервер отвечает", "клики, формы, заявки"),
        ("Когда", "разово", "раз в 2–3 недели", "24/7, поверхностно", "еженедельно + дифф"),
        ("Цена", "0", "15–300 тыс ₽", "500–3 000 ₽/мес", "990 ₽/мес за сайт"),
        ("Язык отчёта", "технический", "экспертный", "технический", "владельца сайта"),
    ]
    y = y0 + 44
    for r, row in enumerate(rows):
        h = 62
        if r % 2 == 0:
            d.box((xs[0], y, xs[4] - xs[0], h), PANEL, None, radius=False)
        d.text(row[0], (xs[0] + 10, y + 12, widths[0] - 18, 38), 9.5, "#75665A", True, line=1.3)
        for i in range(1, 5):
            strong = i == 4
            d.text(row[i], (xs[i] + 10, y + 12, widths[i] - 18, 40), 9.5,
                   INK if strong else MUTED, strong, line=1.35)
        d.rule(xs[0], y + h, sum(widths), "#EADCCE", 0.75)
        y += h
    d.text(
        "Преимущество: детерминированный движок · диффы · готовое ТЗ для AI-агента",
        (M, 480, 832, 16), 10, ACCENT_DARK, True,
    )
    d.footer()

    # ------------------------------------------------------------ 10. стек
    d.new_slide(CREAM, notes=(
        "Технологии выбраны под ограничение «один VPS, ноль DevOps». Playwright даёт "
        "реальный браузер. axe-core — отраслевой стандарт. MCP — канал в AI-инструменты. "
        "Принципиально: LLM не создаёт находки, только объясняет подтверждённые."
    ))
    d.kicker("09 / ПРОДУКТ И СТЕК")
    d.headline("Детерминированное ядро.\nЧеловеческий интерфейс.")
    flow = [
        ("Краулер", "robots.txt, sitemap,\nгруппировка по шаблонам"),
        ("Браузер", "Playwright: клики,\nформы, консоль, сеть"),
        ("Оценка и дифф", "0–100, что изменилось\nс прошлого прогона"),
        ("Отчёт и ТЗ", "JSON, HTML, SARIF,\nпромпт для агента"),
    ]
    x = M
    for i, (title, body) in enumerate(flow):
        d.box((x, 186, 190, 96), PANEL, LINE, 1)
        d.text(title, (x + 14, 200, 162, 20), 12, INK, True, line=1.15)
        d.text(body, (x + 14, 226, 162, 46), 8.5, MUTED, line=1.35)
        if i < 3:
            d.icon("arrow-right", (x + 194, 228, 16, 16), ACCENT)
        x += 214
    d.rule(M, 306, 832, "#DCCBBA", 1)
    d.text("ФОРМАТ", (M, 324, 120, 12), 8.5, "#75665A", True, spacing=0.9)
    d.text(
        "Веб-приложение для владельца  ·  CLI для разработчика  ·  MCP для AI-агента",
        (M, 344, 832, 20), 11.5, INK, line=1.2,
    )
    d.text("СТЕК", (M, 384, 120, 12), 8.5, "#75665A", True, spacing=0.9)
    d.text(
        "Python 3.13  ·  Playwright  ·  axe-core  ·  FastAPI  ·  SQLite  ·  MCP",
        (M, 404, 832, 20), 10.5, INK, line=1.2,
    )
    d.text(
        "Принцип: LLM не создаёт находки — только объясняет подтверждённые. Поэтому отчёт воспроизводим.",
        (M, 446, 832, 18), 9.5, MUTED, line=1.3,
    )
    d.footer()

    # ------------------------------------------------------------ 11. статус
    d.new_slide(SAND, notes=(
        "Честно: продукт готов, бизнеса пока нет. Это нормально для этой стадии и это "
        "главный аргумент, почему следующие пять недель — про клиентов, а не про код. "
        "Цифры: 66 автотестов, 6 проверок, около 3 секунд на страницу."
    ))
    d.kicker("10 / СТАТУС", ACCENT_DARK)
    d.headline("MVP работает.\nПлатящих — пока нет.")
    checks = [
        "6 проверок + детектор блокировки кликов",
        "CLI, MCP-сервер и веб-интерфейс",
        "Краулер, история, диффы, алерты",
        "66 автотестов и CI",
        "Форматы: JSON, SARIF, JUnit, HTML, plain",
    ]
    y = 190
    for item in checks:
        d.icon("check", (M, y + 2, 14, 14), GREEN)
        d.text(item, (M + 26, y - 1, 430, 20), 11.5, INK, line=1.25)
        y += 34
    # KPI справа
    kpis = [("66", "автотестов"), ("6", "проверок"), ("≈3 с", "на страницу")]
    x = 548
    for value, caption in kpis:
        d.box((x, 190, 108, 92), CREAM, LINE, 1)
        d.text(value, (x + 14, 204, 80, 34), 24, INK, True, line=1.0)
        d.text(caption, (x + 14, 244, 84, 24), 9.5, MUTED, line=1.2)
        x += 118
    d.box((M, 386, 832, 92), INK, None, radius=True)
    d.text(
        "Готовность продукта — высокая. Готовность бизнеса — низкая.\n"
        "Поэтому этот питч — про следующие пять недель, а не про фичи.",
        (M + 24, 404, 780, 56), 12.5, CREAM, line=1.45,
    )
    d.footer()

    # ------------------------------------------------------------ 12. экономика
    d.new_slide(CREAM, notes=(
        "Юнит-экономика считается на одном сайте: инфраструктура почти бесплатная, "
        "маржа выше 90%. Основная стоимость — поддержка и продажи. Точка безубыточности — "
        "восемь клиентов. Бюджет до декабря — около 60 тысяч рублей и четыре недели работы."
    ))
    d.kicker("11 / ЭКОНОМИКА")
    d.headline("Восемь клиентов —\nи продукт окупает себя.")
    # тарифы
    tiers = [
        ("Free", "0 ₽", "1 сайт · разовая проверка"),
        ("Solo", "990 ₽/мес", "1 сайт · еженедельно · алерты"),
        ("Studio", "4 900 ₽/мес", "10 сайтов · брендированный отчёт"),
        ("Agency", "12 900 ₽/мес", "40 сайтов · API · white-label"),
    ]
    y = 186
    for name, price, body in tiers:
        d.text(name, (M, y, 90, 20), 11, MUTED, True, line=1.2)
        d.text(price, (M + 100, y - 2, 130, 24), 13, INK, True, line=1.15)
        d.text(body, (M + 240, y, 220, 30), 9.5, MUTED, line=1.25)
        d.rule(M, y + 30, 460, "#EADCCE", 0.75)
        y += 44
    # метрики
    metrics = [
        ("ARPU", "1 700 ₽/мес"),
        ("COGS", "< 10 ₽/сайт/мес"),
        ("Маржа", "> 90%"),
        ("CAC", "≈ 2 000 ₽"),
        ("LTV / CAC", "≈ 7×"),
        ("Точка безубыточности", "8 клиентов"),
    ]
    x, y = 548, 190
    for i, (name, value) in enumerate(metrics):
        col = i % 2
        row = i // 2
        px = x + col * 168
        py = y + row * 58
        d.text(name, (px, py, 150, 12), 8, "#75665A", True, spacing=0.6)
        d.text(value, (px, py + 16, 156, 26), 15, INK, True, line=1.1)
    d.rule(M, 386, 832, "#DCCBBA", 1)
    d.text("Бюджет запуска до декабря", (M, 402, 400, 16), 9, "#75665A", True, spacing=0.7, caps=1)
    d.text("≈ 60 тыс ₽  +  4 недели full-time", (M, 422, 480, 24), 15, ACCENT_DARK, True, line=1.2)
    d.text(
        "VPS и домен · LLM API · оферта и политика · тест трафика · резерв",
        (M, 450, 460, 16), 9.5, MUTED, line=1.2,
    )
    d.text("ПЛАН НА ГОД", (548, 402, 348, 12), 9, "#75665A", True, spacing=0.7)
    d.text("150 сайтов · MRR 255 тыс ₽", (548, 420, 348, 22), 12.5, INK, True, line=1.2)
    d.text("выручка ≈ 1 млн ₽ за 12 месяцев", (548, 444, 348, 16), 9.5, MUTED, line=1.2)
    d.footer()

    # ------------------------------------------------------------ 13. план
    d.new_slide(CREAM, notes=(
        "Пять недель, каждая с проверяемым результатом. Не «доделать продукт», а "
        "«получить клиентов и доказать, что отчёт приводит к действию». Критерий "
        "успеха к защите: 3 платящих и один кейс с измеримым эффектом."
    ))
    d.kicker("12 / ПЛАН")
    d.headline("Пять недель до защиты.")
    weeks = [
        ("27 окт – 1 ноя", "Лендинг и 10 интервью", "Бесплатная проверка по URL, воронка, разговоры с владельцами и агентствами."),
        ("2–8 ноя", "5 пилотов", "Ручной мониторинг, первые находки, обратная связь по отчёту."),
        ("9–15 ноя", "Онбординг без меня", "Тарифы, оферта, брендированный отчёт, оплата по счёту."),
        ("16–22 ноя", "3 платящих + кейс", "Один сайт: нашли блокер, починили, замерили эффект."),
        ("23–29 ноя", "Метрики и репетиция", "Финмодель по факту, финальное демо, прогон защиты."),
        ("30 ноя – 6 дек", "Защита", "Go / no-go по трём критериям."),
    ]
    y = 176
    for i, (date, title, body) in enumerate(weeks):
        last = i == len(weeks) - 1
        d.text(date, (M, y, 118, 14), 9.5, ACCENT_DARK, True, line=1.2)
        d.text(title, (M + 130, y - 2, 240, 20), 12, INK, True, line=1.15)
        d.text(body, (M + 380, y - 1, 452, 30), 10.5, MUTED, line=1.3)
        if not last:
            d.rule(M, y + 32, 832, "#EEE1D4", 0.75)
        y += 42
    d.box((M, 438, 832, 54), SAND, None, radius=True)
    d.text(
        "Критерий успеха: 50 проверок · 10 интервью · 5 пилотов · 3 платящих · 1 кейс с цифрами",
        (M + 20, 452, 792, 24), 11, INK, True, anchor="middle",
    )
    d.footer()

    # ------------------------------------------------------------ 14. запрос
    d.new_slide(INK, notes=(
        "Заканчиваем просьбой, а не «спасибо за внимание». Три конкретные вещи, которые "
        "можно дать сегодня: пилот, интро, ментор. Сумма — на инфраструктуру и проверку "
        "канала, не на зарплаты."
    ))
    d.box((M, 64, 46, 5), ACCENT, radius=False)
    d.text("13 / ЗАПРОС", (M, 86, 300, 14), 9.5, "#C9B7A6", True, spacing=1.3, caps=1)
    d.text("Что нужно,\nчтобы дойти до декабря.", (M, 130, 640, 130), 40, CREAM, True, line=1.0)
    asks = [
        ("3 пилота", "владельцы сайтов или агентства из зала"),
        ("5 интро", "к студиям с портфелем клиентских сайтов"),
        ("60–90 тыс ₽", "инфраструктура и первые тесты канала"),
        ("2 часа в неделю", "ментор по B2B-продажам"),
    ]
    x = M
    for i, (title, body) in enumerate(asks):
        d.text(title, (x, 300, 190, 26), 15, "#F59F00", True, line=1.1)
        d.text(body, (x, 330, 180, 56), 10.5, "#D8C8B8", line=1.4)
        x += 212
    d.rule(M, 412, 832, "#3A2E24", 1)
    d.text("Сайт ломается тихо. Давайте слышать это первыми.", (M, 432, 700, 26), 16, CREAM, True, line=1.2)
    d.text("webscope  ·  демо и код — по запросу", (M, 476, 500, 16), 9.5, "#A89A8C")
    d.text("Спасибо.", (W - M - 120, 476, 120, 16), 9.5, "#A89A8C", False, "right")

    # ------------------------------------------------------------ приложение A
    d.new_slide(CREAM, notes="Приложение для вопросов: что именно проверяем и с какой серьёзностью.")
    d.kicker("ПРИЛОЖЕНИЕ А")
    d.headline("Что проверяем", 30, y=64)
    rules = [
        ("Клики и ссылки", "перекрытые элементы, href=\"#\", target=_blank без noopener, битые ссылки"),
        ("Формы", "поля без подписи, email как text, novalidate, кнопки без имени"),
        ("Консоль и сеть", "ошибки JS, 404/500 на ресурсах, упавшие запросы"),
        ("Доступность", "axe-core: WCAG 2.0/2.1/2.2 A/AA + best practice"),
        ("Контент", "lang, title, description, viewport, alt, порядок заголовков, дубли id"),
        ("Мобильные", "горизонтальный скролл на 320/768, цели касания < 24×24"),
    ]
    y = 130
    for name, body in rules:
        d.text(name, (M, y, 190, 20), 12, INK, True, line=1.2)
        d.text(body, (M + 200, y, 632, 20), 11, MUTED, line=1.25)
        d.rule(M, y + 26, 832, "#EEE1D4", 0.75)
        y += 38
    d.text("Серьёзность: critical → serious → moderate → minor. В топ-3 попадает только то, что мешает заявке.", (M, 404, 832, 16), 10, "#75665A")
    d.footer()

    # ------------------------------------------------------------ приложение B
    d.new_slide(CREAM, notes="План по месяцам: консервативный сценарий, 150 платящих сайтов к декабрю 2027.")
    d.kicker("ПРИЛОЖЕНИЕ Б")
    d.headline("План по клиентам и выручке", 30, y=64)
    # столбики рисуем фигурами: аккуратнее и предсказуемее нативного графика
    data = [("ноя 26", 3), ("фев 27", 15), ("май 27", 40), ("авг 27", 90), ("дек 27", 150)]
    base_y, max_h, max_v = 352, 190, 150
    bar_w, gap = 62, 48
    start_x = M + 38
    d.rule(M, base_y, 600, "#DCCBBA", 1)
    for i, (label, value) in enumerate(data):
        bh = max(8, max_h * value / max_v)
        bx = start_x + i * (bar_w + gap)
        d.box((bx, base_y - bh, bar_w, bh), ACCENT if i == len(data) - 1 else "#E2CDBA", None, radius=False)
        d.text(str(value), (bx - 6, base_y - bh - 22, bar_w + 12, 18), 12, INK, True, "center", line=1.0)
        d.text(label, (bx - 10, base_y + 8, bar_w + 20, 14), 9.5, MUTED, False, "center", line=1.1)
    d.text("ПЛАТЯЩИХ САЙТОВ", (M, 124, 300, 12), 8.5, "#75665A", True, spacing=0.8)
    d.text("150 к декабрю 2027  →  MRR 255 тыс ₽  →  выручка года ≈ 1 млн ₽", (M, 404, 620, 20), 11.5, INK, True, line=1.3)
    d.text(
        "Допущения: ARPU 1 700 ₽, отток 10%/мес, рост за счёт агентств и SEO.\n"
        "Затраты года: инфраструктура 30 тыс, маркетинг 180 тыс, юридика 30 тыс.",
        (M, 450, 620, 46), 9.5, MUTED, line=1.45,
    )
    d.box((716, 130, 180, 160), SAND, None, radius=True)
    d.text("ТОЧКА БЕЗУБЫТОЧНОСТИ", (736, 148, 140, 24), 7.5, "#75665A", True, spacing=0.6)
    d.text("8", (736, 176, 140, 50), 40, INK, True, line=1.0)
    d.text("клиентов при ARPU\n1 700 ₽ и марже 90%", (736, 234, 140, 40), 8.5, MUTED, line=1.35)
    d.footer()

    # ------------------------------------------------------------ приложение C
    d.new_slide(CREAM, notes=(
        "Приложение для вопросов про деньги и риски. Бюджет — только запуск до защиты, "
        "без зарплат. Главные риски названы честно, у каждого есть митигация."
    ))
    d.kicker("ПРИЛОЖЕНИЕ В")
    d.headline("Бюджет запуска и риски", 30, y=64)

    d.text("КУДА ИДУТ ДЕНЬГИ · 3 МЕСЯЦА", (M, 128, 420, 12), 9, "#75665A", True, spacing=0.8)
    budget = [
        ("Инфраструктура: VPS, домен, TLS", "8 000 ₽"),
        ("LLM API, почта, телеметрия", "4 000 ₽"),
        ("Юридика: оферта, политика, платежи", "15 000 ₽"),
        ("Тест трафика: Директ и VK", "20 000 ₽"),
        ("Резерв", "13 000 ₽"),
    ]
    y = 152
    for name, value in budget:
        d.text(name, (M, y, 330, 18), 10.5, MUTED, line=1.2)
        d.text(value, (M + 340, y, 80, 18), 10.5, INK, True, "right", line=1.2)
        d.rule(M, y + 24, 420, "#EEE1D4", 0.75)
        y += 34
    d.text("Итого", (M, y + 2, 200, 20), 11, INK, True, line=1.2)
    d.text("60 000 ₽", (M + 320, y + 2, 100, 20), 14, ACCENT_DARK, True, "right", line=1.2)
    d.text(
        "Ресурсы: 1 основатель full-time 4 недели, дизайн и разработка — своими силами, "
        "поддержка первых клиентов — 2 часа в день. Зарплаты основателя и команды в бюджет не входят.",
        (M, y + 34, 420, 60), 9.5, MUTED, line=1.4,
    )

    d.text("РИСКИ И ЧТО ДЕЛАЕМ", (540, 128, 340, 12), 9, "#75665A", True, spacing=0.8)
    risks = [
        ("Ложные срабатывания", "каждая находка подтверждена в браузере; цель FP < 10%"),
        ("Отток после починки", "агентства с портфелем + регулярные проверки"),
        ("Дорогой трафик", "SEO по «проверка сайта» + партнёрства со студиями"),
        ("Юридика и robots", "уважаем robots.txt; проверяем только свои и клиентские сайты"),
    ]
    y = 152
    for name, body in risks:
        d.text(name, (540, y, 356, 18), 11, INK, True, line=1.2)
        d.text(body, (540, y + 20, 356, 34), 9.5, MUTED, line=1.35)
        y += 60
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
    # экспорт
    for fmt in ("pptx", "pdf"):
        target = OUT.with_suffix(f".{fmt}")
        args = [str(CLI), "convert", str(OUT.with_suffix(".deckcraft")), str(target)]
        r = subprocess.run(args, capture_output=True, text=True)
        print(f"{fmt}: {'ok' if r.returncode == 0 else r.stderr.strip()[:200]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
