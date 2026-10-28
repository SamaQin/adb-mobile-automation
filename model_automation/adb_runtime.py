from __future__ import annotations

import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Iterator


ADB_RUNTIME_DIRNAME = ".adb-runtime"
ADB_TEMP_DIRNAME = "temp"
ADB_LOG_FILENAME = "adb.log"


def _usable_directory(path: Path) -> bool:
    """Create ``path`` and prove this process can write a file inside it."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=path, prefix=".write-probe-", delete=True):
            pass
    except OSError:
        return False
    return True


def _runtime_roots(project_root: Path) -> Iterator[Path]:
    # Keep runtime data beside the application so portable copies stay isolated.
    yield Path(project_root) / ADB_RUNTIME_DIRNAME
    # A packaged application may live in a read-only directory; fall back to a
    # per-user location that adb can still use for its log.
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        yield Path(local_app_data) / "ADB-Automation" / ADB_RUNTIME_DIRNAME


def prepare_adb_environment(project_root: Path) -> dict[str, str]:
    """Return an adb process environment with a writable server-log location.

    Windows applies the mandatory integrity label of an executable's file to
    the process. When the application directory is marked low integrity (for
    example after it was provisioned by a sandboxed tool), adb inherits a low
    integrity token and cannot create ``%TEMP%\\adb.log``. The server then dies
    with ``cannot open ...\\adb.log: Permission denied`` and every command
    reports ``cannot connect to daemon``. Pointing adb's log path and temporary
    directory at a location this process can actually write fixes the server
    startup without changing the parent process's global environment.
    """
    for root in _runtime_roots(project_root):
        temp_dir = (root / ADB_TEMP_DIRNAME).resolve()
        if not _usable_directory(temp_dir):
            continue
        environment = os.environ.copy()
        environment["TEMP"] = str(temp_dir)
        environment["TMP"] = str(temp_dir)
        # Supported by current adb versions; the TEMP override above also keeps
        # older adb binaries working when they ignore this variable.
        environment["ANDROID_ADB_LOG_PATH"] = str(temp_dir / ADB_LOG_FILENAME)
        return environment
    # No writable runtime directory: keep the inherited environment so adb's
    # own error is surfaced instead of failing during application startup.
    return os.environ.copy()
