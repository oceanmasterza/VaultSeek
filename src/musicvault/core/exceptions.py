"""Application-wide exception hierarchy.

All MusicVault exceptions derive from :class:`MusicVaultError` so calling
code can catch application failures without accidentally swallowing
unrelated Python exceptions (e.g. programming errors such as
``AttributeError``). Later phases add subclasses under the groups defined
here rather than introducing new unrelated hierarchies.
"""

from __future__ import annotations


class MusicVaultError(Exception):
    """Base class for all exceptions raised by MusicVault."""


class ConfigError(MusicVaultError):
    """Raised when configuration cannot be loaded, parsed, or validated."""


class ConfigVersionError(ConfigError):
    """Raised when a configuration file's schema version is missing or unsupported."""


class ConfigMigrationError(ConfigError):
    """Raised when migrating a configuration file to a newer schema fails."""


class PluginError(MusicVaultError):
    """Base class for plugin discovery, loading, and execution failures."""


class PluginLoadError(PluginError):
    """Raised when a plugin fails to initialize."""

    def __init__(self, plugin_id: str, cause: Exception) -> None:
        super().__init__(f"Failed to load plugin '{plugin_id}': {cause}")
        self.plugin_id = plugin_id
        self.cause = cause


class DatabaseError(MusicVaultError):
    """Raised when the database cannot be opened, migrated, or queried."""


class JobError(MusicVaultError):
    """Base class for job queue and worker failures."""


class ReviewError(MusicVaultError):
    """Raised when a review-queue operation is invalid or cannot complete."""


class OperationError(MusicVaultError):
    """Raised when a mutating library operation fails."""


class RollbackError(MusicVaultError):
    """Raised when restoring a rollback snapshot fails."""
