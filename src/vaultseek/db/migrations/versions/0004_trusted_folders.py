"""add trusted_folders for fingerprint sampling

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-19 18:00:00.000000

Stores album folders whose identity was confirmed by sampling
(fingerprint + tags + filenames + track count) so remaining files in
the folder can skip Chromaprint.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "trusted_folders",
        sa.Column("library_id", sa.LargeBinary(16), sa.ForeignKey("libraries.id"), primary_key=True),
        sa.Column("folder_path", sa.Text, primary_key=True),
        sa.Column("release_mbid", sa.Text, nullable=False),
        sa.Column("official_track_count", sa.Integer, nullable=False),
        sa.Column("sample_confirmed", sa.Integer, nullable=False),
        sa.Column("trusted_at", sa.Text, nullable=False),
    )
    op.create_index("idx_trusted_folders_library", "trusted_folders", ["library_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("idx_trusted_folders_library", table_name="trusted_folders")
    op.drop_table("trusted_folders")
