"""Сервис операций с сайтами — единая точка истины для бизнес-логики.

Сейчас содержит CRUD для Site + Organization. В будущем здесь будут
методы: schedule_scan, get_report, billing ops и т.д.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ...auth_vault import decrypt as vault_decrypt
from ...auth_vault import encrypt as vault_encrypt
from ..storage import Site, Storage, _site_from_row


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _seal(password: str | None) -> str | None:
    """Шифрует пароль перед записью (без WEBSCOPE_AUTH_KEY — как есть)."""
    return vault_encrypt(password) if password else password


def _open(password: str | None) -> str | None:
    """Расшифровывает пароль из базы (старые записи — plaintext)."""
    return vault_decrypt(password) if password else password


class Organization:
    """Организация, к которой принадлежит сайт."""

    def __init__(self, id: int, name: str, owner_email: str, created_at: str):
        self.id = id
        self.name = name
        self.owner_email = owner_email
        self.created_at = created_at


def create_organization(
    storage: Storage,
    *,
    name: str,
    owner_email: str,
) -> Organization:
    """Создаёт организацию и возвращает объект."""
    # Самое простое: добавляем запись в конфигурационную таблицу
    # или просто создаём идентификатор и сохраняем метаданные.
    # Пока возвращаем структуру, storage.update_site будет привязывать sites к org.
    with storage._conn() as conn:
        org_id = conn.execute(
            "INSERT OR IGNORE INTO organizations (name, owner_email, created_at) VALUES (?, ?, ?)",
            (name, owner_email, now_iso()),
        ).lastrowid
        conn.commit()
    return Organization(id=org_id, name=name, owner_email=owner_email, created_at=now_iso())


def get_organization(storage: Storage, org_id: int) -> Organization | None:
    """Получает организацию по ID."""
    with storage._conn() as conn:
        row = conn.execute(
            "SELECT id, name, owner_email, created_at FROM organizations WHERE id = ?",
            (org_id,),
        ).fetchone()
    if row is None:
        return None
    return Organization(
        id=row[0], name=row[1], owner_email=row[2], created_at=row[3]
    )


def create_site(
    storage: Storage,
    *,
    url: str,
    organization_id: int,
    email: str | None = None,
    telegram_chat: str | None = None,
    schedule: str = "off",
    interval_days: int = 7,
    auth_kind: str | None = None,
    auth_login: str | None = None,
    auth_password: str | None = None,
    auth_login_url: str | None = None,
) -> Site:
    """Создаёт сайт, привязанный к организации.

    Ранее sites не имели явной привязки к организации — теперь
    каждый site имеет organization_id, а organization_id = 0 (или None)
    означает "общий/непривязанный".
    """
    # Гарантируем, что организация существует
    org = get_organization(storage, organization_id)
    if org is None:
        raise ValueError(f"Organization with id={organization_id} does not exist")

    # Проверяем, не существует ли сайт с таким URL уже
    existing = storage.get_site_by_url(url)
    if existing is not None:
        existing_site = existing
        # Если переданы новые авторизационные данные — обновляем их
        if auth_kind is not None:
            storage.update_site(existing_site.id,
                auth_kind=auth_kind,
                auth_login=auth_login,
                auth_password=_seal(auth_password),
                auth_login_url=auth_login_url,
            )
            # Возвращаем обновлённый сайт из БД
            return storage.get_site(existing_site.id)
        return existing_site

    # Создаём новый сайт
    site = Site(
        id=0,
        url=url,
        email=email,
        telegram_chat=telegram_chat,
        schedule=schedule,
        interval_days=interval_days,
        auth_kind=auth_kind,
        auth_login=auth_login,
        auth_password=_seal(auth_password),
        auth_login_url=auth_login_url,
        created_at=now_iso(),
        organization_id=organization_id,
    )

    with storage._conn() as conn:
        conn.execute(
            """INSERT INTO sites 
               (url, email, telegram_chat, schedule, interval_days, 
                auth_kind, auth_login, auth_password, auth_login_url, 
                organization_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                url,
                email,
                telegram_chat,
                schedule,
                interval_days,
                auth_kind,
                auth_login,
                site.auth_password,
                auth_login_url,
                organization_id,
                now_iso(),
            ),
        )
        conn.commit()

    # Возвращаем созданный сайт с ID
    with storage._conn() as conn:
        row = conn.execute(
            "SELECT * FROM sites WHERE url = ? ORDER BY id DESC LIMIT 1",
            (url,),
        ).fetchone()
        if row is None:
            raise RuntimeError("Site was not created despite INSERT success")
        return _site_from_row(row)


