"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-05 07:29:21.793253
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("input", sa.JSON(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_jobs")),
    )
    with op.batch_alter_table("ai_jobs", schema=None) as batch_op:
        batch_op.create_index(
            "ix_ai_jobs_status_created_at", ["status", "created_at"], unique=False
        )

    op.create_table(
        "feeds",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("fetch_interval_minutes", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_fetched_at", sa.DateTime(), nullable=True),
        sa.Column("last_fetch_ok", sa.Boolean(), nullable=True),
        sa.Column("last_fetch_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feeds")),
        sa.UniqueConstraint("url", name=op.f("uq_feeds_url")),
    )
    op.create_table(
        "summaries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("period_start", sa.DateTime(), nullable=False),
        sa.Column("period_end", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_summaries")),
    )
    with op.batch_alter_table("summaries", schema=None) as batch_op:
        batch_op.create_index("ix_summaries_period_start", ["period_start"], unique=False)

    op.create_table(
        "articles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("feed_id", sa.Integer(), nullable=False),
        sa.Column("guid", sa.String(length=2048), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("is_read", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["feed_id"], ["feeds.id"], name=op.f("fk_articles_feed_id_feeds"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_articles")),
        sa.UniqueConstraint("feed_id", "guid", name="uq_articles_feed_id_guid"),
    )
    with op.batch_alter_table("articles", schema=None) as batch_op:
        batch_op.create_index(
            "ix_articles_feed_id_published_at", ["feed_id", "published_at"], unique=False
        )
        batch_op.create_index(
            "ix_articles_is_read_published_at", ["is_read", "published_at"], unique=False
        )
        batch_op.create_index("ix_articles_published_at", ["published_at"], unique=False)

    op.create_table(
        "summary_articles",
        sa.Column("summary_id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["articles.id"],
            name=op.f("fk_summary_articles_article_id_articles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["summary_id"],
            ["summaries.id"],
            name=op.f("fk_summary_articles_summary_id_summaries"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("summary_id", "article_id", name=op.f("pk_summary_articles")),
    )
    with op.batch_alter_table("summary_articles", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_summary_articles_article_id"), ["article_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("summary_articles", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_summary_articles_article_id"))

    op.drop_table("summary_articles")
    with op.batch_alter_table("articles", schema=None) as batch_op:
        batch_op.drop_index("ix_articles_published_at")
        batch_op.drop_index("ix_articles_is_read_published_at")
        batch_op.drop_index("ix_articles_feed_id_published_at")

    op.drop_table("articles")
    with op.batch_alter_table("summaries", schema=None) as batch_op:
        batch_op.drop_index("ix_summaries_period_start")

    op.drop_table("summaries")
    op.drop_table("feeds")
    with op.batch_alter_table("ai_jobs", schema=None) as batch_op:
        batch_op.drop_index("ix_ai_jobs_status_created_at")

    op.drop_table("ai_jobs")
