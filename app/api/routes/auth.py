import time

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.database import naive_sync_session_factory
from app.core.security import hash_password
from app.models import User
from app.schemas.auth import SignupRequest, SignupResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
async def signup_naive(payload: SignupRequest) -> SignupResponse:
    # NAIVE (deliberate mistake, see LEARNING.md M1): a blocking sync session
    # + time.sleep inside an async endpoint freezes the entire event loop.
    with naive_sync_session_factory() as db:
        time.sleep(2)
        exists = db.execute(select(User).where(User.email == payload.email)).scalar_one_or_none()
        if exists is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="email already registered")
        user = User(
            email=str(payload.email),
            hashed_password=hash_password(payload.password),
            full_name=payload.full_name,
            role=payload.role,
            specialty=payload.specialty,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return SignupResponse(id=user.id, email=user.email, full_name=user.full_name, role=user.role)