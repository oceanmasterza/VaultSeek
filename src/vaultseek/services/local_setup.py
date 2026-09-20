"""Read known local client settings without changing another application's files."""

from __future__ import annotations

import ast
import configparser
import os
import socket
import tomllib
import xml.etree.ElementTree as ET
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

_SECRET_FIELDS = frozenset({"key", "api_token", "password", "token"})
_FIELD_LABELS = {
    "url": "URL",
    "key": "API key",
    "host": "Host",
    "api_port": "API port",
    "api_token": "API token",
    "username": "Username",
    "category": "Category",
    "save_path": "Save path",
}


@dataclass(frozen=True)
class LocalConnection:
    """A suggestion; secrets are deliberately excluded from diagnostic reprs."""

    name: str
    source: Path
    values: dict[str, str] = field(repr=False)
    note: str = "Review these settings, then test and save."
    listening: bool = False

    def field_summary(self) -> str:
        """Describe copyable fields without printing secret values."""
        if not self.values:
            return ""
        parts: list[str] = []
        for name, value in self.values.items():
            label = _FIELD_LABELS.get(name, name)
            if name in _SECRET_FIELDS:
                if value:
                    parts.append(f"{label} found (hidden)")
            elif value:
                parts.append(f"{label}: {value}")
        return " · ".join(parts)


