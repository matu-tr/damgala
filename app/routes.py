import random
import time
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, select

from app.auth import (
    authenticate_user,
    complete_plex_connect,
    create_user,
    current_user,
    get_or_create_manual_integration,
    log_in,
    log_out,
    start_plex_connect,
)
from app.db import get_app_config, get_session, set_tmdb_api_key
from app.models import Integration, SyncState, WatchHistory
from app.sync import sync_integration
from app.tmdb_client import fetch_full_episode_catalog, fetch_random_top_rated

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

SORT_FIELDS = {
    "title": lambda row: (row["title"] or "").lower(),
    "last_watched": lambda row: row["last_watched"] or datetime.min,
}


@router.get("/healthz")
def healthz():
    return {"status": "ok"}


# --- account auth (email + password) --------------------------------------


@router.get("/signup")
def signup_form(request: Request):
    if current_user(request) is not None:
        return RedirectResponse(url="/")
    return templates.TemplateResponse(request, "signup.html", {"error": None})


@router.post("/signup")
def signup_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
):
    if password != confirm_password:
        return templates.TemplateResponse(
            request, "signup.html", {"error": "Passwords do not match."}, status_code=400
        )
    if len(password) < 8:
        return templates.TemplateResponse(
            request,
            "signup.html",
            {"error": "Password must be at least 8 characters."},
            status_code=400,
        )
    user = create_user(email.strip().lower(), password)
    if user is None:
        return templates.TemplateResponse(
            request,
            "signup.html",
            {"error": "An account with that email already exists."},
            status_code=400,
        )
    log_in(request, user)
    return RedirectResponse(url="/integrations", status_code=303)


@router.get("/login")
def login_form(request: Request):
    if current_user(request) is not None:
        return RedirectResponse(url="/")
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
def login_submit(request: Request, email: str = Form(...), password: str = Form(...)):
    user = authenticate_user(email.strip().lower(), password)
    if user is None:
        return templates.TemplateResponse(
            request, "login.html", {"error": "Invalid email or password."}, status_code=400
        )
    log_in(request, user)
    return RedirectResponse(url="/", status_code=303)


@router.post("/logout")
def logout(request: Request):
    log_out(request)
    return RedirectResponse(url="/login", status_code=303)


# --- integrations (connected watch-history sources, e.g. Plex) ------------


@router.get("/integrations")
def integrations_page(request: Request):
    user = current_user(request)
    if user is None:
        return RedirectResponse(url="/login")
    with get_session() as session:
        integrations = list(
            session.scalars(
                select(Integration).where(
                    Integration.user_id == user.id, Integration.provider != "manual"
                )
            )
        )
    tmdb_api_key = get_app_config().tmdb_api_key
    return templates.TemplateResponse(
        request,
        "integrations.html",
        {"user": user, "integrations": integrations, "tmdb_api_key": tmdb_api_key},
    )


