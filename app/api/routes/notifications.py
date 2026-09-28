from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db_session
from app.models import Notification, User
from app.schemas.envelope import ApiResponse
from app.schemas.notifications import NotificationResponse

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=ApiResponse[list[NotificationResponse]])
async def list_notifications(
    before_id: int | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> ApiResponse[list[NotificationResponse]]:
    limit = min(max(limit, 1), 100)
    query = select(Notification).where(Notification.user_id == current_user.id)
    if before_id is not None:
        query = query.where(Notification.id < before_id)
    rows = (await db.execute(query.order_by(Notification.id.desc()).limit(limit))).scalars().all()
    data = [NotificationResponse.model_validate(n, from_attributes=True) for n in rows]
    return ApiResponse(data=data, meta={"next_before_id": rows[-1].id if len(rows) == limit else None})
