"""Database engine and session helpers.

This module isolates SQLModel/SQLAlchemy setup from the rest of the app.
FastAPI depends on ``get_session``; scripts can use ``init_db`` directly.

If the project later moves to Django, this module would be replaced by Django's
database configuration while the higher-level concepts can remain similar.
"""

from collections.abc import Generator

from sqlmodel import Session, SQLModel, create_engine

from mandarin_tone_recorder.config import DATA_DIR, DATABASE_URL


# SQLite needs this option when a connection may be used across FastAPI request
# handling threads. This is common in small local FastAPI apps.
connect_args = {"check_same_thread": False}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    echo=False,
)


def init_db() -> None:
    """Create database tables if they do not already exist.

    During early prototyping this is simpler than running migrations. Once the
    schema stabilizes, we can add Alembic migrations and stop relying on
    automatic table creation.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    """Yield a database session for FastAPI dependency injection.

    FastAPI's SQL database examples use this dependency pattern so each request
    gets a session and the session is closed afterwards.
    """
    with Session(engine) as session:
        yield session
