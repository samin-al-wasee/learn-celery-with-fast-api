import logging
import uuid
from datetime import datetime, timedelta, timezone
from math import ceil
from typing import Any

import httpx
from fastapi import APIRouter, Depends, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.core.breaker import CircuitBreaker
from app.core.config import get_settings
from app.core.database import get_db_session
from app.core.errors import CardicheckError
from app.events.outbox import stage
from app.models import Appointment, AppointmentStatus, User, UserRole
from app.schemas.appointments import (
    AppointmentCreate,
    AppointmentResponse,
    AppointmentUpdate,
    UserBrief,
)
from app.schemas.envelope import ApiResponse

router = APIRouter(prefix="/appointments", tags=["appointments"])
logger = logging.getLogger("uvicorn.error")

_availability_breaker = CircuitBreaker(
    "availability",
    failure_threshold=get_settings().availability_breaker_threshold,
    reset_seconds=get_settings().availability_breaker_reset_seconds,
)


async def _check_availability(doctor_id: int, at: datetime) -> tuple[bool, list[str]]:
    """Returns (available, warnings). The check is advisory: on any failure, degrade."""
    # M6: a dead dependency still costs every request its full timeout (a refused connect takes
    # ~2s on Windows); an open breaker skips the call and degrades immediately instead.
    if not _availability_breaker.allow():
        return True, ["availability_unchecked"]
    settings = get_settings()
    try:
        # M6: every remote call gets a deadline; waiting forever turns their outage into ours.
        async with httpx.AsyncClient(timeout=httpx.Timeout(settings.availability_timeout_seconds)) as client:
            r = await client.get(
                f"{settings.availability_url}/availability",
                params={"doctor_id": doctor_id, "at": at.isoformat()},
            )
            r.raise_for_status()
    except httpx.HTTPError as exc:
        _availability_breaker.record_failure()
        logger.warning("availability check skipped doctor_id=%s: %s (breaker %s)",
                       doctor_id, type(exc).__name__, _availability_breaker.state)
        # M6: advisory check (the doctor confirms every booking), so book as pending and say
        # the check was skipped. A critical dependency would return 503 instead.
        return True, ["availability_unchecked"]
    _availability_breaker.record_success()
    return bool(r.json().get("available")), []


def _brief(user: User) -> UserBrief:
    return UserBrief(id=user.id, full_name=user.full_name, role=user.role.value)


def _stage_event(db: AsyncSession, kind: str, appt: Appointment) -> None:
    event: dict[str, Any] = {
        "event_id": str(uuid.uuid4()),
        "type": kind,
        "appointment_id": appt.id,
        "patient_id": appt.patient_id,
        "doctor_id": appt.doctor_id,
        "scheduled_at": appt.scheduled_at.isoformat(),
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }
    # M6: the event is written in the same transaction as the state change (transactional
    # outbox); app.events.relay publishes it, so a down broker delays events instead of losing them.
    stage(db, kind, event)


def _response(appt: Appointment) -> AppointmentResponse:
    return AppointmentResponse(
        id=appt.id,
        patient=_brief(appt.patient),
        doctor=_brief(appt.doctor),
        scheduled_at=appt.scheduled_at,
        status=appt.status,
        reason=appt.reason,
    )


@router.post("", response_model=ApiResponse[AppointmentResponse], status_code=status.HTTP_201_CREATED)
async def create_appointment(
    payload: AppointmentCreate,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> ApiResponse[AppointmentResponse]:
    # Temporal rule (handler, not schema): needs "now", which is runtime state.
    if payload.scheduled_at <= datetime.now(timezone.utc) + timedelta(minutes=15):
        raise CardicheckError(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="PAST_SCHEDULED_AT",
            message="scheduled_at must be at least 15 minutes from now",
        )

    if current_user.role == UserRole.PATIENT:
        patient_id, doctor_id = current_user.id, payload.doctor_id
    elif current_user.role == UserRole.DOCTOR:
        patient_id, doctor_id = payload.patient_id, current_user.id
    else:
        raise CardicheckError(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="INVALID_ROLE",
            message="unsupported role",
        )

    patient = await db.get(User, patient_id)
    doctor = await db.get(User, doctor_id)
    if patient is None or patient.role != UserRole.PATIENT:
        raise CardicheckError(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="INVALID_PATIENT",
            message="patient_id must reference a patient",
        )
    if doctor is None or doctor.role != UserRole.DOCTOR:
        raise CardicheckError(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="INVALID_DOCTOR",
            message="doctor_id must reference a doctor",
        )

    # M6: end the read-only transaction so this request's pool connection goes back before
    # the network call; a slow dependency must not hold DB connections the whole API shares.
    await db.commit()
    available, warnings = await _check_availability(doctor_id, payload.scheduled_at)
    if not available:
        raise CardicheckError(
            status_code=status.HTTP_409_CONFLICT,
            code="DOCTOR_UNAVAILABLE",
            message="the doctor is not available at that time",
        )

    appt = Appointment(
        patient_id=patient_id,
        doctor_id=doctor_id,
        scheduled_at=payload.scheduled_at,
        reason=payload.reason,
    )
    db.add(appt)
    await db.flush()
    _stage_event(db, "appointment.booked", appt)
    await db.commit()
    await db.refresh(appt)
    return ApiResponse(data=_response(appt), meta={"warnings": warnings} if warnings else {})


@router.get("", response_model=ApiResponse[list[AppointmentResponse]])
async def list_appointments(
    page: int = 1,
    per_page: int = 20,
    status_filter: AppointmentStatus | None = None,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> ApiResponse[list[AppointmentResponse]]:
    # Fixed: paginate + selectinload both participants in bulk (no 1+N).
    page = max(page, 1)
    per_page = min(max(per_page, 1), 100)
    owned = or_(
        Appointment.patient_id == current_user.id,
        Appointment.doctor_id == current_user.id,
    )
    filters = [owned]
    if status_filter is not None:
        filters.append(Appointment.status == status_filter)
    total = (
        await db.execute(
            select(func.count()).select_from(Appointment).where(*filters)
        )
    ).scalar_one()
    rows = (
        await db.execute(
            select(Appointment)
            .options(selectinload(Appointment.patient), selectinload(Appointment.doctor))
            .where(*filters)
            .order_by(Appointment.scheduled_at.desc())
            .limit(per_page)
            .offset((page - 1) * per_page)
        )
    ).scalars()
    data = [_response(appt) for appt in rows]
    return ApiResponse(
        data=data,
        meta={
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "pages": ceil(total / per_page),
            }
        },
    )


async def _get_appointment(db: AsyncSession, appointment_id: int) -> Appointment:
    appt = (
        await db.execute(
            select(Appointment)
            .options(selectinload(Appointment.patient), selectinload(Appointment.doctor))
            .where(Appointment.id == appointment_id)
        )
    ).scalar_one_or_none()
    if appt is None:
        raise CardicheckError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="APPOINTMENT_NOT_FOUND",
            message="appointment not found",
        )
    return appt


