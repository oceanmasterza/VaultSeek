"""Application-wide exception hierarchy.

All VaultSeek exceptions derive from :class:`VaultSeekError` so calling
code can catch application failures without accidentally swallowing
unrelated Python exceptions (e.g. programming errors such as
``AttributeError``). Later phases add subclasses under the groups defined
here rather than introducing new unrelated hierarchies.
"""

from __future__ import annotations


class VaultSeekError(Exception):
    """Base class for all exceptions raised by VaultSeek."""


class ConfigError(VaultSeekError):
    """Raised when configuration cannot be loaded, parsed, or validated."""


class ConfigVersionError(ConfigError):
    """Raised when a configuration file's schema version is missing or unsupported."""


class ConfigMigrationError(ConfigError):
    """Raised when migrating a configuration file to a newer schema fails."""


class PluginError(VaultSeekError):
    """Base class for plugin discovery, loading, and execution failures."""


class PluginLoadError(PluginError):
    """Raised when a plugin fails to initialize."""

    def __init__(self, plugin_id: str, cause: Exception) -> None:
        super().__init__(f"Failed to load plugin '{plugin_id}': {cause}")
        self.plugin_id = plugin_id
        self.cause = cause


class DatabaseError(VaultSeekError):
    """Raised when the database cannot be opened, migrated, or queried."""


class JobError(VaultSeekError):
    """Base class for job queue and worker failures."""


class ReviewError(VaultSeekError):
    """Raised when a review-queue operation is invalid or cannot complete."""


class RuleError(VaultSeekError):
    """Raised when a rules-engine operation is invalid or cannot complete."""


class OperationError(VaultSeekError):
    """Raised when a mutating library operation fails."""


class RollbackError(VaultSeekError):
    """Raised when restoring a rollback snapshot fails."""


class ReportError(VaultSeekError):
    """Raised when a report cannot be generated or written."""
