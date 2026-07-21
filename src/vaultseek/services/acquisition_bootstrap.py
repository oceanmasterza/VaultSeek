"""Bootstrap helpers for acquisition providers."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from vaultseek.core.config import AcquisitionConfig
from vaultseek.models.interfaces.acquisition import AcquisitionProviderConfig
from vaultseek.plugins.builtin.nicotine_plus import NicotinePlusProvider
from vaultseek.services.provider_manager import ProviderManager


@dataclass(frozen=True, slots=True)
class NicotineProbeResult:
    ok: bool
    message: str


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
    settings = {
        "host": host or "127.0.0.1",
        "port": port,
        "transport": transport_key,
        "api_port": api_port,
        "api_token": api_token,
    }
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
    settings_by_id = {
        "nicotine_plus": {
            **asdict(config.nicotine_plus),
            "api_token": config.nicotine_plus.api_token or config.nicotine_plus.password,
        },
        "stub": {},
    }
    enabled = set(config.enabled_providers)
    if config.nicotine_plus.enabled:
        enabled.add("nicotine_plus")

    for provider_id in config.provider_order:
        if provider_id not in enabled:
            continue
        if manager.get(provider_id) is None:
            continue
        manager.connect(
            AcquisitionProviderConfig(
                provider_id=provider_id,
                enabled=True,
                settings=settings_by_id.get(provider_id, {}),
            )
        )
