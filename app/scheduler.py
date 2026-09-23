from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from app.sync import sync_all_integrations


def build_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        sync_all_integrations,
        "interval",
        minutes=settings.poll_interval_minutes,
        next_run_time=datetime.now(),
        id="plex_sync_job",
        max_instances=1,
        coalesce=True,
    )
    return scheduler
