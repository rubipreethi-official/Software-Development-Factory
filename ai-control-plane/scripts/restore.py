"""
restore.py — Database Restore Utility
=======================================
Task: DEP-04
Restores database from a backup file.

Usage:
    python scripts/restore.py --list                         # List backups
    python scripts/restore.py --file backups/backup_xxx.db   # Restore specific backup
    python scripts/restore.py --latest                       # Restore most recent
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

BACKUP_DIR = Path(__file__).parent.parent / "backups"


def get_database_url() -> str:
    """Get database URL from environment or .env file."""
    import os
    url = os.environ.get("DATABASE_URL")
    if url:
        return url

    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip()

    return "sqlite+aiosqlite:///./data/control_plane.db"


def list_backups():
    """List available backups."""
    if not BACKUP_DIR.exists():
        print("No backups directory found.")
        return []

    backups = sorted(
        [f for f in BACKUP_DIR.iterdir() if f.is_file() and f.name.startswith("backup_")],
        reverse=True,
    )

    if not backups:
        print("No backups found.")
        return []

    print(f"\n{'#':<4} {'Backup File':<40} {'Size':>10}")
    print("─" * 58)
    for i, f in enumerate(backups, 1):
        size_mb = f.stat().st_size / (1024 * 1024)
        print(f"{i:<4} {f.name:<40} {size_mb:>8.2f} MB")

    return backups


def restore_sqlite(backup_path: Path, db_path: str):
    """Restore SQLite database from backup."""
    target = Path(db_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists():
        # Create a safety copy
        safety = target.with_suffix(".db.pre-restore")
        shutil.copy2(target, safety)
        print(f"[SAFETY] Existing DB saved to: {safety}")

    shutil.copy2(backup_path, target)
    print(f"[OK] Database restored from: {backup_path}")


def restore_postgresql(backup_path: Path, url: str):
    """Restore PostgreSQL database from pg_dump backup."""
    parsed = urlparse(url.replace("+asyncpg", ""))
    db_name = parsed.path.lstrip("/")
    env = {"PGPASSWORD": parsed.password or ""}

    cmd = [
        "pg_restore",
        "-h", parsed.hostname or "localhost",
        "-p", str(parsed.port or 5432),
        "-U", parsed.username or "postgres",
        "-d", db_name,
        "--clean",
        "--if-exists",
        str(backup_path),
    ]

    try:
        import os
        full_env = {**os.environ, **env}
        subprocess.run(cmd, check=True, env=full_env, capture_output=True)
        print(f"[OK] PostgreSQL restored from: {backup_path}")
    except FileNotFoundError:
        print("[ERROR] pg_restore not found. Install PostgreSQL client tools.")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] pg_restore failed: {e.stderr.decode()}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="AI Control Plane — Database Restore")
    parser.add_argument("--file", type=str, help="Path to backup file to restore")
    parser.add_argument("--latest", action="store_true", help="Restore the most recent backup")
    parser.add_argument("--list", action="store_true", help="List available backups")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    if args.list:
        list_backups()
        return

    # Determine backup file
    backup_path = None
    if args.file:
        backup_path = Path(args.file)
    elif args.latest:
        backups = sorted(
            [f for f in BACKUP_DIR.iterdir() if f.is_file() and f.name.startswith("backup_")]
            if BACKUP_DIR.exists() else [],
            reverse=True,
        )
        if not backups:
            print("[ERROR] No backups found.")
            sys.exit(1)
        backup_path = backups[0]
    else:
        print("Specify --file <path> or --latest. Use --list to see available backups.")
        sys.exit(1)

    if not backup_path.exists():
        print(f"[ERROR] Backup file not found: {backup_path}")
        sys.exit(1)

    # Confirmation
    if not args.yes:
        print(f"\n⚠️  This will OVERWRITE the current database with: {backup_path.name}")
        response = input("Continue? [y/N]: ").strip().lower()
        if response != "y":
            print("Aborted.")
            return

    url = get_database_url()
    print(f"\nRestoring to: {url.split('@')[-1] if '@' in url else url}")

    if "sqlite" in url:
        db_path = url.split("///")[-1]
        restore_sqlite(backup_path, db_path)
    elif "postgresql" in url or "postgres" in url:
        restore_postgresql(backup_path, url)
    else:
        print(f"[ERROR] Unsupported database: {url}")
        sys.exit(1)

    print("[DONE] Restore complete. Restart the application to use the restored data.")


if __name__ == "__main__":
    main()
