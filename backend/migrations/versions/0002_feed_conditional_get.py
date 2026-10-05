"""feeds に条件付きGET用の etag / last_modified を追加

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-05 08:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("feeds", schema=None) as batch_op:
        batch_op.add_column(sa.Column("etag", sa.String(length=512), nullable=True))
        batch_op.add_column(sa.Column("last_modified", sa.String(length=128), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("feeds", schema=None) as batch_op:
        batch_op.drop_column("last_modified")
        batch_op.drop_column("etag")
