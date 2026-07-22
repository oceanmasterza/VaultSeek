"""Bootstrap helpers for acquisition providers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from loguru import logger

from vaultseek.core.config import AcquisitionConfig
from vaultseek.models.interfaces.acquisition import AcquisitionProviderConfig
from vaultseek.plugins.builtin.nicotine_plus import NicotinePlusProvider
from vaultseek.services.provider_manager import ProviderManager


@dataclass(frozen=True, slots=True)
class NicotineProbeResult:
    ok: bool
    message: str


def normalize_nicotine_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Return Nicotine+ settings safe for connect/probe.

    Users often point the NDJSON port at the HTTP API port (12339) while
    api-nicotine-plus is installed — auto-switch to HTTP in that case.
    """
    normalized = dict(settings)
    transport = str(normalized.get("transport") or "socket").casefold()
    port = int(normalized.get("port") or 22024)
    api_port = int(normalized.get("api_port") or 12339)
    if transport == "socket" and port == api_port:
        normalized["transport"] = "http"
        normalized["port"] = 22024
    return normalized


def resolve_enabled_acquisition_providers(config: AcquisitionConfig) -> set[str]:
    """Enabled provider ids for connect — Nicotine+ replaces the stub placeholder."""
    enabled = set(config.enabled_providers)
    if config.nicotine_plus.enabled:
        enabled.add("nicotine_plus")
        enabled.discard("stub")
    elif not enabled:
        enabled.add("stub")
    return enabled


def probe_nicotine_plus_connection(
    *,
    host: str,
    port: int,
    transport: str,
    api_port: int,
    api_token: str = "",
    timeout_seconds: float = 3.0,
) -> NicotineProbeResult:
    """Probe Nicotine+ reachability using current settings (no persistence)."""
    transport_key = str(transport or "socket").casefold()
    settings = normalize_nicotine_settings(
        {
            "host": host or "127.0.0.1",
            "port": port,
            "transport": transport_key,
            "api_port": api_port,
            "api_token": api_token,
        }
    )
    transport_key = str(settings["transport"]).casefold()
    provider = NicotinePlusProvider(connect_timeout_seconds=timeout_seconds)
    ok = provider.connect(
        AcquisitionProviderConfig(
            provider_id="nicotine_plus",
            enabled=True,
            settings=settings,
        )
    )
    if ok:
        if transport_key == "http":
            return NicotineProbeResult(
                ok=True,
                message=f"Connected to api-nicotine-plus at {host}:{api_port}.",
            )
        return NicotineProbeResult(
            ok=True,
            message=f"Connected to NDJSON socket at {host}:{port}.",
        )
    if transport_key == "http":
        return NicotineProbeResult(
            ok=False,
            message=(
                f"Cannot reach api-nicotine-plus at {host}:{api_port}. "
                "Ensure Nicotine+ is running with the HTTP plugin enabled and "
                "the API token matches (if configured)."
            ),
        )
    return NicotineProbeResult(
        ok=False,
        message=(
            f"Cannot connect to NDJSON socket at {host}:{port}. "
            "For socket mode, run scripts/nicotine_plus_ndjson_proxy.py "
            "(with api-nicotine-plus on the HTTP API port) or switch transport to HTTP."
        ),
    )


def connect_acquisition_providers(
    config: AcquisitionConfig,
    manager: ProviderManager,
) -> None:
    """Connect enabled acquisition providers using application config."""
    nicotine_settings = normalize_nicotine_settings(
        {
            **asdict(config.nicotine_plus),
            "api_token": config.nicotine_plus.api_token or config.nicotine_plus.password,
            # HTTP search must poll Soulseek results for this long.
            "search_timeout_seconds": config.search_timeout_seconds,
        }
    )
    settings_by_id = {
        "nicotine_plus": nicotine_settings,
        "stub": {},
    }
    enabled = resolve_enabled_acquisition_providers(config)

    for provider_id in config.provider_order:
        if provider_id not in enabled:
            continue
        if manager.get(provider_id) is None:
            continue
        ok = manager.connect(
            AcquisitionProviderConfig(
                provider_id=provider_id,
                enabled=True,
                settings=settings_by_id.get(provider_id, {}),
            )
        )
        if provider_id == "nicotine_plus" and config.nicotine_plus.enabled:
            transport = str(nicotine_settings.get("transport") or "socket")
            if ok:
                logger.debug(
                    "Nicotine+ connected via {} ({}:{})",
                    transport,
                    nicotine_settings.get("host"),
                    nicotine_settings.get("api_port")
                    if transport == "http"
                    else nicotine_settings.get("port"),
                )
            else:
                logger.warning(
                    "Nicotine+ is enabled but did not connect (transport={}). "
                    "Acquisition searches will not reach Soulseek until Settings → "
                    "Test connection succeeds.",
                    transport,
                )
