from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from deep_tracker.config import Settings, get_settings

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def create_db_engine(db_path: str | Path | None = None) -> Engine:
    """SQLite エンジンを作る。WAL・外部キー・busy_timeout を有効にする。"""
    if db_path is None:
        db_path = get_settings().db.path
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}")

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _record) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def upgrade_db(settings: Settings | None = None) -> None:
    """設定のDBパスに対して最新のマイグレーションを適用する（DBが無ければ作成される）。"""
    if settings is None:
        settings = get_settings()
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    cfg.attributes["db_path"] = settings.db.path
    command.upgrade(cfg, "head")
