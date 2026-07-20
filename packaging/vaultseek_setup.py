"""VaultSeek offline installer / uninstaller (Windows).

Built into ``VaultSeek-Setup.exe`` by ``packaging/build_setup_exe.py``.
After install, a copy is also placed at ``{app}\\Uninstall.exe`` and
registered under Apps & Features (ARP).

Modes:
  (default)           Interactive install
  --yes / -y / /S     Silent install (no launch)
  --uninstall         Interactive uninstall
  --uninstall --yes   Silent uninstall (keeps user data)
  --uninstall --purge Silent uninstall and delete AppData
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import traceback
import winreg
import zipfile
from datetime import datetime
from pathlib import Path

APP_NAME = "VaultSeek"
APP_VERSION = "1.0.0"
PUBLISHER = "VaultSeek"
PAYLOAD = "VaultSeekApp.zip"
# Per-user ARP key (no elevation required for LocalAppData installs).
ARP_KEY = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_NAME}"

_LOG: Path | None = None


def _payload_path() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / PAYLOAD


def _default_install_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / "Programs" / APP_NAME


def _user_data_dir() -> Path:
    roaming = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(roaming) / APP_NAME


def _start_menu_dir() -> Path:
    roaming = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(roaming) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / APP_NAME


def _desktop_dir() -> Path:
    return Path.home() / "Desktop"


def _log_path() -> Path:
    temp = os.environ.get("TEMP") or os.environ.get("TMP") or str(Path.home())
    return Path(temp) / "VaultSeek-Setup.log"


def _wants_uninstall() -> bool:
    return any(a.lower() in {"--uninstall", "/uninstall", "-u"} for a in sys.argv[1:])


def _wants_purge() -> bool:
    return any(a.lower() in {"--purge", "/purge"} for a in sys.argv[1:])


def _auto() -> bool:
    if any(a in {"--yes", "-y", "/S", "/s", "/silent"} for a in sys.argv[1:]):
        return True
    return os.environ.get("VAULTSEEK_SETUP_AUTO", "").strip().lower() in {"1", "true", "yes"}


def _open_log() -> Path:
    global _LOG
    path = _log_path()
    mode = "uninstall" if _wants_uninstall() else "install"
    path.write_text(
        f"VaultSeek Setup log ({mode}) — {datetime.now().isoformat(timespec='seconds')}\n"
        f"argv={sys.argv!r}\n"
        f"executable={sys.executable!r}\n"
        f"meipass={getattr(sys, '_MEIPASS', None)!r}\n\n",
        encoding="utf-8",
    )
    _LOG = path
    return path


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    if _LOG is not None:
        with _LOG.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def _message(title: str, text: str, *, error: bool = False) -> None:
    log(f"MSGBOX {'ERROR' if error else 'INFO'}: {title} — {text.replace(chr(10), ' | ')}")
    if _auto():
        return
    flags = 0x10 if error else 0x40
    try:
        ctypes.windll.user32.MessageBoxW(None, text, title, flags)
    except Exception as exc:
        log(f"MessageBox failed: {exc}")


def _ask_yes_no(title: str, text: str, *, default_yes: bool = True) -> bool:
    log(f"ASK: {title} — {text.replace(chr(10), ' | ')}")
    if _auto():
        log(f"AUTO: answering {'YES' if default_yes else 'NO'}")
        return default_yes
    flags = 0x24  # MB_YESNO | MB_ICONQUESTION
    if not default_yes:
        flags |= 0x100  # MB_DEFBUTTON2
    try:
        choice = ctypes.windll.user32.MessageBoxW(None, text, title, flags)
        return choice == 6
    except Exception as exc:
        log(f"MessageBox failed: {exc}; defaulting to {'YES' if default_yes else 'NO'}")
        return default_yes


def _create_shortcut(
    link_path: Path,
    target: Path,
    workdir: Path,
    *,
    description: str = APP_NAME,
    arguments: str = "",
) -> None:
    link_path.parent.mkdir(parents=True, exist_ok=True)
    # Escape for PowerShell double-quoted strings.
    def _ps(s: str) -> str:
        return s.replace("`", "``").replace('"', '`"')

    ps = (
        f'$ws = New-Object -ComObject WScript.Shell; '
        f'$s = $ws.CreateShortcut("{_ps(str(link_path))}"); '
        f'$s.TargetPath = "{_ps(str(target))}"; '
        f'$s.WorkingDirectory = "{_ps(str(workdir))}"; '
        f'$s.Description = "{_ps(description)}"; '
    )
    if arguments:
        ps += f'$s.Arguments = "{_ps(arguments)}"; '
    ps += "$s.Save()"
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log(f"Shortcut warning ({link_path.name}): rc={result.returncode} {result.stderr.strip()}")
    else:
        log(f"Created shortcut: {link_path}")


def _remove_path(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    try:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
        log(f"Removed: {path}")
    except OSError as exc:
        log(f"Could not remove {path}: {exc}")


def _dir_size_kb(path: Path) -> int:
    total = 0
    if not path.is_dir():
        return 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                continue
    return max(1, total // 1024)


def _write_arp(install_dir: Path, uninstall_exe: Path) -> None:
    """Register with Windows Apps & Features (per-user)."""
    estimated = _dir_size_kb(install_dir)
    display_icon = str(install_dir / "VaultSeek.exe")
    values: dict[str, object] = {
        "DisplayName": APP_NAME,
        "DisplayVersion": APP_VERSION,
        "Publisher": PUBLISHER,
        "InstallLocation": str(install_dir),
        "DisplayIcon": display_icon,
        "UninstallString": f'"{uninstall_exe}" --uninstall',
        "QuietUninstallString": f'"{uninstall_exe}" --uninstall --yes',
        "EstimatedSize": estimated,  # DWORD, KiB
        "NoModify": 1,
        "NoRepair": 1,
        "VersionMajor": 1,
        "VersionMinor": 0,
    }
    key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, ARP_KEY, 0, winreg.KEY_WRITE)
    try:
        for name, value in values.items():
            if isinstance(value, int):
                winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)
            else:
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(value))
    finally:
        winreg.CloseKey(key)
    log(f"Registered Apps & Features entry: HKCU\\{ARP_KEY}")


def _remove_arp() -> None:
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, ARP_KEY)
        log(f"Removed Apps & Features entry: HKCU\\{ARP_KEY}")
    except FileNotFoundError:
        log("Apps & Features entry already absent")
    except OSError as exc:
        log(f"Could not remove ARP key: {exc}")


def _stop_running_app() -> None:
    """Best-effort stop of running VaultSeek.exe before file delete."""
    if sys.platform != "win32":
        return
    result = subprocess.run(
        ["taskkill", "/IM", "VaultSeek.exe", "/F"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        log("Stopped running VaultSeek.exe")
    else:
        log("No running VaultSeek.exe (or could not stop)")


def _extract_with_progress(payload: Path, install_dir: Path) -> None:
    with zipfile.ZipFile(payload, "r") as zf:
        members = zf.infolist()
        total = len(members)
        log(f"Extracting {total} files to {install_dir} …")
        for index, info in enumerate(members, start=1):
            zf.extract(info, install_dir)
            if index == 1 or index == total or index % 100 == 0:
                pct = (index * 100) // total if total else 100
                log(f"  progress {index}/{total} ({pct}%) — {info.filename}")
    log("Extraction complete.")


def _install_uninstall_helper(install_dir: Path) -> Path:
    """Copy this Setup binary into the app folder as Uninstall.exe."""
    dest = install_dir / "Uninstall.exe"
    src = Path(sys.executable).resolve()
    # When running as a frozen one-file, sys.executable is VaultSeek-Setup.exe.
    shutil.copy2(src, dest)
    log(f"Installed uninstaller: {dest}")
    return dest


def do_install() -> int:
    log_file = _open_log()
    print("=" * 60, flush=True)
    print(f"  {APP_NAME} Setup {APP_VERSION}", flush=True)
    print("=" * 60, flush=True)
    log(f"Log file: {log_file}")
    log("Starting installer (first launch of a one-file exe can take a minute while it unpacks).")

    payload = _payload_path()
    log(f"Payload path: {payload}")
    if not payload.is_file():
        _message(
            f"{APP_NAME} Setup",
            f"Installer payload missing:\n{payload}\n\nLog: {log_file}",
            error=True,
        )
        return 1
    size_mb = payload.stat().st_size / (1024 * 1024)
    log(f"Payload size: {size_mb:.1f} MiB")

    install_dir = _default_install_dir()
    log(f"Install directory: {install_dir}")

    if not _ask_yes_no(
        f"{APP_NAME} Setup",
        f"Install {APP_NAME} {APP_VERSION} to:\n{install_dir}\n\n"
        f"This copies ~{size_mb:.0f} MiB of bundled files (Python, Qt, fpcalc, …).\n\n"
        f"Continue?\n\n(Progress is shown in the console window.)",
    ):
        log("User cancelled.")
        return 0

    _stop_running_app()
    if install_dir.exists():
        log("Removing previous install…")
        shutil.rmtree(install_dir, ignore_errors=True)
    install_dir.mkdir(parents=True, exist_ok=True)

    _extract_with_progress(payload, install_dir)

    exe = install_dir / "VaultSeek.exe"
    fpcalc = install_dir / "_internal" / "fpcalc.exe"
    if not fpcalc.is_file():
        fpcalc = install_dir / "fpcalc.exe"
    log(f"VaultSeek.exe present: {exe.is_file()}")
    log(f"fpcalc present: {fpcalc.is_file()} ({fpcalc})")
    if not exe.is_file():
        _message(
            f"{APP_NAME} Setup",
            f"Install finished but VaultSeek.exe is missing.\n\nLog: {log_file}",
            error=True,
        )
        return 1

    uninstall_exe = _install_uninstall_helper(install_dir)
    _write_arp(install_dir, uninstall_exe)

    start_menu = _start_menu_dir()
    _create_shortcut(start_menu / f"{APP_NAME}.lnk", exe, install_dir)
    _create_shortcut(
        start_menu / f"Uninstall {APP_NAME}.lnk",
        uninstall_exe,
        install_dir,
        description=f"Uninstall {APP_NAME}",
        arguments="--uninstall",
    )

    desktop = _desktop_dir()
    if desktop.is_dir():
        _create_shortcut(desktop / f"{APP_NAME}.lnk", exe, install_dir)

    log("Install succeeded.")
    if _ask_yes_no(
        f"{APP_NAME} Setup",
        f"{APP_NAME} {APP_VERSION} was installed to:\n{install_dir}\n\n"
        f"It appears in Apps & Features, with an Uninstall shortcut in the Start Menu.\n"
        f"Log: {log_file}\n\n"
        f"Launch {APP_NAME} now?\n\n"
        f"(Recommended: click No, then start from the Desktop shortcut.)",
        default_yes=False,
    ):
        log(f"Launching {exe}")
        subprocess.Popen([str(exe)], cwd=str(install_dir))
    else:
        log("User declined launch (or silent install — not launching).")

    if not _auto():
        print("\nDone. You can close this window.", flush=True)
        input("Press Enter to exit…")
    return 0


def do_uninstall() -> int:
    log_file = _open_log()
    print("=" * 60, flush=True)
    print(f"  {APP_NAME} Uninstall {APP_VERSION}", flush=True)
    print("=" * 60, flush=True)
    log(f"Log file: {log_file}")

    install_dir = _default_install_dir()
    data_dir = _user_data_dir()
    log(f"Install directory: {install_dir}")
    log(f"User data directory: {data_dir}")

    if not _ask_yes_no(
        f"Uninstall {APP_NAME}",
        f"Remove {APP_NAME} from this PC?\n\n"
        f"Program files:\n{install_dir}\n\n"
        f"Your library settings and database under:\n{data_dir}\n"
        f"will be kept unless you choose to delete them next.",
        default_yes=True,
    ):
        log("User cancelled uninstall.")
        return 0

    purge = _wants_purge()
    if not purge and data_dir.exists() and not _auto():
        purge = _ask_yes_no(
            f"Uninstall {APP_NAME}",
            f"Also delete user data (settings, database, logs)?\n\n{data_dir}\n\n"
            f"Choose No to keep your library configuration.",
            default_yes=False,
        )

    _stop_running_app()

    # Shortcuts
    _remove_path(_start_menu_dir())
    _remove_path(_desktop_dir() / f"{APP_NAME}.lnk")

    # Program files — schedule delayed delete of Uninstall.exe if we are it
    self_path = Path(sys.executable).resolve()
    install_resolved = install_dir.resolve()
    removing_self = str(self_path).lower().startswith(str(install_resolved).lower() + os.sep) or (
        self_path.parent.resolve() == install_resolved
    )

    if install_dir.exists():
        if removing_self:
            # Delete everything except our running Uninstall.exe, then cmd ping-delay delete.
            for child in install_dir.iterdir():
                if child.resolve() == self_path:
                    continue
                _remove_path(child)
            log("Scheduling removal of Uninstall.exe after exit…")
            subprocess.Popen(
                [
                    "cmd",
                    "/c",
                    f'ping 127.0.0.1 -n 5 >nul & rmdir /s /q "{install_dir}"',
                ],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            _remove_path(install_dir)

    if purge:
        _remove_path(data_dir)
    else:
        log(f"Kept user data: {data_dir}")

    _remove_arp()
    log("Uninstall complete.")
    _message(
        f"Uninstall {APP_NAME}",
        f"{APP_NAME} has been removed."
        + (f"\n\nUser data deleted:\n{data_dir}" if purge else f"\n\nUser data kept:\n{data_dir}"),
    )
    if not _auto():
        print("\nDone. You can close this window.", flush=True)
        input("Press Enter to exit…")
    return 0


def main() -> int:
    try:
        if _wants_uninstall():
            return do_uninstall()
        return do_install()
    except Exception as exc:
        tb = traceback.format_exc()
        log(f"FATAL: {exc}")
        log(tb)
        _message(
            f"{APP_NAME} Setup",
            f"Setup failed:\n{exc}\n\nSee log:\n{_log_path()}",
            error=True,
        )
        if not _auto():
            print("\nSetup failed. Log:", _log_path(), flush=True)
            input("Press Enter to exit…")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
