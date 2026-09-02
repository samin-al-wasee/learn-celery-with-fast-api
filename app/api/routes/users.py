from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.cache import get_db_fetch_count, read_through
from app.core.database import get_db_session
from app.core.errors import CardicheckError
from app.core.redis import cache_delete
from app.models import User, UserRole
from app.schemas.envelope import ApiResponse
from app.schemas.users import ProfileResponse, ProfileUpdate

router = APIRouter(prefix="/users", tags=["users"])

# M2! Redis read-through cache on the hot profile read.
# - Read path: GET /users/me -> read_through (Redis miss -> DB -> cache).
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
async def get_me(
    response: Response,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> ApiResponse[ProfileResponse]:
    key = PROFILE_KEY.format(user_id=current_user.id)

    # The loader is the *expensive read the cache protects*: a real DB select.
    # (Making it a genuine I/O read is what lets us observe a stampede.)
    async def load_profile() -> dict:
        row = (
            await db.execute(select(User).where(User.id == current_user.id))
        ).scalar_one()
        return _profile(row).model_dump(mode="json")

    data, _was_miss = await read_through(key, load_profile)
    # M2 observability: expose the DB-fetch (miss) counter so observe_stampede.py
    # can measure how many readers hit the datastore in a concurrent burst.
    response.headers["X-Cache-Miss-Count"] = str(get_db_fetch_count())
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