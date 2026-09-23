import logging
import random

import requests

logger = logging.getLogger(__name__)

TMDB_API_BASE = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/original"


def search_show(api_key: str, title: str) -> int | None:
    resp = requests.get(
        f"{TMDB_API_BASE}/search/tv",
        params={"api_key": api_key, "query": title},
        timeout=10,
    )
    resp.raise_for_status()
    results = resp.json().get("results") or []
    return results[0]["id"] if results else None


def fetch_season_numbers(api_key: str, tmdb_id: int) -> list[int]:
    resp = requests.get(f"{TMDB_API_BASE}/tv/{tmdb_id}", params={"api_key": api_key}, timeout=10)
    resp.raise_for_status()
    seasons = resp.json().get("seasons") or []
    return [s["season_number"] for s in seasons if s["season_number"] > 0]


def fetch_season_episodes(api_key: str, tmdb_id: int, season_number: int) -> list[dict]:
    resp = requests.get(
        f"{TMDB_API_BASE}/tv/{tmdb_id}/season/{season_number}",
        params={"api_key": api_key},
        timeout=10,
    )
    resp.raise_for_status()
    episodes = resp.json().get("episodes") or []
    return [{"episode_number": e["episode_number"], "name": e["name"]} for e in episodes]


def fetch_full_episode_catalog(api_key: str, show_title: str) -> dict[tuple[int, int], str] | None:
    """Returns {(season_number, episode_number): episode_name} for a show, or
    None if no TMDB match was found."""
    try:
        tmdb_id = search_show(api_key, show_title)
        if tmdb_id is None:
            return None
        catalog: dict[tuple[int, int], str] = {}
        for season_number in fetch_season_numbers(api_key, tmdb_id):
            for ep in fetch_season_episodes(api_key, tmdb_id, season_number):
                catalog[(season_number, ep["episode_number"])] = ep["name"]
        return catalog
    except requests.RequestException:
        logger.exception("TMDB lookup failed for %r", show_title)
        return None


MIN_VOTE_COUNT = {"movie": 5000, "tv": 1000}


def fetch_random_top_rated(api_key: str, media_type: str) -> dict | None:
    """media_type: 'movie' or 'tv'. Returns a random title from TMDB,
    sorted by rating but restricted to titles with a high vote count —
    this approximates an "IMDb Top 250"-style list of widely-known
    acclaimed titles, rather than TMDB's plain top_rated endpoint which
    also surfaces obscure titles with few but highly favorable votes.
    Returns None on failure."""
    try:
        page = random.randint(1, 10)
        resp = requests.get(
            f"{TMDB_API_BASE}/discover/{media_type}",
            params={
                "api_key": api_key,
                "sort_by": "vote_average.desc",
                "vote_count.gte": MIN_VOTE_COUNT[media_type],
                "page": page,
            },
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json().get("results") or []
        if not results:
            return None
        item = random.choice(results)
        poster_path = item.get("poster_path")
        return {
            "tmdb_id": item["id"],
            "title": item.get("title") or item.get("name"),
            "poster_url": f"{TMDB_IMAGE_BASE}{poster_path}" if poster_path else None,
        }
    except requests.RequestException:
        logger.exception("TMDB top-rated lookup failed for %r", media_type)
        return None
