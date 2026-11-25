"""articles に言語判定と日本語訳（language / title_ja / content_ja / translated_at）を追加

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-25 09:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 既存記事は NULL（未判定・未翻訳）のまま。原文の列は変更しない
    with op.batch_alter_table("articles", schema=None) as batch_op:
        batch_op.add_column(sa.Column("language", sa.String(length=8), nullable=True))
        batch_op.add_column(sa.Column("title_ja", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("content_ja", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("translated_at", sa.DateTime(), nullable=True))
        batch_op.add_column(
            sa.Column("translation_truncated", sa.Boolean(), server_default="0", nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("articles", schema=None) as batch_op:
        batch_op.drop_column("translation_truncated")
        batch_op.drop_column("translated_at")
        batch_op.drop_column("content_ja")
        batch_op.drop_column("title_ja")
        batch_op.drop_column("language")
