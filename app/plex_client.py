import logging
from dataclasses import dataclass
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

PRODUCT_NAME = "Damgala"

PINS_URL = "https://plex.tv/api/v2/pins"
ACCOUNT_INFO_URL = "https://plex.tv/api/v2/user"
COMMUNITY_API_URL = "https://community.plex.tv/api"

# Captured verbatim from app.plex.tv's own "Watch History" page network
# traffic — this is the account-level history feed (works across every
# server the account has ever used, including ones no longer online),
# not the local-server-only /status/sessions/history/all endpoint.
WATCH_HISTORY_QUERY = """
    query GetWatchHistoryHub($uuid: ID = "", $first: PaginationInt!, $after: String, $skipUserState: Boolean = false) {
  user(id: $uuid) {
    watchHistory(first: $first, after: $after) {
      nodes {
        metadataItem {
          ...itemFields
        }
        date
        id
      }
      pageInfo {
        hasNextPage
        hasPreviousPage
        endCursor
      }
    }
  }
}

    fragment itemFields on MetadataItem {
  id
  images {
    coverArt
    coverPoster
    thumbnail
    art
  }
  userState @skip(if: $skipUserState) {
    viewCount
    viewedLeafCount
    watchlistedAt
  }
  title
  key
  type
  index
  publicPagesURL
  parent {
    ...parentFields
  }
  grandparent {
    ...parentFields
  }
  publishedAt
  leafCount
  year
  originallyAvailableAt
  childCount
}

    fragment parentFields on MetadataItem {
  index
  title
  publishedAt
  key
  type
  images {
    coverArt
    coverPoster
    thumbnail
    art
  }
  userState @skip(if: $skipUserState) {
    viewCount
    viewedLeafCount
    watchlistedAt
  }
}
    """


@dataclass
class HistoryEntry:
    history_key: str
    item_key: str
    grandparent_key: str | None
    media_type: str  # 'movie' | 'episode'
    title: str | None
    grandparent_title: str | None
    season_index: int | None
    episode_index: int | None
    poster_url: str | None
    grandparent_poster_url: str | None
    viewed_at: datetime


@dataclass
class AccountInfo:
    uuid: str
    username: str
    email: str | None
    thumb_url: str | None


def _poster_url(images: dict | None) -> str | None:
    if not images:
        return None
    return images.get("coverPoster") or images.get("thumbnail")


def create_pin(client_identifier: str) -> dict:
    """Starts a Plex OAuth login: returns a {id, code, ...} dict.

    The caller sends the user to the Plex auth page built from `code`; once
    the user approves, `check_pin` will return an authToken for this pin id.
    """
    resp = requests.post(
        PINS_URL,
        json={"strong": True},
        headers={
            "X-Plex-Client-Identifier": client_identifier,
            "X-Plex-Product": PRODUCT_NAME,
            "Accept": "application/json",
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def check_pin(pin_id: int, client_identifier: str) -> str | None:
    """Returns the auth token once the user has approved the pin, else None."""
    resp = requests.get(
        f"{PINS_URL}/{pin_id}",
        headers={
            "X-Plex-Client-Identifier": client_identifier,
            "Accept": "application/json",
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json().get("authToken") or None


def fetch_account_info(token: str) -> AccountInfo:
    resp = requests.get(
        ACCOUNT_INFO_URL,
        headers={"X-Plex-Token": token, "Accept": "application/json"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    return AccountInfo(
        uuid=data["uuid"],
        username=data["username"],
        email=data.get("email"),
        thumb_url=data.get("thumb"),
    )


def _fetch_watch_history_page(token: str, uuid: str, after: str | None, first: int = 100) -> dict:
    payload = {
        "query": WATCH_HISTORY_QUERY,
        "variables": {"first": first, "uuid": uuid, "after": after, "skipUserState": True},
        "operationName": "GetWatchHistoryHub",
    }
    resp = requests.post(
        COMMUNITY_API_URL,
        json=payload,
        headers={
            "X-Plex-Token": token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["data"]["user"]["watchHistory"]


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")


def fetch_history(token: str, uuid: str, mindate: datetime) -> list[HistoryEntry]:
    entries: list[HistoryEntry] = []
    after: str | None = None

    while True:
        page = _fetch_watch_history_page(token, uuid, after)
        reached_mindate = False

        for node in page["nodes"]:
            viewed_at = _parse_date(node["date"])
            if viewed_at < mindate:
                reached_mindate = True
                break

            item = node["metadataItem"]
            item_type = item["type"]  # "MOVIE" | "EPISODE" | ...
            if item_type not in ("MOVIE", "EPISODE"):
                continue

            grandparent = item.get("grandparent")
            parent = item.get("parent")
            entries.append(
                HistoryEntry(
                    history_key=f"community:{node['id']}",
                    item_key=item["key"],
                    grandparent_key=grandparent["key"] if grandparent else None,
                    media_type="movie" if item_type == "MOVIE" else "episode",
                    title=item["title"],
                    grandparent_title=grandparent["title"] if grandparent else None,
                    season_index=parent["index"] if parent else None,
                    episode_index=item["index"] if item_type == "EPISODE" else None,
                    poster_url=_poster_url(item.get("images")),
                    grandparent_poster_url=_poster_url(grandparent.get("images") if grandparent else None),
                    viewed_at=viewed_at,
                )
            )

        page_info = page["pageInfo"]
        if reached_mindate or not page_info["hasNextPage"]:
            break
        after = page_info["endCursor"]

    logger.info("fetched %d history rows since %s", len(entries), mindate)
    return entries