def list_sites(
    storage: Storage,
    *,
    organization_id: int | None = None,
) -> list[Site]:
    """Список сайтов, фильтр по организации опционален."""
    if organization_id is not None:
        with storage._conn() as connection:
            rows = connection.execute(
                "SELECT * FROM sites WHERE organization_id = ? ORDER BY id",
                (organization_id,),
            ).fetchall()
    else:
        with storage._conn() as connection:
            rows = connection.execute("SELECT * FROM sites ORDER BY id").fetchall()
    return [_site_from_row(row) for row in rows]


def get_organizations(storage: Storage) -> list[Organization]:
    """Все организации — для UI-селектора."""
    with storage._conn() as connection:
        rows = connection.execute(
            "SELECT id, name, owner_email, created_at FROM organizations ORDER BY id"
        ).fetchall()
    return [
        Organization(id=r[0], name=r[1], owner_email=r[2], created_at=r[3]) for r in rows
    ]


def update_site(
    storage: Storage,
    *,
    site_id: int,
    organization_id: int | None = None,
    **fields,
) -> Site:
    """Обновляет сайт. organization_id можно сменить — сработает каскад.

    Передаваемые поля filter: email, telegram_chat, schedule, interval_days,
    auth_kind, auth_login, auth_password, auth_login_url.
    """
    allowed = {
        "email",
        "telegram_chat",
        "schedule",
        "interval_days",
        "auth_kind",
        "auth_login",
        "auth_password",
        "auth_login_url",
    }
    updates = {key: value for key, value in fields.items() if key in allowed}

    if organization_id is not None:
        updates["organization_id"] = organization_id

    if "auth_password" in updates:
        updates["auth_password"] = _seal(updates["auth_password"])

    if not updates:
        # Ничего не меняем, но возвращаем текущий сайт
        site = storage.get_site(site_id)
        if site is None:
            raise ValueError("Site not found")
        return site

    set_clause = ", ".join(f"{key} = ?" for key in updates)
    with storage._conn() as conn:
        conn.execute(
            f"UPDATE sites SET {set_clause} WHERE id = ?",
            (*updates.values(), site_id),
        )
        conn.commit()

    site = storage.get_site(site_id)
    if site is None:
        raise ValueError("Site not found after update")
    return site


def delete_site(
    storage: Storage,
    *,
    site_id: int,
) -> bool:
    """Удаляет сайт вместе с прогонами и находками (каскад по FK)."""
    with storage._conn() as connection:
        cursor = connection.execute("DELETE FROM sites WHERE id = ?", (site_id,))
        connection.commit()
        return cursor.rowcount > 0


def ensure_default_organization(storage) -> Organization:
    """Создаёт дефолтную организацию и привязывает к ней сайты с org_id=0 или NULL."""
    with storage._conn() as conn:
        # Проверяем, есть ли уже организация
        org = conn.execute("SELECT id, name, owner_email, created_at FROM organizations LIMIT 1").fetchone()
        if org:
            return Organization(id=org[0], name=org[1], owner_email=org[2], created_at=org[3])
        
        # Создаём дефолтную организацию
        from datetime import UTC, datetime
        now = datetime.now(UTC).isoformat()
        cursor = conn.execute(
            "INSERT INTO organizations (name, owner_email, created_at) VALUES (?, ?, ?)",
            ("Default", "", now)
        )
        org_id = cursor.lastrowid
        
        # Привязываем сайты с org_id=0 или NULL
        conn.execute(
            "UPDATE sites SET organization_id = ? WHERE organization_id IS NULL OR organization_id = 0",
            (org_id,)
        )
        conn.commit()
        
        return Organization(id=org_id, name="Default", owner_email="", created_at=now)


def migrate_add_organization_id(storage) -> None:
    """Добавляет колонку organization_id в существующую БД sites.

    Выполняется один раз при обновлении до версии, поддерживающей мультиарендность.
    Значения по умолчанию устанавливаются в 0 (общий пул).
    """
    with storage._conn() as conn:
        # Проверяем, колонка уже есть
        col = conn.execute(
            "PRAGMA table_info(sites)"
        ).fetchall()
        col_names = [c[1] for c in col]
        if "organization_id" not in col_names:
            conn.execute(
                "ALTER TABLE sites ADD COLUMN organization_id INTEGER NOT NULL DEFAULT 0"
            )
            conn.commit()