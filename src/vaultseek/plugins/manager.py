"""Lightweight in-process plugin manager for built-in providers."""

from __future__ import annotations

from collections.abc import Sequence

from vaultseek.models.interfaces.acquisition import AcquisitionProvider
from vaultseek.models.interfaces.artwork import ArtworkProvider
from vaultseek.models.interfaces.media_server import MediaServerPlugin
from vaultseek.models.interfaces.metadata import MetadataProvider


class PluginManager:
    """Holds explicitly registered built-in providers."""

    def __init__(
        self,
        metadata_providers: Sequence[MetadataProvider] = (),
        artwork_providers: Sequence[ArtworkProvider] = (),
        media_server_plugins: Sequence[MediaServerPlugin] = (),
        acquisition_providers: Sequence[AcquisitionProvider] = (),
    ) -> None:
        self._metadata_providers = list(metadata_providers)
        self._artwork_providers = list(artwork_providers)
        self._media_server_plugins = list(media_server_plugins)
        self._acquisition_providers = list(acquisition_providers)

    def get_metadata_providers(self) -> list[MetadataProvider]:
        return sorted(self._metadata_providers, key=lambda p: p.priority)

    def get_artwork_providers(self) -> list[ArtworkProvider]:
        return sorted(self._artwork_providers, key=lambda p: p.priority)

    def get_media_servers(self) -> list[MediaServerPlugin]:
        return list(self._media_server_plugins)

    def get_acquisition_providers(self) -> list[AcquisitionProvider]:
        return list(self._acquisition_providers)