@router.post("/{appointment_id}/cancel", response_model=ApiResponse[AppointmentResponse])
async def cancel_appointment(
    appointment_id: int,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> ApiResponse[AppointmentResponse]:
    appt = await _get_appointment(db, appointment_id)

    # Authz: only the two participants may act on the record.
    if current_user.id not in (appt.patient_id, appt.doctor_id):
        raise CardicheckError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="NOT_PARTICIPANT",
            message="only participants may cancel this appointment",
        )

    # Transition guard + idempotency: already-cancelled -> no-op success
    # (cancel is idempotent); completed -> genuine conflict (can't rewrite history).
    if appt.status == AppointmentStatus.CANCELLED:
        return ApiResponse(data=_response(appt))
    if appt.status == AppointmentStatus.COMPLETED:
        raise CardicheckError(
            status_code=status.HTTP_409_CONFLICT,
            code="INVALID_TRANSITION",
            message="a completed appointment cannot be cancelled",
        )

    appt.status = AppointmentStatus.CANCELLED
    _stage_event(db, "appointment.cancelled", appt)
    await db.commit()
    await db.refresh(appt)
    return ApiResponse(data=_response(appt))


@router.patch("/{appointment_id}", response_model=ApiResponse[AppointmentResponse])
async def update_appointment(
    appointment_id: int,
    payload: AppointmentUpdate,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> ApiResponse[AppointmentResponse]:
    appt = await _get_appointment(db, appointment_id)

    # Authz: participants only.
    if current_user.id not in (appt.patient_id, appt.doctor_id):
        raise CardicheckError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="NOT_PARTICIPANT",
            message="only participants may update this appointment",
        )

    updates = payload.model_dump(exclude_unset=True)
    terminal = appt.status in (AppointmentStatus.CANCELLED, AppointmentStatus.COMPLETED)

    # Status transitions: doctor-only, PENDING -> CONFIRMED; re-confirm is a no-op
    # (idempotent), anything from a terminal/other state is a conflict.
    if "status" in updates:
        if current_user.role != UserRole.DOCTOR:
            raise CardicheckError(
                status_code=status.HTTP_403_FORBIDDEN,
                code="FORBIDDEN",
                message="only the doctor may confirm an appointment",
            )
        if appt.status == AppointmentStatus.CONFIRMED:
            pass
        elif appt.status != AppointmentStatus.PENDING:
            raise CardicheckError(
                status_code=status.HTTP_409_CONFLICT,
                code="INVALID_TRANSITION",
                message="only pending appointments can be confirmed",
            )
        else:
            appt.status = AppointmentStatus.CONFIRMED

    # Terminal states are immutable for data fields too.
    if ("scheduled_at" in updates or "reason" in updates) and terminal:
        raise CardicheckError(
            status_code=status.HTTP_409_CONFLICT,
            code="INVALID_TRANSITION",
            message="cancelled or completed appointments cannot be rescheduled or edited",
        )

    if "scheduled_at" in updates:
        if updates["scheduled_at"] <= datetime.now(timezone.utc) + timedelta(minutes=15):
            raise CardicheckError(
                status_code=status.HTTP_400_BAD_REQUEST,
                code="PAST_SCHEDULED_AT",
                message="scheduled_at must be at least 15 minutes from now",
            )
        appt.scheduled_at = updates["scheduled_at"]
        # M3: a new time owes a new reminder; the beat scan picks it up from the DB.
        appt.reminder_sent_at = None
    if "reason" in updates:
        appt.reason = updates["reason"]

    if updates:
        await db.commit()
        await db.refresh(appt)
    return ApiResponse(data=_response(appt))