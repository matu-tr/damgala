# Damgala

A self-hosted, multi-user web app that tracks your watch history (movies and
TV shows). You create an Damgala account and connect one or more watch-history
sources ("integrations") — Plex is the first supported one, with more
services plannable later. No Plex webhook / Plex Pass required; history is
pulled via periodic polling.

Plex data comes from `community.plex.tv`'s account-level Watch History
service — no local Plex Media Server connection needed.

## How auth works

- **Account**: sign up with an email + password, like any normal app.
- **Integrations**: from the Integrations page, click "Connect Plex" to link
  a Plex account via Plex's official OAuth (PIN) flow — Damgala never sees
  or stores your Plex password, only an access token. You can disconnect an
  integration at any time (this also deletes the watch history it supplied).
- **TMDB API key**: also set from the Integrations page (not an env var) —
  powers Watch Roulette and unwatched-episode listings. Get a free key at
  [themoviedb.org](https://www.themoviedb.org/settings/api).

## Local development

```bash
cp .env.example .env
docker compose up --build
```

Dashboard: http://localhost:8000 — sign up, then connect Plex from the
Integrations page.

## Image builds

Pushing a version tag (e.g. `v0.1.0`) triggers `.github/workflows/build.yml`,
which builds the image, pushes it to `ghcr.io/matu-tr/damgala:latest` (and
a matching `:vX.Y.Z` tag), and creates a GitHub Release for that tag. No
manual `docker build` step needed for deployment — just tag and push, then
pull the new image on the host.

## Installing as a TrueNAS SCALE Custom App

1. **Image**: `ghcr.io/matu-tr/damgala`, tag `latest`. Set Pull Policy to
   "Always pull" so restarts pick up newly published images.
2. **Storage**: in TrueNAS Apps, add an ixVolume (or Host Path Volume)
   mounted at `/data` inside the container. This is where the SQLite
   database (accounts, integrations, watch history) lives, so it survives
   app restarts/upgrades.
3. **Network**: map the container's port `8000` to a host port.
4. **Environment variables**: all optional, see the table below.
5. Start the app, open it in a browser, sign up and connect Plex.

To ship a code update: push to `main` (CI builds and publishes the image),
then restart the app from the TrueNAS Apps page to pull the fresh image —
Custom Apps don't reliably surface an "Update Available" badge on their own,
so a manual restart is the dependable way to pick it up.

## Upgrading from MTPSync

This project was renamed from MTPSync to Damgala. Two things moved with it:
the image is now `ghcr.io/matu-tr/damgala`, and the default database path
changed from `/data/mtpsync.db` to `/data/damgala.db`.

Your data is not touched by the rename — the volume still holds the same
SQLite file — but the app looks for the new filename and will otherwise come
up with an empty database, as if every account and all watch history had
vanished. Inside the mounted `/data` volume, rename the file once:

```bash
mv mtpsync.db damgala.db
```

If `mtpsync.db-wal` / `mtpsync.db-shm` sit next to it, rename those to match.
If you would rather not touch the file at all, set `DB_PATH=/data/mtpsync.db`
in the environment instead and the old name keeps working.

## Configuration (environment variables)

| Variable | Required | Default | Description |
|---|---|---|---|
| `POLL_INTERVAL_MINUTES` | no | 15 | How often each integration is synced |
| `DB_PATH` | no | `/data/damgala.db` | SQLite file path |
| `DASHBOARD_PORT` | no | 8000 | Uvicorn listen port |
| `HISTORY_LOOKBACK_DAYS` | no | 3650 | How far back to backfill on first sync |
| `LOG_LEVEL` | no | INFO | Python log level |

## How it works

- **Accounts vs. integrations**: `users` holds login credentials only.
  `integrations` holds connected external accounts (currently just Plex),
  each with its own access token, linked to a user. This keeps room to add
  other watch-history providers later without touching the auth model.
- **Watch history**: for each integration, pulled from `community.plex.tv`'s
  GraphQL API (`GetWatchHistoryHub` query) — account-level, independent of
  any particular server — newest-first, paginating back to that
  integration's `sync_state.last_history_sync_at` cursor. Stored in
  `watch_history` (append-only until explicitly deleted).
- **Movies**: grouped by `item_key`, showing watch count and first/last
  watched date.
- **Shows**: grouped by episodes' `grandparent_key` (show-level summary);
  clicking through shows a season-by-season list of watched episodes.
- **Deleting history**: each card has a delete button that removes all
  watch-history rows for that movie or show; individual episodes can be
  deleted from a show's detail page.
- **Background sync**: APScheduler runs a sync for every integration, across
  all users, every `POLL_INTERVAL_MINUTES`.
- **Watch Roulette**: suggests a random all-time top-rated movie/show from TMDB and asks
  whether you've watched it. A "yes" is recorded under a per-user virtual
  "manual" integration, with no watched date (not knowable for a
  self-reported entry).
