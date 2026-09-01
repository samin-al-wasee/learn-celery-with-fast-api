from datetime import datetime, timezone
from math import ceil

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.core.database import get_db_session
from app.core.errors import CardicheckError
from app.models import Appointment, User, UserRole
from app.schemas.appointments import AppointmentCreate, AppointmentResponse, UserBrief
from app.schemas.envelope import ApiResponse

router = APIRouter(prefix="/appointments", tags=["appointments"])


def _brief(user: User) -> UserBrief:
    return UserBrief(id=user.id, full_name=user.full_name, role=user.role.value)


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
    if payload.scheduled_at <= datetime.now(timezone.utc):
        raise CardicheckError(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="PAST_SCHEDULED_AT",
            message="scheduled_at must be in the future",
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

    appt = Appointment(
        patient_id=patient_id,
        doctor_id=doctor_id,
        scheduled_at=payload.scheduled_at,
        reason=payload.reason,
    )
    db.add(appt)
    await db.commit()
    await db.refresh(appt)
    return ApiResponse(data=_response(appt))


@router.get("", response_model=ApiResponse[list[AppointmentResponse]])
async def list_appointments(
    page: int = 1,
    per_page: int = 20,
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
    total = (
        await db.execute(
            select(func.count()).select_from(Appointment).where(owned)
        )
    ).scalar_one()
    rows = (
        await db.execute(
            select(Appointment)
            .options(selectinload(Appointment.patient), selectinload(Appointment.doctor))
            .where(owned)
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