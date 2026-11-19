"""articles に記事のマーク（is_marked / marked_at）を追加

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-20 09:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("articles", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("is_marked", sa.Boolean(), server_default="0", nullable=False)
        )
        batch_op.add_column(sa.Column("marked_at", sa.DateTime(), nullable=True))
        batch_op.create_index(
            "ix_articles_is_marked_published_at", ["is_marked", "published_at"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("articles", schema=None) as batch_op:
        batch_op.drop_index("ix_articles_is_marked_published_at")
        batch_op.drop_column("marked_at")
        batch_op.drop_column("is_marked")
