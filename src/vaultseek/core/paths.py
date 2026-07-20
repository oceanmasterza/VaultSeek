"""Platform-specific application data directory resolution.

VaultSeek stores its configuration, logs, cache, and database under a
single per-user application data directory. On Windows — the primary
target platform — this is ``%APPDATA%/VaultSeek``. Other platforms fall
back to conventional per-user data locations so the application (and its
test suite) remain portable.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

_APP_NAME = "VaultSeek"


@dataclass(frozen=True)
class AppPaths:
    """Resolved filesystem locations for all application data.

    Every attribute is a location the application *will* use, not a
    guarantee that it already exists. Call :meth:`ensure_created` once
    during startup to create the directory tree before anything (config,
    logging) tries to write into it.
    """

    root: Path
    config_file: Path
    secrets_file: Path
    database_file: Path
    logs_dir: Path
    crashes_dir: Path
    cache_dir: Path
    backups_dir: Path
    rollback_dir: Path
    reports_dir: Path

    def ensure_created(self) -> None:
        """Create every directory required for the application to run."""
        for directory in (
            self.root,
            self.logs_dir,
            self.crashes_dir,
            self.cache_dir,
            self.backups_dir,
            self.rollback_dir,
            self.reports_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


def _resolve_base_dir() -> Path:
    """Return the per-user application data root for the current platform."""
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata)
        return Path.home() / "AppData" / "Roaming"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home)
    return Path.home() / ".local" / "share"


def get_app_paths(*, base_override: Path | None = None) -> AppPaths:
    """Build an :class:`AppPaths` instance.

    Args:
        base_override: When provided, used instead of the platform-specific
            base directory. Tests pass a temporary directory here to stay
            isolated from the real user profile.
    """
    base = base_override if base_override is not None else _resolve_base_dir()
    root = base / _APP_NAME
    logs_dir = root / "logs"
    return AppPaths(
        root=root,
        config_file=root / "config.json",
        secrets_file=root / "secrets.json",
        database_file=root / "vaultseek.db",
        logs_dir=logs_dir,
        crashes_dir=logs_dir / "crashes",
        cache_dir=root / "cache",
        backups_dir=root / "backups",
        rollback_dir=root / "rollback",
        reports_dir=root / "reports",
    )
