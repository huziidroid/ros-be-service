"""
FastAPI dependencies shared across routers.

Centralised so routers never import Temporal SDK types directly.
"""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio.client import Client

from app.clients.redis import RedisClient, get_redis_client
from app.core.database import get_session
from app.core.security import decode_token
from app.models.user import User
from app.repositories.user_repo import UserRepo
from app.schemas.auth import TokenError


def get_temporal_client(request: Request) -> Client:
    """Inject the Temporal client; raises 503 if it wasn't initialised at startup."""
    client: Client | None = getattr(request.app.state, "temporal", None)
    if client is None:
        raise HTTPException(
            status_code=503,
            detail="Workflow engine unavailable. Please try again shortly.",
        )
    return client


TemporalDep = Annotated[Client, Depends(get_temporal_client)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
RedisDep = Annotated[RedisClient, Depends(get_redis_client)]


async def get_current_user(
    session: SessionDep,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """
    Resolve the authenticated user from the Bearer access token.

    Raises 401 for anything wrong with the token — missing header, bad
    scheme, expired/invalid signature, or a user_id that no longer exists.
    """
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401, detail="Missing or malformed Authorization header."
        )

    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = decode_token(token, expected_type="access")
    except TokenError as exc:
        raise HTTPException(
            status_code=401, detail="Invalid or expired access token."
        ) from exc

    user = await UserRepo(session).get_by_id(UUID(payload.user_id))
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired access token.")
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]
