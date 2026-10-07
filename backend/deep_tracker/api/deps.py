from collections.abc import Iterator
from functools import lru_cache

import httpx
from sqlalchemy.orm import Session, sessionmaker

from deep_tracker.db import create_db_engine, make_session_factory


@lru_cache
def _session_factory() -> sessionmaker[Session]:
    return make_session_factory(create_db_engine())


def get_session() -> Iterator[Session]:
    with _session_factory()() as session:
        yield session


def get_http_client() -> Iterator[httpx.Client | None]:
    """フィード取得用のHTTPクライアント。None なら fetcher が既定を作る。テストで差し替える。"""
    yield None
