"""add idx_tracks_artist for browse queries

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-19 20:45:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index("idx_tracks_artist", "tracks", ["artist_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("idx_tracks_artist", table_name="tracks")
