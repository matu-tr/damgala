import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.db import get_app_config, init_db
from app.routes import router
from app.scheduler import build_scheduler

logging.basicConfig(level=settings.log_level)

init_db()
app_config = get_app_config()

scheduler = build_scheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="Damgala", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=app_config.session_secret)
app.include_router(router)
