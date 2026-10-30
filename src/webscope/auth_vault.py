"""Шифрование паролей к защищённым сайтам (Fernet, ключ из ``WEBSCOPE_AUTH_KEY``).

Пароль от клиентского сайта — такой же секрет, как пароль пользователя: если
база утечёт, из неё не должны читаться учётные данные. Ключ живёт в окружении,
а не в базе; без ключа пароли пишутся как раньше (совместимость с уже
развёрнутыми инсталляциями), и приложение об этом предупреждает.

Fernet — AES-128-CBC + HMAC-SHA256 с ключом в base64. ``cryptography``
импортируется лениво: без ключа пакет не нужен.
"""

from __future__ import annotations

import logging
import os

LOGGER = logging.getLogger("webscope.auth_vault")

# Префикс, по которому видно, что значение зашифровано (старые записи — plaintext).
PREFIX = "fernet:"


def key_configured() -> bool:
    """Задан ли ключ шифрования."""
    return bool((os.environ.get("WEBSCOPE_AUTH_KEY") or "").strip())


def _fernet():
    """Fernet из ``WEBSCOPE_AUTH_KEY`` или None, если ключ не задан."""
    key = (os.environ.get("WEBSCOPE_AUTH_KEY") or "").strip()
    if not key:
        return None
    from cryptography.fernet import Fernet

    return Fernet(key.encode("utf-8"))


def encrypt(value: str) -> str:
    """Шифрует секрет; без ключа возвращает значение как есть."""
    if not value:
        return value
    fernet = _fernet()
    if fernet is None:
        return value
    if value.startswith(PREFIX):  # уже зашифровано — не шифруем повторно
        return value
    return PREFIX + fernet.encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(value: str) -> str:
    """Расшифровывает секрет.

    Незашифрованное значение возвращается как есть (базы до появления ключа),
    а нечитаемый токен — тоже: лучше показать «пароль не расшифровался» при
    попытке входа, чем уронить чтение сайта из базы.
    """
    if not value or not value.startswith(PREFIX):
        return value
    fernet = _fernet()
    if fernet is None:
        LOGGER.warning("пароль зашифрован, но WEBSCOPE_AUTH_KEY не задан — вход на сайт не сработает")
        return ""
    try:
        return fernet.decrypt(value[len(PREFIX) :].encode("ascii")).decode("utf-8")
    except Exception:  # noqa: BLE001 - чужой/испорченный ключ не должен ломать чтение
        LOGGER.warning("не удалось расшифровать пароль: ключ WEBSCOPE_AUTH_KEY не совпадает")
        return ""
