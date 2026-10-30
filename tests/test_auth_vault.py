"""Тест шифрования auth.vault: Fernet + WEBSCOPE_AUTH_KEY."""

import os
from cryptography.fernet import Fernet

os.environ["WEBSCOPE_AUTH_KEY"] = Fernet.generate_key().decode()

from webscope.auth_vault import encrypt, decrypt


def test_encrypt_decrypt_roundtrip():
    token = encrypt("secret-password")
    assert decrypt(token) == "secret-password"
