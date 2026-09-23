from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AppConfig(Base):
    __tablename__ = "app_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_identifier: Mapped[str] = mapped_column(String, nullable=False)
    session_secret: Mapped[str] = mapped_column(String, nullable=False)
    tmdb_api_key: Mapped[str | None] = mapped_column(String, nullable=True)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class Integration(Base):
    """A connected external account that supplies watch history (e.g. Plex).

    Kept separate from User so a person's login isn't tied to any one
    provider, and so more providers can be added later without touching
    the auth model.
    """

    __tablename__ = "integrations"
    __table_args__ = (UniqueConstraint("provider", "external_id", name="uq_provider_external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)  # 'plex'
    external_id: Mapped[str] = mapped_column(String, nullable=False)  # plex account uuid
    display_name: Mapped[str] = mapped_column(String, nullable=False)  # plex username
    thumb_url: Mapped[str | None] = mapped_column(String, nullable=True)
    access_token: Mapped[str] = mapped_column(String, nullable=False)
    connected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class WatchHistory(Base):
    __tablename__ = "watch_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    integration_id: Mapped[int] = mapped_column(ForeignKey("integrations.id"), nullable=False, index=True)
    history_key: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    item_key: Mapped[str] = mapped_column(String, nullable=False, index=True)
    grandparent_key: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    media_type: Mapped[str] = mapped_column(String, nullable=False)  # 'movie' | 'episode'
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    grandparent_title: Mapped[str | None] = mapped_column(String, nullable=True)
    season_index: Mapped[int | None] = mapped_column(nullable=True)
    episode_index: Mapped[int | None] = mapped_column(nullable=True)
    poster_url: Mapped[str | None] = mapped_column(String, nullable=True)
    grandparent_poster_url: Mapped[str | None] = mapped_column(String, nullable=True)
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # null for self-reported entries
    synced_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class SyncState(Base):
    __tablename__ = "sync_state"

    integration_id: Mapped[int] = mapped_column(ForeignKey("integrations.id"), primary_key=True)
    last_history_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_run_status: Mapped[str | None] = mapped_column(String, nullable=True)
    last_run_error: Mapped[str | None] = mapped_column(String, nullable=True)
