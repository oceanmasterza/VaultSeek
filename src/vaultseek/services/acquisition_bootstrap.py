"""Bootstrap helpers for acquisition providers."""

from __future__ import annotations

from dataclasses import asdict

from vaultseek.core.config import AcquisitionConfig
from vaultseek.models.interfaces.acquisition import AcquisitionProviderConfig
from vaultseek.services.provider_manager import ProviderManager


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
