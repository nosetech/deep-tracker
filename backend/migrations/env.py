import os

from alembic import context

from deep_tracker.config import get_settings
from deep_tracker.db.models import Base
from deep_tracker.db.session import create_db_engine

target_metadata = Base.metadata


def _db_path() -> str:
    # upgrade_db() / テストからはプログラムで渡し、CLI 実行時は設定ファイルの値を使う
    return context.config.attributes.get("db_path") or os.fspath(get_settings().db.path)


def run_migrations_online() -> None:
    engine = create_db_engine(_db_path())
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations_online()
