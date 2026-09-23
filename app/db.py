import os
import secrets
import uuid
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models import AppConfig, Base

os.makedirs(os.path.dirname(settings.db_path), exist_ok=True)

engine = create_engine(f"sqlite:///{settings.db_path}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        if session.get(AppConfig, 1) is None:
            session.add(
                AppConfig(
                    id=1,
                    client_identifier=str(uuid.uuid4()),
                    session_secret=secrets.token_hex(32),
                )
            )
            session.commit()


def get_app_config() -> AppConfig:
    with SessionLocal() as session:
        config = session.get(AppConfig, 1)
        if config is None:
            raise RuntimeError("init_db() must run before get_app_config()")
        return config


def set_tmdb_api_key(value: str | None) -> None:
    with SessionLocal() as session:
        config = session.get(AppConfig, 1)
        config.tmdb_api_key = value or None
        session.commit()


@contextmanager
def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
