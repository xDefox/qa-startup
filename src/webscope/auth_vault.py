"""Крепкое шифрование auth.vault: Fernet с ключом из WEBSCOPE_AUTH_KEY."""

from __future__ import annotations

import os

from cryptography.fernet import Fernet

KEY = os.environ.get("WEBSCOPE_AUTH_KEY")
if KEY is None:
    raise ValueError("WEBSCOPE_AUTH_KEY не задан — шифрование auth.vault невозможно")

fernet = Fernet(KEY.encode() if isinstance(KEY, str) else KEY)


def encrypt(value: str) -> str:
    return fernet.encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    return fernet.decrypt(token.encode()).decode()
