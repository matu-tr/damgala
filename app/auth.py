from datetime import datetime
from urllib.parse import urlencode

import bcrypt
from fastapi import Request
from sqlalchemy import select

from app.db import get_session
from app.models import Integration, User
from app.plex_client import PRODUCT_NAME, check_pin, create_pin, fetch_account_info

PLEX_AUTH_BASE_URL = "https://app.plex.tv/auth#"


# --- account auth (email + password) -----------------------------------


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_user(email: str, password: str) -> User | None:
    with get_session() as session:
        if session.scalar(select(User).where(User.email == email)) is not None:
            return None
        user = User(email=email, password_hash=hash_password(password), created_at=datetime.utcnow())
        session.add(user)
        session.commit()
        session.refresh(user)
        return user


def authenticate_user(email: str, password: str) -> User | None:
    with get_session() as session:
        user = session.scalar(select(User).where(User.email == email))
        if user is None or not verify_password(password, user.password_hash):
            return None
        return user


def current_user(request: Request) -> User | None:
    user_id = request.session.get("user_id")
    if user_id is None:
        return None
    with get_session() as session:
        return session.get(User, user_id)


def log_in(request: Request, user: User) -> None:
    request.session["user_id"] = user.id


def log_out(request: Request) -> None:
    request.session.pop("user_id", None)


# --- Plex integration (connect an external account, not a login) -------


def start_plex_connect(client_identifier: str, forward_url: str) -> tuple[int, str]:
    """Creates a Plex OAuth pin and returns (pin_id, auth_url_to_redirect_to)."""
    pin = create_pin(client_identifier)
    params = {
        "clientID": client_identifier,
        "code": pin["code"],
        "forwardUrl": forward_url,
        "context[device][product]": PRODUCT_NAME,
    }
    auth_url = f"{PLEX_AUTH_BASE_URL}?{urlencode(params)}"
    return pin["id"], auth_url


def complete_plex_connect(pin_id: int, client_identifier: str, user_id: int) -> Integration | None:
    """Polls the pin once; if approved, links a Plex Integration to user_id."""
    token = check_pin(pin_id, client_identifier)
    if token is None:
        return None

    info = fetch_account_info(token)
    now = datetime.utcnow()

    with get_session() as session:
        integration = session.scalar(
            select(Integration).where(
                Integration.provider == "plex",
                Integration.external_id == info.uuid,
            )
        )
        if integration is None:
            integration = Integration(
                user_id=user_id,
                provider="plex",
                external_id=info.uuid,
                display_name=info.username,
                thumb_url=info.thumb_url,
                access_token=token,
                connected_at=now,
            )
            session.add(integration)
        else:
            integration.user_id = user_id
            integration.display_name = info.username
            integration.thumb_url = info.thumb_url
            integration.access_token = token
        session.commit()
        session.refresh(integration)
        return integration


# --- self-reported entries (e.g. from Watch Roulette) -----------------


def get_or_create_manual_integration(session, user_id: int) -> Integration:
    """A virtual, provider='manual' integration each user has for entries
    they confirm themselves rather than sync from a real provider."""
    external_id = f"user-{user_id}"
    integration = session.scalar(
        select(Integration).where(
            Integration.provider == "manual",
            Integration.external_id == external_id,
        )
    )
    if integration is None:
        integration = Integration(
            user_id=user_id,
            provider="manual",
            external_id=external_id,
            display_name="Manually added",
            access_token="",
            connected_at=datetime.utcnow(),
        )
        session.add(integration)
        session.commit()
        session.refresh(integration)
    return integration
