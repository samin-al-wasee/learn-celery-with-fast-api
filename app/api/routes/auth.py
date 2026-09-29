import logging

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.database import get_db_session
from app.core.errors import CardicheckError
from app.core.rate_limit import record_failure, retry_after
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User
from app.schemas.auth import LoginRequest, SignupRequest, SignupResponse, TokenResponse
from app.schemas.envelope import ApiResponse
from app.worker.tasks import send_welcome_email

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger("uvicorn.error")


@router.post("/signup", response_model=ApiResponse[SignupResponse], status_code=status.HTTP_201_CREATED)
async def signup(
    payload: SignupRequest,
    db: AsyncSession = Depends(get_db_session),
) -> ApiResponse[SignupResponse]:
    existing = (
        await db.execute(select(User).where(User.email == payload.email))
    ).scalar_one_or_none()
    if existing is not None:
        raise CardicheckError(
            status_code=status.HTTP_409_CONFLICT,
            code="EMAIL_ALREADY_REGISTERED",
            message="email already registered",
        )
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
    # M3: publish to RabbitMQ; .delay() is blocking network I/O, so it runs off the loop.
    # Publish after commit can still be lost if the broker is down (fix: transactional outbox, M6).
    try:
        await run_in_threadpool(send_welcome_email.delay, user.id)
    except Exception:
        logger.exception("welcome email not enqueued user_id=%s", user.id)
    return ApiResponse(
        data=SignupResponse(id=user.id, email=user.email, full_name=user.full_name, role=user.role)
    )


@router.post("/login", response_model=ApiResponse[TokenResponse])
async def login(
    payload: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> ApiResponse[TokenResponse]:
    key = f"{request.client.host if request.client else '-'}:{str(payload.email).lower()}"
    # M8: check the limit BEFORE the DB lookup and the ~30ms argon2 verify.
    settings = get_settings()
    retry = await retry_after("login", key, settings.login_max_failures)
    if retry is not None:
        raise CardicheckError(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            code="TOO_MANY_ATTEMPTS",
            message="too many failed logins, try again later",
            headers={"Retry-After": str(retry)},
        )
    # argon2 is deliberately CPU-slow (~30ms per verify); running it on the
    # event loop stalls every concurrent request. Delegate to the threadpool.
    user = (
        await db.execute(select(User).where(User.email == payload.email))
    ).scalar_one_or_none()
    ok = user is not None and await run_in_threadpool(
        verify_password, payload.password, user.hashed_password
    )
    if not ok:
        await record_failure("login", key, settings.login_window_seconds)
        raise CardicheckError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="INVALID_CREDENTIALS",
            message="invalid email or password",
        )
    return ApiResponse(data=TokenResponse(access_token=create_access_token(user.id)))