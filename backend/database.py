import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import load_environment


load_environment()


DEFAULT_DB_PATH = Path("data") / "meeting_agent.db"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH.as_posix()}")


class Base(DeclarativeBase):
    pass


def ensure_sqlite_parent() -> None:
    if DATABASE_URL.startswith("sqlite:///"):
        db_path = Path(DATABASE_URL.replace("sqlite:///", "", 1))
        if db_path.parent != Path("."):
            db_path.parent.mkdir(parents=True, exist_ok=True)


ensure_sqlite_parent()

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    run_lightweight_migrations()


def run_lightweight_migrations() -> None:
    if not DATABASE_URL.startswith("sqlite"):
        return

    with engine.begin() as connection:
        inspector = inspect(connection)
        if "meetings" not in inspector.get_table_names():
            return

        columns = {column["name"] for column in inspector.get_columns("meetings")}
        if "user_id" not in columns:
            connection.execute(text("ALTER TABLE meetings ADD COLUMN user_id INTEGER"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
