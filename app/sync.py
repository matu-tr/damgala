import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from app.config import settings
from app.db import get_session
from app.models import Integration, SyncState, WatchHistory
from app.plex_client import fetch_history

logger = logging.getLogger(__name__)


def _sync_history(session, integration: Integration, state: SyncState, now: datetime) -> int:
    cursor = state.last_history_sync_at
    if cursor is None:
        mindate = now - timedelta(days=settings.history_lookback_days)
    else:
        mindate = cursor - timedelta(hours=1)  # overlap buffer for clock skew

    entries = fetch_history(token=integration.access_token, uuid=integration.external_id, mindate=mindate)

    existing_keys = {
        key
        for key in session.scalars(
            select(WatchHistory.history_key).where(
                WatchHistory.history_key.in_([e.history_key for e in entries])
            )
        )
    }

    max_viewed_at = cursor
    for entry in entries:
        if entry.history_key not in existing_keys:
            session.add(
                WatchHistory(
                    integration_id=integration.id,
                    history_key=entry.history_key,
                    item_key=entry.item_key,
                    grandparent_key=entry.grandparent_key,
                    media_type=entry.media_type,
                    title=entry.title,
                    grandparent_title=entry.grandparent_title,
                    season_index=entry.season_index,
                    episode_index=entry.episode_index,
                    poster_url=entry.poster_url,
                    grandparent_poster_url=entry.grandparent_poster_url,
                    viewed_at=entry.viewed_at,
                    synced_at=now,
                )
            )
        if max_viewed_at is None or entry.viewed_at > max_viewed_at:
            max_viewed_at = entry.viewed_at

    if max_viewed_at is not None:
        state.last_history_sync_at = max_viewed_at

    return len(entries)


def sync_integration(integration_id: int) -> None:
    now = datetime.utcnow()
    with get_session() as session:
        integration = session.get(Integration, integration_id)
        if integration is None:
            return

        state = session.get(SyncState, integration_id)
        if state is None:
            state = SyncState(integration_id=integration_id)
            session.add(state)

        try:
            history_count = _sync_history(session, integration, state, now)

            state.last_run_at = now
            state.last_run_status = "ok"
            state.last_run_error = None
            session.commit()
            logger.info(
                "sync completed for integration %s (%s): %d history rows fetched",
                integration.display_name,
                integration.provider,
                history_count,
            )
        except Exception as exc:
            session.rollback()
            logger.exception("sync failed for integration %s", integration.display_name)
            state = session.get(SyncState, integration_id) or SyncState(integration_id=integration_id)
            state.last_run_at = now
            state.last_run_status = "error"
            state.last_run_error = str(exc)
            session.add(state)
            session.commit()


def sync_all_integrations() -> None:
    with get_session() as session:
        integration_ids = list(session.scalars(select(Integration.id)))
    for integration_id in integration_ids:
        sync_integration(integration_id)
