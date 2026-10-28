"""Уведомления: email и Telegram.

Канал настраивается переменными окружения, чтобы не тащить конфиг в код:

    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM
    TELEGRAM_BOT_TOKEN

Если канал не настроен — отправка молча пропускается (в лог уходит причина).
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage

import httpx

from ..history import DiffReport

LOGGER = logging.getLogger("webscope.alerts")

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def email_configured() -> bool:
    return bool(os.environ.get("SMTP_HOST") and os.environ.get("SMTP_USER"))


def telegram_configured() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN"))


def build_alert_text(site_url: str, diff: DiffReport) -> str:
    """Текст алерта: что сломалось с прошлого раза."""
    delta = diff.score_after - diff.score_before
    sign = f"+{delta}" if delta > 0 else str(delta)
    lines = [
        f"Проверка сайта {site_url}",
        f"Оценка: {diff.score_before} → {diff.score_after} ({sign})",
    ]

    if diff.new_findings:
        lines.append(f"Новых проблем: {len(diff.new_findings)}")
        for entry in diff.new_findings[:10]:
            lines.append(f"• [{entry.severity_after}] {entry.title} — {entry.url}")
    else:
        lines.append("Новых проблем нет")

    worsened = diff.worsened_findings
    if worsened:
        lines.append(f"Ухудшилось (старые проблемы стали серьёзнее): {len(worsened)}")
        for entry in worsened[:10]:
            lines.append(f"• {entry.title}: {entry.severity_before} → {entry.severity_after} — {entry.url}")

    if diff.fixed_findings:
        lines.append(f"Исправлено: {len(diff.fixed_findings)}")

    return "\n".join(lines)


def send_email(to: str, subject: str, body: str) -> bool:
    """Отправляет письмо. Возвращает False, если канал не настроен или ошибка."""
    host = os.environ.get("SMTP_HOST")
    user = os.environ.get("SMTP_USER")
    if not host or not user:
        LOGGER.info("email не настроен (нужны SMTP_HOST и SMTP_USER)")
        return False

    port = int(os.environ.get("SMTP_PORT", "587"))
    sender = os.environ.get("SMTP_FROM", user)
    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    try:
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.starttls()
            password = os.environ.get("SMTP_PASSWORD")
            if password:
                server.login(user, password)
            server.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        LOGGER.warning("не удалось отправить письмо на %s: %s", to, exc)
        return False
    return True


def send_telegram(chat_id: str, text: str) -> bool:
    """Отправляет сообщение в Telegram. False, если токен не задан или ошибка."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        LOGGER.info("telegram не настроен (нужен TELEGRAM_BOT_TOKEN)")
        return False

    try:
        response = httpx.post(
            TELEGRAM_API.format(token=token),
            json={"chat_id": chat_id, "text": text},
            timeout=20,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        LOGGER.warning("не удалось отправить сообщение в Telegram: %s", exc)
        return False
    return True


def notify(
    *,
    site_url: str,
    diff: DiffReport,
    email: str | None = None,
    telegram_chat: str | None = None,
) -> list[str]:
    """Рассылает алерт по настроенным каналам. Возвращает список сработавших каналов."""
    parts = [f"{len(diff.new_findings)} новых проблем"]
    if diff.worsened_findings:
        parts.append(f"ухудшилось: {len(diff.worsened_findings)}")
    subject = f"Проверка сайта {site_url}: " + ", ".join(parts)
    text = build_alert_text(site_url, diff)

    sent: list[str] = []
    if email and send_email(email, subject, text):
        sent.append("email")
    if telegram_chat and send_telegram(telegram_chat, text):
        sent.append("telegram")
    return sent
