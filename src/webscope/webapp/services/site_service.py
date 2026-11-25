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

    def __init__(self, id: int, name: str, owner_email: str, created_at: str, owner_id: int = 0):
        self.id = id
        self.name = name
        self.owner_email = owner_email
        self.created_at = created_at
        self.owner_id = owner_id


def create_organization(
    storage: Storage,
    *,
    name: str,
    owner_email: str,
    owner_id: int = 0,
) -> Organization:
    """Создаёт организацию и возвращает объект."""
    with storage._conn() as conn:
        cursor = conn.execute(
            "INSERT INTO organizations (name, owner_email, owner_id, created_at) VALUES (?, ?, ?, ?)",
            (name, owner_email, owner_id, now_iso()),
        )
        conn.commit()
        org_id = cursor.lastrowid
    return Organization(id=org_id, name=name, owner_email=owner_email, created_at=now_iso(), owner_id=owner_id)


def get_organization(storage: Storage, org_id: int, owner_id: int | None = None) -> Organization | None:
    """Получает организацию по ID (опционально — только свою)."""
    query = "SELECT id, name, owner_email, created_at, owner_id FROM organizations WHERE id = ?"
    params: tuple = (org_id,)
    if owner_id is not None:
        query += " AND owner_id = ?"
        params += (owner_id,)
    with storage._conn() as conn:
        row = conn.execute(query, params).fetchone()
    if row is None:
        return None
    return Organization(
        id=row[0],
        name=row[1],
        owner_email=row[2],
        created_at=row[3],
        owner_id=row[4],
    )


def create_site(
    storage: Storage,
    *,
    url: str,
    organization_id: int,
    owner_id: int = 0,
    email: str | None = None,
    telegram_chat: str | None = None,
    schedule: str = "off",
    interval_days: int = 7,
    auth_kind: str | None = None,
    auth_login: str | None = None,
    auth_password: str | None = None,
    auth_login_url: str | None = None,
    watchdog_enabled: bool = False,
    watchdog_triggers: list[str] | None = None,
    watchdog_webhook_secret: str | None = None,
) -> Site:
    """Создаёт сайт, привязанный к организации и владельцу.

    URL уникален в базе, поэтому сайт, добавленный другим аккаунтом, не
    переиспользуется: это отдельный кабинет, а не общий список.
    """
    # Гарантируем, что организация существует и принадлежит этому же владельцу
    org = get_organization(storage, organization_id, owner_id=owner_id)
    if org is None:
        raise ValueError(f"Organization with id={organization_id} does not exist")

    # Проверяем, не существует ли сайт с таким URL уже
    existing = storage.get_site_by_url(url)
    if existing is not None:
        # Публичный сервис: человек кинул ссылку — сайт видим. Несколько
        # аккаунтов могут отслеживать один URL; владелец (owner_id) остаётся
        # первым, а остальные попадают в список видимых в их кабинете.
        existing_site = existing
        # Сайт из «доавторизационной» эпохи забирает текущий владелец.
        if existing_site.owner_id == 0 and owner_id:
            storage.update_site(existing_site.id, owner_id=owner_id)
        # Если переданы новые авторизационные данные — обновляем их
        if auth_kind is not None:
            storage.update_site(
                existing_site.id,
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
        owner_id=owner_id,
        watchdog_enabled=watchdog_enabled,
        watchdog_triggers=watchdog_triggers or ["webhook", "content_hash"],
        watchdog_webhook_secret=watchdog_webhook_secret,
    )

    with storage._conn() as conn:
        conn.execute(
            """INSERT INTO sites 
               (url, email, telegram_chat, schedule, interval_days, 
                auth_kind, auth_login, auth_password, auth_login_url, 
                organization_id, owner_id, created_at,
                watchdog_enabled, watchdog_triggers, watchdog_webhook_secret)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                owner_id,
                now_iso(),
                1 if watchdog_enabled else 0,
                ",".join(watchdog_triggers) if watchdog_triggers else "webhook,content_hash",
                watchdog_webhook_secret,
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
    owner_id: int | None = None,
) -> list[Site]:
    """Список сайтов: опционально по организации. Публичная модель — сайты видны всем."""
    query = "SELECT * FROM sites"
    where: list[str] = []
    params: list = []
    if organization_id is not None:
        where.append("organization_id = ?")
        params.append(organization_id)
    if where:
        query += " WHERE " + " AND ".join(where)
    query += " ORDER BY id"
    with storage._conn() as connection:
        rows = connection.execute(query, params).fetchall()
    return [_site_from_row(row) for row in rows]


def get_organizations(storage: Storage, owner_id: int | None = None) -> list[Organization]:
    """Организации для UI-селектора (только свои, если задан owner_id)."""
    query = "SELECT id, name, owner_email, created_at, owner_id FROM organizations"
    params: tuple = ()
    if owner_id is not None:
        query += " WHERE owner_id = ?"
        params = (owner_id,)
    query += " ORDER BY id"
    with storage._conn() as connection:
        rows = connection.execute(query, params).fetchall()
    return [Organization(id=r[0], name=r[1], owner_email=r[2], created_at=r[3], owner_id=r[4]) for r in rows]


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
        "owner_id",
        "auth_kind",
        "auth_login",
        "auth_password",
        "auth_login_url",
        "watchdog_enabled",
        "watchdog_triggers",
        "watchdog_webhook_secret",
    }
    updates = {key: value for key, value in fields.items() if key in allowed}

    if "watchdog_triggers" in updates and isinstance(updates["watchdog_triggers"], list):
        updates["watchdog_triggers"] = ",".join(updates["watchdog_triggers"])

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
            ("Default", "", now),
        )
        org_id = cursor.lastrowid

        # Привязываем сайты с org_id=0 или NULL
        conn.execute(
            "UPDATE sites SET organization_id = ? WHERE organization_id IS NULL OR organization_id = 0",
            (org_id,),
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
            "PRAGMA table_info(sites)",
        ).fetchall()
        col_names = [c[1] for c in col]
        if "organization_id" not in col_names:
            conn.execute(
                "ALTER TABLE sites ADD COLUMN organization_id INTEGER NOT NULL DEFAULT 0",
            )
            conn.commit()
