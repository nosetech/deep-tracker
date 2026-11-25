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
        # SQLite の batch mode はテーブルを作り直す（コピー → DROP TABLE → リネーム）。外部キーが
        # 有効なままだと、DROP TABLE が参照元の ON DELETE CASCADE / SET NULL を発火させて
        # 関連する行（例: feeds を作り直すと articles）を消してしまう。マイグレーション中は
        # 無効にし、終了後に整合性を検査する。PRAGMA foreign_keys はトランザクション外でのみ有効
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()
            violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise RuntimeError(f"マイグレーション後に外部キーの不整合があります: {violations}")
        connection.commit()
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    engine.dispose()


run_migrations_online()
