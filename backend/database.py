import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import load_environment


load_environment()


DEFAULT_DATABASE_URL = "postgresql+psycopg://meeting_agent:meeting_agent@localhost:5432/meeting_agent"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
SCHEMA_LOCK_ID = 51420260518

if not DATABASE_URL.startswith("postgresql"):
    raise RuntimeError("DATABASE_URL must point to Postgres, for example: " + DEFAULT_DATABASE_URL)


class Base(DeclarativeBase):
    pass


engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    from . import models  # noqa: F401

    with engine.begin() as connection:
        connection.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": SCHEMA_LOCK_ID})
        ensure_postgres_extensions(connection)
        Base.metadata.create_all(bind=connection)
        run_migrations(connection)


def ensure_postgres_extensions(connection: Connection | None = None) -> None:
    if connection is not None:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        return

    with engine.begin() as connection:
        ensure_postgres_extensions(connection)


def run_migrations(connection: Connection) -> None:
    project_root = Path(__file__).resolve().parents[1]
    alembic_ini = project_root / "alembic.ini"
    migrations_dir = project_root / "migrations"
    if not alembic_ini.exists() or not migrations_dir.exists():
        return

    config = Config(str(alembic_ini))
    config.set_main_option("script_location", str(migrations_dir))
    config.set_main_option("sqlalchemy.url", DATABASE_URL)
    config.attributes["connection"] = connection
    command.upgrade(config, "head")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
