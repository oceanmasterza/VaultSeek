"""SQLAlchemy Core table definitions for the MusicVault schema.

This module defines the 15 tables that were fully specified in
docs/architecture/03-database-schema.md, plus the three artwork tables
(``artwork``, ``track_artwork``, ``album_artwork``) whose column-level
design was lost when the v1 schema document was superseded and which
Phase 11 re-designed from scratch (see
:mod:`musicvault.models.entities.artwork` for the design rationale).
Two more tables mentioned in that document (``plugin_state``,
``library_stats``) remain intentionally undefined until the phases that
actually need them.

Conventions used throughout, matching the schema document exactly:

- Every primary/foreign key is UUIDv7 stored as ``LargeBinary(16)`` (a
  16-byte BLOB), never SQLAlchemy's native ``Uuid`` type. Conversion
  to/from Python's ``uuid.UUID`` happens explicitly at the repository
  boundary (see :mod:`musicvault.db.uuid_utils`) — this module only ever
  reads/writes raw bytes.
- Every timestamp column is ``Text`` holding an ISO 8601 string, not
  SQLAlchemy's ``DateTime`` type. This is a deliberate schema decision
  (see the schema document), not an oversight.
- Column-level ``server_default`` values are set only where the schema
  document explicitly documents a ``DEFAULT``. FK ``ondelete`` behavior is
  intentionally left unspecified (SQLite's default no-action semantics)
  because the document does not mandate cascade/restrict/set-null for any
  relationship; deciding that is deferred to whichever phase first needs
  it (most likely Phase 12, the rollback engine).
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    Table,
    Text,
    false,
    text,
    true,
)

metadata = MetaData()

# ---------------------------------------------------------------------------
# Core Library Tables
# ---------------------------------------------------------------------------

libraries = Table(
    "libraries",
    metadata,
    Column("id", LargeBinary(16), primary_key=True),
    Column("name", Text, nullable=False),
    Column("incoming_path", Text, nullable=False),
    Column("staging_path", Text, nullable=False),
    Column("library_path", Text, nullable=False),
    Column("archive_path", Text, nullable=False),
    Column("watch_enabled", Boolean, nullable=False, server_default=false()),
    Column("auto_approve_threshold", Float, nullable=False, server_default=text("0.90")),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
)

artists = Table(
    "artists",
    metadata,
    Column("id", LargeBinary(16), primary_key=True),
    Column("name", Text, nullable=False),
    Column("sort_name", Text, nullable=False),
    Column("mbid", Text),
    Column("discogs_id", Text),
    Column("type", Text),
    Column("country", Text),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
    Index("idx_artists_name", "name"),
    Index("idx_artists_sort_name", "sort_name"),
    Index("idx_artists_mbid", "mbid"),
)

albums = Table(
    "albums",
    metadata,
    Column("id", LargeBinary(16), primary_key=True),
    Column("title", Text, nullable=False),
    Column("sort_title", Text, nullable=False),
    Column("album_artist_id", LargeBinary(16), ForeignKey("artists.id")),
    Column("year", Integer),
    Column("mbid", Text),
    Column("release_group_mbid", Text),
    Column("discogs_id", Text),
    Column("type", Text),
    Column("genre", Text),
    Column("disc_count", Integer, nullable=False, server_default=text("1")),
    Column("track_count", Integer, nullable=False, server_default=text("0")),
    Column("is_compilation", Boolean, nullable=False, server_default=false()),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
    Index("idx_albums_title", "title"),
    Index("idx_albums_mbid", "mbid"),
    Index("idx_albums_artist", "album_artist_id"),
)

tracks = Table(
    "tracks",
    metadata,
    Column("id", LargeBinary(16), primary_key=True),
    Column("library_id", LargeBinary(16), ForeignKey("libraries.id"), nullable=False),
    Column("album_id", LargeBinary(16), ForeignKey("albums.id")),
    Column("artist_id", LargeBinary(16), ForeignKey("artists.id")),
    Column("zone", Text, nullable=False),
    Column("file_path", Text, nullable=False, unique=True),
    Column("file_name", Text, nullable=False),
    Column("file_size", Integer, nullable=False),
    Column("file_modified", Text, nullable=False),
    Column("title", Text),
    Column("track_number", Integer),
    Column("disc_number", Integer, nullable=False, server_default=text("1")),
    Column("duration_ms", Integer),
    Column("bitrate", Integer),
    Column("bit_depth", Integer),
    Column("sample_rate", Integer),
    Column("channels", Integer),
    Column("codec", Text),
    Column("is_lossless", Boolean, nullable=False, server_default=false()),
    Column("quality_score", Integer),
    Column("mb_recording_id", Text),
    Column("composer", Text),
    Column("genre", Text),
    Column("year", Integer),
    Column("has_embedded_art", Boolean, nullable=False, server_default=false()),
    Column("is_corrupt", Boolean, nullable=False, server_default=false()),
    Column("overall_confidence", Float),
    Column("needs_review", Boolean, nullable=False, server_default=false()),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
    Index("idx_tracks_library_zone", "library_id", "zone"),
    Index("idx_tracks_file_path", "file_path", unique=True),
    Index("idx_tracks_album", "album_id"),
    Index("idx_tracks_mb_recording", "mb_recording_id"),
    Index("idx_tracks_needs_review", "needs_review", sqlite_where=text("needs_review = TRUE")),
    Index("idx_tracks_quality", "quality_score"),
)

# ---------------------------------------------------------------------------
# File Identity (Fingerprint Persistence)
# ---------------------------------------------------------------------------

file_identity = Table(
    "file_identity",
    metadata,
    Column("track_id", LargeBinary(16), ForeignKey("tracks.id"), primary_key=True),
    Column("content_hash_sha256", Text, nullable=False),
    Column("fingerprint_data", LargeBinary),
    Column("fingerprint_duration", Float),
    Column("fingerprint_hash", Text),
    Column("acoustid_id", Text),
    Column("acoustid_score", Float),
    Column("file_size", Integer, nullable=False),
    Column("file_modified", Text, nullable=False),
    Column("hash_computed_at", Text),
    Column("fingerprint_computed_at", Text),
    Index("idx_file_identity_acoustid", "acoustid_id"),
    Index("idx_file_identity_content_hash", "content_hash_sha256"),
    Index("idx_file_identity_fingerprint_hash", "fingerprint_hash"),
)

# ---------------------------------------------------------------------------
# Metadata Confidence
# ---------------------------------------------------------------------------

metadata_confidence = Table(
    "metadata_confidence",
    metadata,
    Column("id", LargeBinary(16), primary_key=True),
    Column("track_id", LargeBinary(16), ForeignKey("tracks.id"), nullable=False),
    Column("field_name", Text, nullable=False),
    Column("value", Text),
    Column("confidence", Float, nullable=False),
    Column("source", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
    Index("idx_metadata_conf_track", "track_id"),
    Index("idx_metadata_confidence_track_field", "track_id", "field_name", unique=True),
)

# ---------------------------------------------------------------------------
# Artwork (Phase 11 re-design — see musicvault.models.entities.artwork)
# ---------------------------------------------------------------------------

artwork = Table(
    "artwork",
    metadata,
    Column("id", LargeBinary(16), primary_key=True),
    Column("content_hash_sha256", Text, nullable=False, unique=True),
    Column("source", Text, nullable=False),
    Column("source_id", Text),
    Column("mime_type", Text, nullable=False),
    Column("width", Integer, nullable=False),
    Column("height", Integer, nullable=False),
    Column("file_size", Integer, nullable=False),
    Column("file_path", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    Index("idx_artwork_content_hash", "content_hash_sha256", unique=True),
)

track_artwork = Table(
    "track_artwork",
    metadata,
    Column("track_id", LargeBinary(16), ForeignKey("tracks.id"), primary_key=True),
    Column("artwork_id", LargeBinary(16), ForeignKey("artwork.id"), primary_key=True),
    Column("role", Text, nullable=False, server_default=text("'front'")),
    Column("is_primary", Boolean, nullable=False, server_default=false()),
    Index("idx_track_artwork_artwork", "artwork_id"),
)

album_artwork = Table(
    "album_artwork",
    metadata,
    Column("album_id", LargeBinary(16), ForeignKey("albums.id"), primary_key=True),
    Column("artwork_id", LargeBinary(16), ForeignKey("artwork.id"), primary_key=True),
    Column("role", Text, nullable=False, server_default=text("'front'")),
    Column("is_primary", Boolean, nullable=False, server_default=false()),
    Index("idx_album_artwork_artwork", "artwork_id"),
)

# ---------------------------------------------------------------------------
# Job Queue
# ---------------------------------------------------------------------------

jobs = Table(
    "jobs",
    metadata,
    Column("id", LargeBinary(16), primary_key=True),
    Column("library_id", LargeBinary(16), ForeignKey("libraries.id"), nullable=False),
    Column("job_type", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("priority", Integer, nullable=False, server_default=text("100")),
    Column("payload", Text, nullable=False),
    Column("parent_job_id", LargeBinary(16), ForeignKey("jobs.id")),
    Column("attempt_count", Integer, nullable=False, server_default=text("0")),
    Column("max_attempts", Integer, nullable=False, server_default=text("3")),
    Column("error_message", Text),
    Column("created_at", Text, nullable=False),
    Column("started_at", Text),
    Column("completed_at", Text),
    Column("scheduled_at", Text),
    Index("idx_jobs_claim", "status", "job_type", "priority", "created_at"),
    Index("idx_jobs_library", "library_id", "status"),
    Index("idx_jobs_parent", "parent_job_id"),
)

# ---------------------------------------------------------------------------
# Review Queue
# ---------------------------------------------------------------------------

review_items = Table(
    "review_items",
    metadata,
    Column("id", LargeBinary(16), primary_key=True),
    Column("library_id", LargeBinary(16), ForeignKey("libraries.id"), nullable=False),
    Column("track_id", LargeBinary(16), ForeignKey("tracks.id")),
    Column("album_id", LargeBinary(16), ForeignKey("albums.id")),
    Column("duplicate_group_id", LargeBinary(16), ForeignKey("duplicate_groups.id")),
    Column("review_type", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("description", Text),
    Column("confidence", Float),
    Column("payload", Text),
    Column("created_at", Text, nullable=False),
    Column("resolved_at", Text),
    Column("resolved_by", Text),
    Index("idx_review_library_status", "library_id", "status"),
)

# ---------------------------------------------------------------------------
# Rules Engine
# ---------------------------------------------------------------------------

rules = Table(
    "rules",
    metadata,
    Column("id", LargeBinary(16), primary_key=True),
    Column("library_id", LargeBinary(16), ForeignKey("libraries.id"), nullable=False),
    Column("name", Text, nullable=False),
    Column("enabled", Boolean, nullable=False, server_default=true()),
    Column("priority", Integer, nullable=False, server_default=text("100")),
    Column("conditions", Text, nullable=False),
    Column("actions", Text, nullable=False),
    Column("requires_approval", Boolean, nullable=False, server_default=false()),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
)

# ---------------------------------------------------------------------------
# Duplicates
# ---------------------------------------------------------------------------

duplicate_groups = Table(
    "duplicate_groups",
    metadata,
    Column("id", LargeBinary(16), primary_key=True),
    Column("library_id", LargeBinary(16), ForeignKey("libraries.id")),
    Column("match_type", Text, nullable=False),
    Column("match_confidence", Float, nullable=False),
    Column("best_track_id", LargeBinary(16), ForeignKey("tracks.id")),
    Column("track_count", Integer, nullable=False),
    Column("detected_at", Text, nullable=False),
    Column("status", Text, nullable=False, server_default=text("'open'")),
    Column("resolution", Text),
    Index("idx_duplicate_groups_library_status", "library_id", "status"),
)

duplicate_members = Table(
    "duplicate_members",
    metadata,
    Column("group_id", LargeBinary(16), ForeignKey("duplicate_groups.id"), primary_key=True),
    Column("track_id", LargeBinary(16), ForeignKey("tracks.id"), primary_key=True),
    Column("quality_score", Integer, nullable=False),
    Column("is_best", Boolean, nullable=False, server_default=false()),
    Column("zone", Text, nullable=False),
    Index("idx_duplicate_members_track", "track_id"),
)

# ---------------------------------------------------------------------------
# Operations & Rollback
# ---------------------------------------------------------------------------

operations = Table(
    "operations",
    metadata,
    Column("id", LargeBinary(16), primary_key=True),
    Column("operation_type", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("is_dry_run", Boolean, nullable=False, server_default=false()),
    Column("description", Text),
    Column("affected_count", Integer, nullable=False, server_default=text("0")),
    Column("started_at", Text, nullable=False),
    Column("completed_at", Text),
    Column("snapshot_id", LargeBinary(16), ForeignKey("rollback_snapshots.id")),
)

change_history = Table(
    "change_history",
    metadata,
    Column("id", LargeBinary(16), primary_key=True),
    Column("operation_id", LargeBinary(16), ForeignKey("operations.id")),
    Column("track_id", LargeBinary(16), ForeignKey("tracks.id")),
    Column("change_type", Text, nullable=False),
    Column("field_name", Text),
    Column("old_value", Text),
    Column("new_value", Text),
    Column("old_file_path", Text),
    Column("new_file_path", Text),
    Column("old_zone", Text),
    Column("new_zone", Text),
    Column("timestamp", Text, nullable=False),
)

rollback_snapshots = Table(
    "rollback_snapshots",
    metadata,
    Column("id", LargeBinary(16), primary_key=True),
    Column("operation_id", LargeBinary(16), ForeignKey("operations.id")),
    Column("snapshot_data", LargeBinary, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("restored_at", Text),
)

# ---------------------------------------------------------------------------
# Media Server Integration
# ---------------------------------------------------------------------------
#
# NOTE: the schema document specifies this table's columns and types but,
# unlike every other table, omits a "Constraints" column entirely — so
# nullability is not literally documented anywhere. The choices below
# (library_id and plugin_id required, everything else optional) are the
# minimal reasonable interpretation: a state row without a library or a
# plugin identifier would be meaningless. No uniqueness constraint is
# added here (e.g. one row per library+plugin) since the document does
# not call for one; that is left as an application-level concern until a
# real need (and a documented decision) exists.

media_server_state = Table(
    "media_server_state",
    metadata,
    Column("id", LargeBinary(16), primary_key=True),
    Column("library_id", LargeBinary(16), ForeignKey("libraries.id"), nullable=False),
    Column("plugin_id", Text, nullable=False),
    Column("server_url", Text),
    Column("db_path", Text),
    Column("config", Text),
    Column("last_sync_at", Text),
    Column("last_sync_status", Text),
    Index("idx_media_server_state_library", "library_id"),
)
