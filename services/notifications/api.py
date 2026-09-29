"""Notifications service HTTP API (M6).

Run:  uvicorn services.notifications.api:app --port 8300
"""
from fastapi import Depends, FastAPI
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import CardicheckError, register_exception_handlers
from app.core.request_id import install_request_id
from app.core.security import decode_access_token
from app.schemas.envelope import ApiResponse
from services.notifications.db import get_session
from services.notifications.models import Notification
from services.notifications.schemas import NotificationResponse

app = FastAPI(title="notifications-service")
register_exception_handlers(app)
install_request_id(app, "notifications")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def current_user_id(token: str = Depends(oauth2_scheme)) -> int:
    # M6: the service validates the JWT itself (shared signing secret) and never queries the
    # monolith's users table; the token's subject is all it needs.
    user_id = decode_access_token(token)
    if user_id is None:
        raise CardicheckError(status_code=401, code="INVALID_TOKEN", message="invalid or expired token")
    return user_id


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/notifications", response_model=ApiResponse[list[NotificationResponse]])
async def list_notifications(
    before_id: int | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_session),
    user_id: int = Depends(current_user_id),
) -> ApiResponse[list[NotificationResponse]]:
    limit = min(max(limit, 1), 100)
    query = select(Notification).where(Notification.user_id == user_id)
    if before_id is not None:
        query = query.where(Notification.id < before_id)
    rows = (await db.execute(query.order_by(Notification.id.desc()).limit(limit))).scalars().all()
    data = [NotificationResponse.model_validate(n, from_attributes=True) for n in rows]
    return ApiResponse(data=data, meta={"next_before_id": rows[-1].id if len(rows) == limit else None})
