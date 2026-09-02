from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db_session
from app.core.errors import CardicheckError
from app.core.redis import cache_delete, cache_get, cache_set
from app.models import User, UserRole
from app.schemas.envelope import ApiResponse
from app.schemas.users import ProfileResponse, ProfileUpdate

router = APIRouter(prefix="/users", tags=["users"])

# M2! Redis read-through cache on the hot profile read.
# - Read path: GET /users/me -> Redis miss -> build from DB -> cache with TTL.
# - Write path: PATCH /users/me -> delete the key (delete-over-update).
PROFILE_KEY = "profile:{user_id}"


def _profile(user: User) -> ProfileResponse:
    return ProfileResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        specialty=user.specialty,
        phone=user.phone,
    )


@router.get("/me", response_model=ApiResponse[ProfileResponse])
async def get_me(current_user: User = Depends(get_current_user)) -> ApiResponse[ProfileResponse]:
    key = PROFILE_KEY.format(user_id=current_user.id)
    cached = await cache_get(key)
    if cached is not None:
        return ApiResponse(data=cached)
    data = _profile(current_user).model_dump(mode="json")
    await cache_set(key, data)
    return ApiResponse(data=data)


@router.patch("/me", response_model=ApiResponse[ProfileResponse])
async def update_me(
    payload: ProfileUpdate,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> ApiResponse[ProfileResponse]:
    updates = payload.model_dump(exclude_unset=True)

    # Role-aware field: a specialty only exists for doctors.
    if "specialty" in updates and current_user.role != UserRole.DOCTOR:
        raise CardicheckError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="FORBIDDEN",
            message="only doctors have a specialty",
        )

    for field, value in updates.items():
        setattr(current_user, field, value)
    await db.commit()
    await db.refresh(current_user)
    # M2: invalidate the cached profile so the next read is fresh.
    await cache_delete(PROFILE_KEY.format(user_id=current_user.id))
    return ApiResponse(data=_profile(current_user))