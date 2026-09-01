from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.models import User
from app.schemas.auth import SignupResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=SignupResponse)
async def get_me(current_user: User = Depends(get_current_user)) -> SignupResponse:
    return SignupResponse(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        role=current_user.role,
    )