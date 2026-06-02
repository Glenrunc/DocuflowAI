from collections.abc import Iterator

from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine

from .config import settings

connect_args = {}
engine = create_engine(settings.database_url, echo=False, connect_args=connect_args)

# Additive, idempotent schema touches (no Alembic): a nullable TL;DR column and a GIN
# full-text index. Both use IF NOT EXISTS so they're safe to run on an existing DB.
_MIGRATIONS = [
    "ALTER TABLE document ADD COLUMN IF NOT EXISTS summary VARCHAR",
    "CREATE INDEX IF NOT EXISTS document_fts ON document USING gin "
    "(to_tsvector('french', coalesce(ocr_text, '') || ' ' || filename))",
]


def init_db() -> None:
    # Import models so SQLModel.metadata is populated before create_all.
    from . import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:
        for stmt in _MIGRATIONS:
            conn.execute(text(stmt))


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
