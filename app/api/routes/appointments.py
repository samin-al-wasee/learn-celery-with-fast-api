from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db_session
from app.core.errors import CardicheckError
from app.models import Appointment, User, UserRole
from app.schemas.appointments import AppointmentCreate, AppointmentResponse, UserBrief
from app.schemas.envelope import ApiResponse

router = APIRouter(prefix="/appointments", tags=["appointments"])


def _brief(user: User) -> UserBrief:
    return UserBrief(id=user.id, full_name=user.full_name, role=user.role.value)


async def _appointment_response(db: AsyncSession, appt: Appointment) -> AppointmentResponse:
    # NAIVE: 1+N — fetch both participants with their own query per row.
    patient = await db.get(User, appt.patient_id)
    doctor = await db.get(User, appt.doctor_id)
    return AppointmentResponse(
        id=appt.id,
        patient=_brief(patient),
        doctor=_brief(doctor),
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
    response = await _appointment_response(db, appt)
    return ApiResponse(data=response)


@router.get("", response_model=ApiResponse[list[AppointmentResponse]])
async def list_appointments(
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> ApiResponse[list[AppointmentResponse]]:
    # NAIVE: unbounded result set + 1+N per row (see scripts/observe_n_plus_1.py).
    rows = (
        await db.execute(
            select(Appointment)
            .where(or_(Appointment.patient_id == current_user.id, Appointment.doctor_id == current_user.id))
            .order_by(Appointment.scheduled_at.desc())
        )
    ).scalars()
    appts = [await _appointment_response(db, appt) for appt in rows]
    return ApiResponse(data=appts)