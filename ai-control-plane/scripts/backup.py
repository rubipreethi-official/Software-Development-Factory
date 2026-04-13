"""
backup.py — Database & Trace Backup Utility
=============================================
Task: DEP-04
Supports SQLite file copy and PostgreSQL pg_dump.

Usage:
    python scripts/backup.py                    # Run backup
    python scripts/backup.py --retain-days 14   # Custom retention
    python scripts/backup.py --list             # List backups
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse

# ── Configuration ────────────────────────────────────────────────────────────────

BACKUP_DIR = Path(__file__).parent.parent / "backups"
DEFAULT_RETAIN_DAYS = 7


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


def backup_sqlite(db_path: str) -> Path:
    """Backup SQLite database by copying the file."""
    source = Path(db_path)
    if not source.exists():
        print(f"[ERROR] Database file not found: {source}")
        sys.exit(1)

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_name = f"backup_{timestamp}.db"
    dest = BACKUP_DIR / backup_name

    shutil.copy2(source, dest)
    size_mb = dest.stat().st_size / (1024 * 1024)
    print(f"[OK] SQLite backup created: {dest} ({size_mb:.2f} MB)")
    return dest


def backup_postgresql(url: str) -> Path:
    """Backup PostgreSQL database using pg_dump."""
    parsed = urlparse(url.replace("+asyncpg", ""))
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_name = f"backup_{timestamp}.sql.gz"
    dest = BACKUP_DIR / backup_name

    db_name = parsed.path.lstrip("/")
    env = {
        "PGPASSWORD": parsed.password or "",
    }

    cmd = [
        "pg_dump",
        "-h", parsed.hostname or "localhost",
        "-p", str(parsed.port or 5432),
        "-U", parsed.username or "postgres",
        "-d", db_name,
        "--format=custom",
        f"--file={dest}",
    ]

    try:
        import os
        full_env = {**os.environ, **env}
        subprocess.run(cmd, check=True, env=full_env, capture_output=True)
        size_mb = dest.stat().st_size / (1024 * 1024)
        print(f"[OK] PostgreSQL backup created: {dest} ({size_mb:.2f} MB)")
    except FileNotFoundError:
        print("[ERROR] pg_dump not found. Install PostgreSQL client tools.")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] pg_dump failed: {e.stderr.decode()}")
        sys.exit(1)

    return dest


def cleanup_old_backups(retain_days: int) -> int:
    """Remove backups older than retain_days."""
    if not BACKUP_DIR.exists():
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=retain_days)
    removed = 0

    for f in BACKUP_DIR.iterdir():
        if f.is_file() and f.name.startswith("backup_"):
            # Parse timestamp from filename
            try:
                ts_str = f.stem.replace("backup_", "").split(".")[0]
                ts = datetime.strptime(ts_str, "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
                if ts < cutoff:
                    f.unlink()
                    print(f"[CLEANUP] Removed old backup: {f.name}")
                    removed += 1
            except ValueError:
                continue

    return removed


def list_backups():
    """List all available backups."""
    if not BACKUP_DIR.exists():
        print("No backups directory found.")
        return

    backups = sorted(BACKUP_DIR.iterdir(), reverse=True)
    backups = [f for f in backups if f.is_file() and f.name.startswith("backup_")]

    if not backups:
        print("No backups found.")
        return

    print(f"\n{'Backup File':<40} {'Size':>10} {'Date'}")
    print("─" * 65)
    for f in backups:
        size_mb = f.stat().st_size / (1024 * 1024)
        mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        print(f"{f.name:<40} {size_mb:>8.2f} MB  {mtime}")

    print(f"\nTotal: {len(backups)} backup(s)")


def main():
    parser = argparse.ArgumentParser(description="AI Control Plane — Database Backup")
    parser.add_argument("--retain-days", type=int, default=DEFAULT_RETAIN_DAYS,
                        help=f"Days to retain backups (default: {DEFAULT_RETAIN_DAYS})")
    parser.add_argument("--list", action="store_true", help="List available backups")
    args = parser.parse_args()

    if args.list:
        list_backups()
        return

    print("=" * 50)
    print(" AI Control Plane — Backup")
    print("=" * 50)

    url = get_database_url()
    print(f"Database: {url.split('@')[-1] if '@' in url else url}")

    if "sqlite" in url:
        # Extract file path from SQLite URL
        db_path = url.split("///")[-1]
        backup_sqlite(db_path)
    elif "postgresql" in url or "postgres" in url:
        backup_postgresql(url)
    else:
        print(f"[ERROR] Unsupported database: {url}")
        sys.exit(1)

    # Cleanup old backups
    removed = cleanup_old_backups(args.retain_days)
    if removed:
        print(f"[CLEANUP] Removed {removed} old backup(s) (>{args.retain_days} days)")

    print("[DONE] Backup complete.")


if __name__ == "__main__":
    main()
