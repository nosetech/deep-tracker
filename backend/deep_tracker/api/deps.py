from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy.orm import Session, sessionmaker

from deep_tracker.db import create_db_engine, make_session_factory


@lru_cache(maxsize=1)
def _session_factory() -> sessionmaker[Session]:
    return make_session_factory(create_db_engine())


def get_session() -> Iterator[Session]:
    with _session_factory()() as session:
        yield session
