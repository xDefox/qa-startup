"""Тест шифрования auth.vault: Fernet + WEBSCOPE_AUTH_KEY."""

import os

from cryptography.fernet import Fernet

os.environ["WEBSCOPE_AUTH_KEY"] = Fernet.generate_key().decode()

from webscope.auth_vault import decrypt, encrypt


def test_encrypt_decrypt_roundtrip():
    token = encrypt("secret-password")
    assert decrypt(token) == "secret-password"


def test_encrypt_is_idempotent_for_prefix() -> None:
    """Уже зашифрованное значение не шифруется повторно."""
    from webscope.auth_vault import PREFIX

    token = encrypt("secret")
    assert token.startswith(PREFIX)
    assert encrypt(token) == token


def test_plaintext_without_key_is_returned_as_is(monkeypatch) -> None:
    """Базы без ключа продолжают читаться: старые пароли лежат открытым текстом."""
    from webscope.auth_vault import decrypt, key_configured

    monkeypatch.delenv("WEBSCOPE_AUTH_KEY", raising=False)
    assert key_configured() is False
    assert decrypt("plain-password") == "plain-password"


def test_encrypted_password_is_unreadable_without_key(monkeypatch) -> None:
    """Без ключа зашифрованный пароль не подставляется молча."""
    token = encrypt("secret")
    monkeypatch.delenv("WEBSCOPE_AUTH_KEY", raising=False)
    assert decrypt(token) == ""


def test_storage_encrypts_password_at_rest(tmp_path, monkeypatch) -> None:
    """В базе пароль к сайту лежит шифротекстом, наружу отдаётся открытым."""
    import sqlite3

    from webscope.webapp.storage import Storage

    monkeypatch.setenv("WEBSCOPE_AUTH_KEY", Fernet.generate_key().decode())
    db = tmp_path / "db.sqlite"
    storage = Storage(db)
    site = storage.add_site("https://site.com/", auth_kind="basic", auth_login="user", auth_password="p@ss")
    assert site.auth_password == "p@ss"
    assert site.auth_credentials().password == "p@ss"

    connection = sqlite3.connect(db)
    raw = connection.execute("SELECT auth_password FROM sites WHERE id = ?", (site.id,)).fetchone()[0]
    connection.close()
    assert raw.startswith("fernet:")
    assert raw != "p@ss"
    storage.close()
