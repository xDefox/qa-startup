"""Разбор и проверка адреса, введённого пользователем."""

from __future__ import annotations

from urllib.parse import urlsplit


def normalize_url(url: str) -> str:
    """Приводит введённый адрес к полному URL и отбрасывает мусор.

    Проверяется не «похоже ли на домен», а разбирается ли адрес: переводы строк
    (инъекция в заголовок письма), логин/пароль в URL (утечка в логи и реферер),
    порт вне диапазона и пустой хост отклоняются. IPv6 в скобках — валидный адрес.
    """
    cleaned = (url or "").strip()
    if not cleaned:
        raise ValueError("Укажите адрес сайта")
    if any(char in cleaned for char in "\r\n\t") or any(ord(char) < 32 for char in cleaned):
        raise ValueError("В адресе есть недопустимые символы")
    if " " in cleaned:
        raise ValueError("Похоже, это не адрес сайта")
    if not cleaned.startswith(("http://", "https://")):
        cleaned = f"https://{cleaned}"

    parsed = urlsplit(cleaned)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Поддерживаются только http и https")
    if parsed.username or parsed.password:
        raise ValueError("Логин и пароль в адресе не поддерживаются — укажите их в блоке авторизации")
    if not parsed.hostname:
        raise ValueError("Похоже, это не адрес сайта")
    try:
        port = parsed.port
    except ValueError as exc:  # порт не число или вне диапазона
        raise ValueError("Некорректный порт в адресе") from exc
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Некорректный порт в адресе")

    host = parsed.hostname
    if not ("." in host or host == "localhost" or ":" in host):
        raise ValueError("Похоже, это не адрес сайта")
    return cleaned