@router.post("/settings/tmdb")
def update_tmdb_key(request: Request, tmdb_api_key: str = Form("")):
    user = current_user(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    set_tmdb_api_key(tmdb_api_key.strip())
    return RedirectResponse(url="/integrations", status_code=303)


@router.get("/integrations/plex/connect")
def plex_connect(request: Request):
    user = current_user(request)
    if user is None:
        return RedirectResponse(url="/login")
    config = get_app_config()
    forward_url = str(request.base_url).rstrip("/") + "/integrations/plex/callback"
    pin_id, auth_url = start_plex_connect(config.client_identifier, forward_url)
    request.session["pending_pin_id"] = pin_id
    return RedirectResponse(url=auth_url)


@router.get("/integrations/plex/callback")
def plex_callback(request: Request):
    user = current_user(request)
    if user is None:
        return RedirectResponse(url="/login")

    pin_id = request.session.get("pending_pin_id")
    if pin_id is None:
        return RedirectResponse(url="/integrations")

    config = get_app_config()
    integration = None
    for _ in range(5):
        integration = complete_plex_connect(pin_id, config.client_identifier, user.id)
        if integration is not None:
            break
        time.sleep(1)

    request.session.pop("pending_pin_id", None)

    if integration is None:
        return templates.TemplateResponse(request, "connect_failed.html", {}, status_code=400)

    sync_integration(integration.id)
    return RedirectResponse(url="/integrations")


@router.post("/integrations/{integration_id}/disconnect")
def disconnect_integration(request: Request, integration_id: int):
    user = current_user(request)
    if user is None:
        return RedirectResponse(url="/login")
    with get_session() as session:
        integration = session.get(Integration, integration_id)
        if integration is not None and integration.user_id == user.id:
            session.execute(delete(WatchHistory).where(WatchHistory.integration_id == integration_id))
            session.execute(delete(SyncState).where(SyncState.integration_id == integration_id))
            session.delete(integration)
            session.commit()
    return RedirectResponse(url="/integrations", status_code=303)


@router.post("/api/sync")
def trigger_sync(request: Request):
    user = current_user(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    with get_session() as session:
        integration_ids = list(
            session.scalars(select(Integration.id).where(Integration.user_id == user.id))
        )
    for integration_id in integration_ids:
        sync_integration(integration_id)
    return RedirectResponse(url="/", status_code=303)


# --- history deletion -------------------------------------------------------


@router.post("/history/delete")
def delete_history(request: Request, media_type: str = Form(...), key: str = Form(...)):
    user = current_user(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    with get_session() as session:
        integration_ids = select(Integration.id).where(Integration.user_id == user.id)
        if media_type == "movie":
            session.execute(
                delete(WatchHistory).where(
                    WatchHistory.integration_id.in_(integration_ids),
                    WatchHistory.item_key == key,
                    WatchHistory.media_type == "movie",
                )
            )
        else:
            session.execute(
                delete(WatchHistory).where(
                    WatchHistory.integration_id.in_(integration_ids),
                    WatchHistory.grandparent_key == key,
                )
            )
        session.commit()
    referer = request.headers.get("referer", "/")
    return RedirectResponse(url=referer, status_code=303)


@router.post("/history/delete-episode")
def delete_episode(request: Request, item_key: str = Form(...)):
    user = current_user(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    with get_session() as session:
        integration_ids = select(Integration.id).where(Integration.user_id == user.id)
        session.execute(
            delete(WatchHistory).where(
                WatchHistory.integration_id.in_(integration_ids),
                WatchHistory.item_key == item_key,
                WatchHistory.media_type == "episode",
            )
        )
        session.commit()
    referer = request.headers.get("referer", "/")
    return RedirectResponse(url=referer, status_code=303)


# --- dashboard ---------------------------------------------------------------


def _movie_rows(session, integration_ids) -> list[dict]:
    stmt = (
        select(
            WatchHistory.item_key,
            func.max(WatchHistory.title).label("title"),
            func.max(WatchHistory.poster_url).label("poster_url"),
            func.count(WatchHistory.id).label("watch_count"),
            func.min(WatchHistory.viewed_at).label("first_watched"),
            func.max(WatchHistory.viewed_at).label("last_watched"),
        )
        .where(WatchHistory.integration_id.in_(integration_ids), WatchHistory.media_type == "movie")
        .group_by(WatchHistory.item_key)
    )
    return [
        {
            "media_type": "movie",
            "key": row.item_key,
            "title": row.title,
            "poster_url": row.poster_url,
            "episodes_watched": None,
            "watch_count": row.watch_count,
            "first_watched": row.first_watched,
            "last_watched": row.last_watched,
        }
        for row in session.execute(stmt)
    ]


def _show_rows(session, integration_ids) -> list[dict]:
    stmt = (
        select(
            WatchHistory.grandparent_key,
            func.max(WatchHistory.grandparent_title).label("title"),
            func.max(WatchHistory.grandparent_poster_url).label("poster_url"),
            func.count(func.distinct(WatchHistory.item_key)).label("episodes_watched"),
            func.min(WatchHistory.viewed_at).label("first_watched"),
            func.max(WatchHistory.viewed_at).label("last_watched"),
        )
        .where(
            WatchHistory.integration_id.in_(integration_ids),
            WatchHistory.media_type == "episode",
            WatchHistory.grandparent_key.is_not(None),
        )
        .group_by(WatchHistory.grandparent_key)
    )
    return [
        {
            "media_type": "show",
            "key": row.grandparent_key,
            "title": row.title,
            "poster_url": row.poster_url,
            "episodes_watched": row.episodes_watched,
            "watch_count": None,
            "first_watched": row.first_watched,
            "last_watched": row.last_watched,
        }
        for row in session.execute(stmt)
    ]


@router.get("/")
def dashboard(request: Request, type: str = Query("movie"), sort: str = Query("last_watched")):
    user = current_user(request)
    if user is None:
        return templates.TemplateResponse(request, "landing.html", {})

    with get_session() as session:
        integration_ids = select(Integration.id).where(Integration.user_id == user.id)
        has_integration = (
            session.scalar(
                select(Integration.id).where(Integration.user_id == user.id).limit(1)
            )
            is not None
        )

        rows = _movie_rows(session, integration_ids) if type == "movie" else _show_rows(session, integration_ids)

        sort_key = SORT_FIELDS.get(sort, SORT_FIELDS["last_watched"])
        rows.sort(key=sort_key, reverse=(sort == "last_watched"))

        sync_states = list(
            session.scalars(select(SyncState).where(SyncState.integration_id.in_(integration_ids)))
        )
        last_run_at = max((s.last_run_at for s in sync_states if s.last_run_at), default=None)

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "rows": rows,
            "last_run_at": last_run_at,
            "user": user,
            "has_integration": has_integration,
            "filters": {"type": type, "sort": sort},
        },
    )


# --- show detail (episode watched/unwatched breakdown) ----------------------


@router.get("/show")
def show_detail(request: Request, key: str = Query(...)):
    user = current_user(request)
    if user is None:
        return RedirectResponse(url="/login")

    with get_session() as session:
        integration_ids = select(Integration.id).where(Integration.user_id == user.id)
        stmt = (
            select(WatchHistory)
            .where(
                WatchHistory.integration_id.in_(integration_ids),
                WatchHistory.grandparent_key == key,
                WatchHistory.media_type == "episode",
            )
            .order_by(WatchHistory.season_index, WatchHistory.episode_index)
        )
        watched_episodes = list(session.scalars(stmt))

    if not watched_episodes:
        return RedirectResponse(url="/?type=show")

    show_title = watched_episodes[0].grandparent_title
    poster_url = watched_episodes[0].grandparent_poster_url

    watched_by_season_ep: dict[tuple[int, int], WatchHistory] = {}
    for ep in watched_episodes:
        if ep.season_index is not None and ep.episode_index is not None:
            watched_by_season_ep[(ep.season_index, ep.episode_index)] = ep

    tmdb_api_key = get_app_config().tmdb_api_key
    full_catalog = None
    if tmdb_api_key and show_title:
        full_catalog = fetch_full_episode_catalog(tmdb_api_key, show_title)

    seasons: dict[int, list[dict]] = {}
    if full_catalog:
        all_keys = set(full_catalog.keys()) | set(watched_by_season_ep.keys())
        for season_number, episode_number in all_keys:
            watched = watched_by_season_ep.get((season_number, episode_number))
            seasons.setdefault(season_number, []).append(
                {
                    "episode_index": episode_number,
                    "title": full_catalog.get(
                        (season_number, episode_number), watched.title if watched else None
                    ),
                    "watched": watched is not None,
                    "viewed_at": watched.viewed_at if watched else None,
                    "item_key": watched.item_key if watched else None,
                }
            )
        for episodes in seasons.values():
            episodes.sort(key=lambda e: e["episode_index"])
    else:
        for ep in watched_episodes:
            seasons.setdefault(ep.season_index or 0, []).append(
                {
                    "episode_index": ep.episode_index,
                    "title": ep.title,
                    "watched": True,
                    "viewed_at": ep.viewed_at,
                    "item_key": ep.item_key,
                }
            )

    return templates.TemplateResponse(
        request,
        "show_detail.html",
        {
            "show_title": show_title,
            "poster_url": poster_url,
            "seasons": sorted(seasons.items()),
            "full_catalog_available": full_catalog is not None,
        },
    )


# --- watch roulette -----------------------------------------------------


def _already_in_history(session, integration_ids, media_type: str, title: str) -> bool:
    """Best-effort check across ALL of the user's history (not just
    Roulette-confirmed entries) so already-watched titles aren't re-asked
    about. Matches by title since synced sources (e.g. Plex) don't carry a
    TMDB id we can join on."""
    if media_type == "movie":
        stmt = select(WatchHistory.id).where(
            WatchHistory.integration_id.in_(integration_ids),
            WatchHistory.media_type == "movie",
            func.lower(WatchHistory.title) == title.lower(),
        )
    else:
        stmt = select(WatchHistory.id).where(
            WatchHistory.integration_id.in_(integration_ids),
            WatchHistory.media_type == "episode",
            func.lower(WatchHistory.grandparent_title) == title.lower(),
        )
    return session.scalar(stmt.limit(1)) is not None


@router.get("/roulette")
def roulette(request: Request):
    user = current_user(request)
    if user is None:
        return RedirectResponse(url="/login")

    tmdb_api_key = get_app_config().tmdb_api_key
    if not tmdb_api_key:
        return templates.TemplateResponse(request, "roulette.html", {"item": None, "no_tmdb": True})

    tmdb_media_type = random.choice(["movie", "tv"])
    item = None
    with get_session() as session:
        integration = get_or_create_manual_integration(session, user.id)
        integration_ids = select(Integration.id).where(Integration.user_id == user.id)
        for _ in range(8):
            candidate = fetch_random_top_rated(tmdb_api_key, tmdb_media_type)
            if candidate is None:
                continue
            history_key = f"roulette:{tmdb_media_type}:{candidate['tmdb_id']}:{integration.id}"
            already_confirmed = session.scalar(
                select(WatchHistory.id).where(WatchHistory.history_key == history_key)
            )
            already_watched = candidate["title"] and _already_in_history(
                session,
                integration_ids,
                "movie" if tmdb_media_type == "movie" else "show",
                candidate["title"],
            )
            if already_confirmed is None and not already_watched:
                item = {
                    **candidate,
                    "media_type": "movie" if tmdb_media_type == "movie" else "show",
                }
                break

    return templates.TemplateResponse(
        request,
        "roulette.html",
        {"item": item, "no_tmdb": False, "recent": request.session.get("roulette_recent", [])},
    )


def _remember_recent_answer(
    request: Request, media_type: str, tmdb_id: int, title: str, poster_url: str, watched: bool
) -> None:
    """Keeps the last few answered items in the session so a misclick
    ("Not yet" on something actually watched, or vice versa) can be
    corrected from the roulette page without hunting through history."""
    recent = [
        r
        for r in request.session.get("roulette_recent", [])
        if not (r["tmdb_id"] == tmdb_id and r["media_type"] == media_type)
    ]
    recent.insert(
        0,
        {
            "tmdb_id": tmdb_id,
            "media_type": media_type,
            "title": title,
            "poster_url": poster_url,
            "watched": watched,
        },
    )
    request.session["roulette_recent"] = recent[:3]


@router.post("/roulette/answer")
def roulette_answer(
    request: Request,
    media_type: str = Form(...),
    tmdb_id: int = Form(...),
    title: str = Form(...),
    poster_url: str = Form(""),
    watched: str = Form(...),
):
    user = current_user(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)

    now = datetime.utcnow()
    tmdb_media_type = "movie" if media_type == "movie" else "tv"
    with get_session() as session:
        integration = get_or_create_manual_integration(session, user.id)
        history_key = f"roulette:{tmdb_media_type}:{tmdb_id}:{integration.id}"
        exists = session.scalar(select(WatchHistory.id).where(WatchHistory.history_key == history_key))

        if watched == "yes" and exists is None:
            if media_type == "movie":
                session.add(
                    WatchHistory(
                        integration_id=integration.id,
                        history_key=history_key,
                        item_key=f"tmdb:movie:{tmdb_id}",
                        grandparent_key=None,
                        media_type="movie",
                        title=title,
                        grandparent_title=None,
                        season_index=None,
                        episode_index=None,
                        poster_url=poster_url or None,
                        grandparent_poster_url=None,
                        viewed_at=None,
                        synced_at=now,
                    )
                )
            else:
                session.add(
                    WatchHistory(
                        integration_id=integration.id,
                        history_key=history_key,
                        item_key=f"tmdb:show:{tmdb_id}",
                        grandparent_key=f"tmdb:show:{tmdb_id}",
                        media_type="episode",
                        title=title,
                        grandparent_title=title,
                        season_index=None,
                        episode_index=None,
                        poster_url=poster_url or None,
                        grandparent_poster_url=poster_url or None,
                        viewed_at=None,
                        synced_at=now,
                    )
                )
            session.commit()
        elif watched == "no" and exists is not None:
            session.execute(delete(WatchHistory).where(WatchHistory.history_key == history_key))
            session.commit()

    _remember_recent_answer(request, media_type, tmdb_id, title, poster_url, watched == "yes")
    return RedirectResponse(url="/roulette", status_code=303)
