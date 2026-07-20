"""add artwork tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-17 12:00:00.000000

Phase 11 re-designs the three artwork tables whose v1 column-level
specification was lost (see the "Artwork, Plugins, Statistics" note in
docs/architecture/03-database-schema.md). `artwork` holds one row per
unique image (deduplicated by content hash; bytes live on disk under
the app cache directory), while `track_artwork` / `album_artwork` link
images to tracks and albums with a role + primary flag.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "artwork",
        sa.Column("id", sa.LargeBinary(16), primary_key=True),
        sa.Column("content_hash_sha256", sa.Text, nullable=False, unique=True),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("source_id", sa.Text),
        sa.Column("mime_type", sa.Text, nullable=False),
        sa.Column("width", sa.Integer, nullable=False),
        sa.Column("height", sa.Integer, nullable=False),
        sa.Column("file_size", sa.Integer, nullable=False),
        sa.Column("file_path", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
    )
    op.create_index(
        "idx_artwork_content_hash",
        "artwork",
        ["content_hash_sha256"],
        unique=True,
    )
    op.create_table(
        "track_artwork",
        sa.Column("track_id", sa.LargeBinary(16), sa.ForeignKey("tracks.id"), primary_key=True),
        sa.Column("artwork_id", sa.LargeBinary(16), sa.ForeignKey("artwork.id"), primary_key=True),
        sa.Column("role", sa.Text, nullable=False, server_default=sa.text("'front'")),
        sa.Column("is_primary", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_index("idx_track_artwork_artwork", "track_artwork", ["artwork_id"])
    op.create_table(
        "album_artwork",
        sa.Column("album_id", sa.LargeBinary(16), sa.ForeignKey("albums.id"), primary_key=True),
        sa.Column("artwork_id", sa.LargeBinary(16), sa.ForeignKey("artwork.id"), primary_key=True),
        sa.Column("role", sa.Text, nullable=False, server_default=sa.text("'front'")),
        sa.Column("is_primary", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_index("idx_album_artwork_artwork", "album_artwork", ["artwork_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("idx_album_artwork_artwork", table_name="album_artwork")
    op.drop_table("album_artwork")
    op.drop_index("idx_track_artwork_artwork", table_name="track_artwork")
    op.drop_table("track_artwork")
    op.drop_index("idx_artwork_content_hash", table_name="artwork")
    op.drop_table("artwork")
