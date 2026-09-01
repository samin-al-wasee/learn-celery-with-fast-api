from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db_session
from app.core.errors import CardicheckError
from app.models import User, UserRole
from app.schemas.envelope import ApiResponse
from app.schemas.users import ProfileResponse, ProfileUpdate

router = APIRouter(prefix="/users", tags=["users"])


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
    return ApiResponse(data=_profile(current_user))


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
    return ApiResponse(data=_profile(current_user))