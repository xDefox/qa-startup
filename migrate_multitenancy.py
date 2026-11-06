#!/usr/bin/env python3
"""
Multi-tenancy migration script for WebScope.

Run this once to migrate an existing database to support organizations:
- Adds organization_id column to sites table
- Creates organizations table
- Creates "Default" organization
- Assigns all existing sites to the Default organization

Usage:
    python migrate_multitenancy.py [--db-path /path/to/webscope.db]
"""

import argparse
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path


def migrate(db_path: str) -> None:
    """Run the multi-tenancy migration."""
    db = Path(db_path)
    if not db.exists():
        print(f"Database not found: {db_path}")
        sys.exit(1)

    print(f"Migrating database: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        # 1. Check if organizations table exists
        org_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='organizations'"
        ).fetchone()

        if not org_table:
            print("Creating organizations table...")
            conn.execute("""
                CREATE TABLE organizations (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    name        TEXT NOT NULL,
                    owner_email TEXT NOT NULL,
                    created_at  TEXT NOT NULL
                )
            """)
        else:
            print("organizations table already exists")

        # 2. Check if sites table has organization_id column
        cols = conn.execute("PRAGMA table_info(sites)").fetchall()
        col_names = [c[1] for c in cols]

        if "organization_id" not in col_names:
            print("Adding organization_id column to sites table...")
            conn.execute(
                "ALTER TABLE sites ADD COLUMN organization_id INTEGER NOT NULL DEFAULT 0"
            )
        else:
            print("organization_id column already exists in sites table")

        # 3. Check if Default organization exists
        org = conn.execute(
            "SELECT id, name, owner_email, created_at FROM organizations LIMIT 1"
        ).fetchone()

        if org:
            org_id = org[0]
            print(f"Default organization already exists: id={org_id}, name={org[1]}")
        else:
            print("Creating Default organization...")
            now = datetime.now(UTC).isoformat()
            cursor = conn.execute(
                "INSERT INTO organizations (name, owner_email, created_at) VALUES (?, ?, ?)",
                ("Default", "", now)
            )
            org_id = cursor.lastrowid
            print(f"Created organization: id={org_id}")

        # 4. Update sites with org_id = 0 or NULL to the Default organization
        cursor = conn.execute(
            "SELECT COUNT(*) as cnt FROM sites WHERE organization_id IS NULL OR organization_id = 0"
        )
        count = cursor.fetchone()["cnt"]

        if count > 0:
            print(f"Assigning {count} existing sites to Default organization (id={org_id})...")
            conn.execute(
                "UPDATE sites SET organization_id = ? WHERE organization_id IS NULL OR organization_id = 0",
                (org_id,)
            )
        else:
            print("No sites need reassignment")

        # 5. Verify
        sites_count = conn.execute("SELECT COUNT(*) as cnt FROM sites").fetchone()["cnt"]
        orgs_count = conn.execute("SELECT COUNT(*) as cnt FROM organizations").fetchone()["cnt"]
        unassigned = conn.execute(
            "SELECT COUNT(*) as cnt FROM sites WHERE organization_id IS NULL OR organization_id = 0"
        ).fetchone()["cnt"]

        print(f"\nMigration complete:")
        print(f"  Organizations: {orgs_count}")
        print(f"  Sites: {sites_count}")
        print(f"  Unassigned sites: {unassigned}")

        conn.commit()
        print("SUCCESS: Database migrated successfully")

    except Exception as e:
        conn.rollback()
        print(f"ERROR: Migration failed: {e}")
        sys.exit(1)
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Migrate WebScope DB for multi-tenancy")
    parser.add_argument(
        "--db-path",
        default="webscope.db",
        help="Path to SQLite database (default: webscope.db)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes"
    )
    args = parser.parse_args()

    if args.dry_run:
        print("DRY RUN MODE - no changes will be made")
        # TODO: implement dry run
        return

    migrate(args.db_path)


if __name__ == "__main__":
    main()