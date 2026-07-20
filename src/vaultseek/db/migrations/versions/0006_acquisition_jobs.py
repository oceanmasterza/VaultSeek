"""add acquisition_jobs table for VaultSeek AcquisitionEngine

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-20 14:00:00.000000

Persists AcquisitionJob entities (ADR-0017) so job lifecycle survives
application restarts.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "acquisition_jobs",
        sa.Column("id", sa.LargeBinary(16), primary_key=True),
        sa.Column("library_id", sa.LargeBinary(16), sa.ForeignKey("libraries.id"), nullable=False),
        sa.Column("job_type", sa.Text, nullable=False),
        sa.Column("state", sa.Text, nullable=False),
        sa.Column("artist", sa.Text),
        sa.Column("album", sa.Text),
        sa.Column("title", sa.Text),
        sa.Column("year", sa.Integer),
        sa.Column("mb_release_id", sa.Text),
        sa.Column("preferred_codec", sa.Text),
        sa.Column("preferred_bit_depth", sa.Integer),
        sa.Column("preferred_country", sa.Text),
        sa.Column("preferred_providers", sa.Text, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("selected_result_id", sa.Text),
        sa.Column("selected_provider_id", sa.Text),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("priority", sa.Integer, nullable=False, server_default=sa.text("100")),
        sa.Column("progress", sa.Float, nullable=False, server_default=sa.text("0")),
        sa.Column("error_message", sa.Text),
        sa.Column("history", sa.Text, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("extra", sa.Text, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
    )
    op.create_index(
        "idx_acquisition_jobs_library",
        "acquisition_jobs",
        ["library_id", "state"],
    )
    op.create_index(
        "idx_acquisition_jobs_priority",
        "acquisition_jobs",
        ["library_id", "priority", "created_at"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("idx_acquisition_jobs_priority", table_name="acquisition_jobs")
    op.drop_index("idx_acquisition_jobs_library", table_name="acquisition_jobs")
    op.drop_table("acquisition_jobs")
