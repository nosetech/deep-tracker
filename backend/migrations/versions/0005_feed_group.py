"""フィードのグループ（feed_groups / feeds.group_id）を追加

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-25 12:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feed_groups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feed_groups")),
        sa.UniqueConstraint("name", name=op.f("uq_feed_groups_name")),
    )
    # 既存のフィードはすべて未分類（NULL）になる
    with op.batch_alter_table("feeds", schema=None) as batch_op:
        batch_op.add_column(sa.Column("group_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f("fk_feeds_group_id_feed_groups"),
            "feed_groups",
            ["group_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(batch_op.f("ix_feeds_group_id"), ["group_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("feeds", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_feeds_group_id"))
        batch_op.drop_constraint(batch_op.f("fk_feeds_group_id_feed_groups"), type_="foreignkey")
        batch_op.drop_column("group_id")
    op.drop_table("feed_groups")
