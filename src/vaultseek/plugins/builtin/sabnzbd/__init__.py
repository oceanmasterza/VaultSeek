"""Built-in SABnzbd download client (used by the Prowlarr provider)."""

from vaultseek.plugins.builtin.sabnzbd.client import SabnzbdClient, SabnzbdMappedStatus, SabnzbdSlot

__all__ = ["SabnzbdClient", "SabnzbdMappedStatus", "SabnzbdSlot"]
