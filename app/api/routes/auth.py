from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db_session
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User
from app.schemas.auth import LoginRequest, SignupRequest, SignupResponse, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    payload: SignupRequest,
    db: AsyncSession = Depends(get_db_session),
) -> SignupResponse:
    existing = (
        await db.execute(select(User).where(User.email == payload.email))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="email already registered")
    user = User(
        email=str(payload.email),
        hashed_password=await run_in_threadpool(hash_password, payload.password),
        full_name=payload.full_name,
        role=payload.role,
        specialty=payload.specialty,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return SignupResponse(id=user.id, email=user.email, full_name=user.full_name, role=user.role)


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db_session),
) -> TokenResponse:
    # argon2 is deliberately CPU-slow (~30ms per verify); running it on the
    # event loop stalls every concurrent request. Delegate to the threadpool.
    user = (
        await db.execute(select(User).where(User.email == payload.email))
    ).scalar_one_or_none()
    ok = user is not None and await run_in_threadpool(
        verify_password, payload.password, user.hashed_password
    )
    if not ok:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid email or password")
    return TokenResponse(access_token=create_access_token(user.id))