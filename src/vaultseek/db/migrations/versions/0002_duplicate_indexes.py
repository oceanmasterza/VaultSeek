"""add duplicate detection indexes

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-17 12:00:00.000000

Phase 9 duplicate detection looks up tracks by shared content hash and
Chromaprint hash on every `detect_duplicates` job, and checks group
membership per track for the rules engine's `has_lossless_duplicate`
flag — all three lookups need indexes to avoid full-table scans at
100k+ track scale (docs/architecture/08-performance.md).
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        "idx_file_identity_content_hash",
        "file_identity",
        ["content_hash_sha256"],
        unique=False,
    )
    op.create_index(
        "idx_file_identity_fingerprint_hash",
        "file_identity",
        ["fingerprint_hash"],
        unique=False,
    )
    op.create_index(
        "idx_duplicate_members_track",
        "duplicate_members",
        ["track_id"],
        unique=False,
    )
    op.create_index(
        "idx_duplicate_groups_library_status",
        "duplicate_groups",
        ["library_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("idx_duplicate_groups_library_status", table_name="duplicate_groups")
    op.drop_index("idx_duplicate_members_track", table_name="duplicate_members")
    op.drop_index("idx_file_identity_fingerprint_hash", table_name="file_identity")
    op.drop_index("idx_file_identity_content_hash", table_name="file_identity")