class LocalSetupService:
    """Discover supported Windows configuration files, with bounded reads."""

    def __init__(
        self,
        *,
        roaming: Path | None = None,
        local: Path | None = None,
        program_data: Path | None = None,
        port_probe: Callable[[str, int], bool] | None = None,
    ) -> None:
        self.roaming = roaming or Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
        self.local = local or Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
        self.program_data = program_data or Path(os.environ.get("PROGRAMDATA", "C:/ProgramData"))
        self._port_probe = port_probe or _tcp_open

    def discover(self) -> list[LocalConnection]:
        """Report missing/inaccessible installations without exposing file contents."""
        specs = [
            (
                "Prowlarr",
                (self.program_data / "Prowlarr/config.xml",),
                self._prowlarr,
                9696,
            ),
            (
                "qBittorrent",
                (self.roaming / "qBittorrent/qBittorrent.ini",),
                self._qbit,
                8081,
            ),
            (
                "SABnzbd",
                (
                    self.local / "sabnzbd/sabnzbd.ini",
                    self.roaming / "sabnzbd/sabnzbd.ini",
                ),
                self._sab,
                8080,
            ),
            (
                "Nicotine+",
                (self.roaming / "nicotine/config/config",),
                self._nicotine,
                12339,
            ),
            (
                "Jellyfin",
                (self.program_data / "Jellyfin/Server/config/network.xml",),
                self._jellyfin,
                8096,
            ),
            (
                "Navidrome",
                (
                    self.program_data / "Navidrome/navidrome.toml",
                    self.roaming / "navidrome/navidrome.toml",
                ),
                self._navidrome,
                4533,
            ),
            (
                "Plex",
                (self.local / "Plex Media Server/Preferences.xml",),
                self._plex,
                32400,
            ),
            (
                "Emby",
                (
                    self.program_data / "Emby-Server/config/system.xml",
                    self.roaming / "Emby-Server/config/system.xml",
                ),
                self._emby,
                8096,
            ),
            (
                "NZBGet",
                (self.program_data / "NZBGet/nzbget.conf",),
                self._nzbget,
                6789,
            ),
        ]
        parsed = [
            (self._read_first(name, paths, reader), port) for name, paths, reader, port in specs
        ]
        return self._apply_listening(parsed)

    def _read_first(
        self,
        name: str,
        paths: tuple[Path, ...],
        reader: Callable[[str], tuple[dict[str, str], str]],
    ) -> LocalConnection:
        last_unreadable: Path | None = None
        for path in paths:
            try:
                if path.stat().st_size > 2_000_000:
                    raise ValueError("Configuration is too large")
                values, note = reader(path.read_text(encoding="utf-8-sig"))
                return LocalConnection(name, path, values, note, False)
            except FileNotFoundError:
                continue
            except (OSError, ValueError, SyntaxError, KeyError, configparser.Error, ET.ParseError):
                last_unreadable = path
                continue
        source = last_unreadable or paths[0]
        if last_unreadable is not None:
            note = (
                "Configuration could not be read. "
                "Use manual setup; existing settings are unchanged."
            )
        else:
            note = (
                "No standard local configuration found. "
                "Use manual setup for portable or remote installs."
            )
        return LocalConnection(name, source, {}, note, False)

    def _apply_listening(self, rows: list[tuple[LocalConnection, int]]) -> list[LocalConnection]:
        targets = [self._listen_target(item.values, default_port) for item, default_port in rows]
        unique = list(dict.fromkeys(targets))
        found: dict[tuple[str, int], bool] = {}
        workers = min(8, max(1, len(unique)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(self._port_probe, host, port): (host, port) for host, port in unique
            }
            for future in as_completed(futures):
                host, port = futures[future]
                try:
                    found[(host, port)] = bool(future.result())
                except (OSError, ValueError, TypeError, RuntimeError):
                    found[(host, port)] = False
        out: list[LocalConnection] = []
        for (item, default_port), target in zip(rows, targets, strict=True):
            listening = found.get(target, False)
            note = item.note
            if listening:
                if item.values:
                    note = f"{note} A service is listening on this PC."
                else:
                    note += (
                        f" Port {target[1] if target[1] else default_port} is open "
                        "on this PC — enter URL and credentials manually."
                    )
            out.append(LocalConnection(item.name, item.source, item.values, note, listening))
        return out

    @staticmethod
    def _listen_target(values: dict[str, str], default_port: int) -> tuple[str, int]:
        url = values.get("url") or ""
        port = default_port
        host = "127.0.0.1"
        if "://" in url:
            rest = url.split("://", 1)[1]
            hostport = rest.split("/", 1)[0]
            if ":" in hostport:
                host, _, raw_port = hostport.rpartition(":")
                parsed = _parse_port(raw_port)
                port = parsed if parsed is not None else default_port
            else:
                host = hostport or host
        api_port = values.get("api_port")
        parsed_api = _parse_port(api_port) if api_port else None
        if parsed_api is not None:
            port = parsed_api
            host = values.get("host") or host
        if host in ("0.0.0.0", "::", ""):
            host = "127.0.0.1"
        return host, port

    @staticmethod
    def _ini(text: str) -> configparser.ConfigParser:
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.read_string(text)
        return parser

    @staticmethod
    def _url(port: str, https: bool = False, base: str = "") -> str:
        number = int(port)
        if not 1 <= number <= 65535:
            raise ValueError("Invalid port")
        prefix = base.strip().strip("/")
        if any(c in prefix for c in ("?", "#", "\\", "@")):
            raise ValueError("Invalid URL base")
        return f"{'https' if https else 'http'}://127.0.0.1:{number}" + (
            f"/{prefix}" if prefix else ""
        )

    def _prowlarr(self, text: str) -> tuple[dict[str, str], str]:
        root = ET.fromstring(text)
        https = root.findtext("EnableSsl", "false").lower() == "true"
        url = self._url(
            root.findtext("SslPort" if https else "Port", "9696"),
            https,
            root.findtext("UrlBase", ""),
        )
        return {
            "url": url,
            "key": root.findtext("ApiKey", ""),
        }, "Local URL and API key found. Test before enabling search."

    def _qbit(self, text: str) -> tuple[dict[str, str], str]:
        parser = self._ini(text)
        prefs = parser["Preferences"]
        if prefs.get("WebUI\\Enabled", "false").lower() != "true":
            return {}, "Enable Tools → Options → Web UI in qBittorrent, then detect again."
        url = self._url(
            prefs.get("WebUI\\Port", "8080"),
            prefs.get("WebUI\\HTTPS\\Enabled", "false").lower() == "true",
        )
        values = {
            "url": url,
            "username": prefs.get("WebUI\\Username", "admin"),
        }
        save_path = prefs.get("Downloads\\SavePath", "").strip()
        if not save_path and parser.has_section("BitTorrent"):
            save_path = parser["BitTorrent"].get("Session\\DefaultSavePath", "").strip()
        if save_path:
            values["save_path"] = save_path
        return values, (
            "Enter the Web UI password manually; stored password hashes cannot be imported."
        )

    def _sab(self, text: str) -> tuple[dict[str, str], str]:
        # SAB uses ConfigObj: global keys may precede sections, and category
        # sections nest. Read only misc rather than interpreting the whole file.
        lines = text.splitlines()
        start = next((i for i, line in enumerate(lines) if line.strip() == "[misc]"), None)
        if start is None:
            raise ValueError("SAB misc section missing")
        end = next(
            (i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")),
            len(lines),
        )
        prefs = self._ini("\n".join(lines[start:end]))["misc"]
        https = prefs.get("enable_https", "0").strip('"') == "1"
        port = prefs.get("https_port" if https else "port", "8080").strip('"')
        url = self._url(port, https, prefs.get("url_base", "").strip('"'))
        values = {"url": url, "key": prefs.get("api_key", "").strip('"')}
        if "[[vaultseek]]" in text.lower():
            values["category"] = "vaultseek"
        return values, ("Local URL and full API key found. Test before enabling downloads.")

    def _nicotine(self, text: str) -> tuple[dict[str, str], str]:
        plugins = self._ini(text)["plugins"]
        enabled = ast.literal_eval(plugins.get("enabled", "[]"))
        if not isinstance(enabled, list):
            raise ValueError("Unexpected plugin list")
        for plugin_id in ("api-nicotine-plus", "api-nicotine-plus-main", "api_nicotine_plus"):
            if plugin_id not in enabled or plugin_id not in plugins:
                continue
            settings = ast.literal_eval(plugins[plugin_id])
            if not isinstance(settings, dict):
                raise ValueError("Unexpected plugin settings")
            port = str(settings.get("port", 12339))
            self._url(port)
            host = str(settings.get("host", "127.0.0.1"))
            if host in ("0.0.0.0", "::", ""):
                host = "127.0.0.1"
            return {
                "host": host,
                "api_port": port,
                "api_token": str(settings.get("api_token", "")),
            }, ("Enabled HTTP plugin settings found. Test to confirm Soulseek/API availability.")
        return {}, "Enable api-nicotine-plus in Nicotine's Plugins settings, then detect again."

    def _jellyfin(self, text: str) -> tuple[dict[str, str], str]:
        root = ET.fromstring(text)
        https = root.findtext("RequireHttps", "false").lower() == "true"
        url = self._url(
            root.findtext("InternalHttpsPort" if https else "InternalHttpPort", "8096"),
            https,
            root.findtext("BaseUrl", ""),
        )
        return {"url": url}, "Create a VaultSeek API key in Jellyfin Dashboard → API Keys."

    def _navidrome(self, text: str) -> tuple[dict[str, str], str]:
        data = tomllib.loads(text)
        port = str(data.get("Port") or data.get("port") or 4533)
        address = str(data.get("Address") or data.get("address") or "127.0.0.1")
        if address in ("0.0.0.0", "::", ""):
            address = "127.0.0.1"
        url = self._url(port)
        if address not in ("127.0.0.1", "localhost"):
            url = url.replace("127.0.0.1", address, 1)
        return {"url": url}, "Enter Navidrome username/password. Optional DB path is local-only."

    def _plex(self, text: str) -> tuple[dict[str, str], str]:
        # Preferences.xml is a single-element dump; the HTTP port is usually 32400.
        if "<" not in text:
            raise ValueError("Unexpected Plex preferences")
        return {
            "url": "http://127.0.0.1:32400"
        }, "Paste a Plex token (account → XML → X-Plex-Token). This form does not import it."

    def _emby(self, text: str) -> tuple[dict[str, str], str]:
        root = ET.fromstring(text)
        https = root.findtext("EnableHttps", "false").lower() == "true"
        port = root.findtext("PublicHttpsPort" if https else "PublicPort", "8096")
        return {"url": self._url(port, https)}, "Create an API key in Emby Dashboard → API Keys."

    def _nzbget(self, text: str) -> tuple[dict[str, str], str]:
        # nzbget.conf is key=value. Read control credentials only; do not write the file.
        pairs: dict[str, str] = {}
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith(";"):
                continue
            if "=" not in stripped:
                continue
            key, _, raw = stripped.partition("=")
            pairs[key.strip()] = raw.strip().strip('"')
        secure = pairs.get("SecureControl", "no").casefold() in {"yes", "true", "1"}
        port = pairs.get("SecurePort", "6791") if secure else pairs.get("ControlPort", "6789")
        url = self._url(port, secure)
        host = pairs.get("ControlIP", "127.0.0.1")
        if host not in {"0.0.0.0", "::", "*", ""}:
            url = url.replace("127.0.0.1", host, 1)
        values = {
            "url": url,
            "username": pairs.get("ControlUsername", ""),
            "password": pairs.get("ControlPassword", ""),
        }
        for key, value in pairs.items():
            if key.casefold().endswith(".name") and value.casefold() == "vaultseek":
                values["category"] = "vaultseek"
                break
        if values["password"]:
            note = (
                "Control URL and password found. Review them, then test. "
                "An add-only login cannot report queue progress. "
                "VaultSeek does not change NZBGet."
            )
        else:
            note = (
                "Control URL found. Enter the control password manually. "
                "An add-only login cannot report queue progress."
            )
        return values, note


def _parse_port(raw: str) -> int | None:
    try:
        value = int(raw)
    except ValueError:
        return None
    if not 1 <= value <= 65535:
        return None
    return value


def _tcp_open(host: str, port: int) -> bool:
    if not 1 <= port <= 65535:
        return False
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False
