from math import ceil

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.core.database import get_db_session
from app.core.errors import CardicheckError
from app.models import MedicalRecord, User, UserRole
from app.schemas.appointments import UserBrief
from app.schemas.envelope import ApiResponse
from app.schemas.records import RecordCreate, RecordResponse, RecordUpdate

router = APIRouter(prefix="/records", tags=["records"])


def _brief(user: User) -> UserBrief:
    return UserBrief(id=user.id, full_name=user.full_name, role=user.role.value)


def _response(record: MedicalRecord) -> RecordResponse:
    return RecordResponse(
        id=record.id,
        title=record.title,
        notes=record.notes,
        patient=_brief(record.patient),
        doctor=_brief(record.doctor),
        created_at=record.created_at,
    )


async def _load(db: AsyncSession, record_id: int) -> MedicalRecord:
    record = (
        await db.execute(
            select(MedicalRecord)
            .options(selectinload(MedicalRecord.patient), selectinload(MedicalRecord.doctor))
            .where(MedicalRecord.id == record_id)
        )
    ).scalar_one_or_none()
    if record is None:
        raise CardicheckError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="RECORD_NOT_FOUND",
            message="record not found",
        )
    return record


@router.post("", response_model=ApiResponse[RecordResponse], status_code=status.HTTP_201_CREATED)
async def create_record(
    payload: RecordCreate,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> ApiResponse[RecordResponse]:
    if current_user.role != UserRole.DOCTOR:
        raise CardicheckError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="FORBIDDEN",
            message="only doctors can create medical records",
        )
    patient = await db.get(User, payload.patient_id)
    if patient is None or patient.role != UserRole.PATIENT:
        raise CardicheckError(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="INVALID_PATIENT",
            message="patient_id must reference a patient",
        )
    record = MedicalRecord(
        patient_id=payload.patient_id,
        doctor_id=current_user.id,
        title=payload.title,
        notes=payload.notes,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    immediate = await _load(db, record.id)
    return ApiResponse(data=_response(immediate))


@router.get("", response_model=ApiResponse[list[RecordResponse]])
async def list_records(
    page: int = 1,
    per_page: int = 20,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> ApiResponse[list[RecordResponse]]:
    page = max(page, 1)
    per_page = min(max(per_page, 1), 100)
    owned = or_(
        MedicalRecord.patient_id == current_user.id,
        MedicalRecord.doctor_id == current_user.id,
    )
    total = (
        await db.execute(
            select(func.count()).select_from(MedicalRecord).where(owned)
        )
    ).scalar_one()
    rows = (
        await db.execute(
            select(MedicalRecord)
            .options(selectinload(MedicalRecord.patient), selectinload(MedicalRecord.doctor))
            .where(owned)
            .order_by(MedicalRecord.created_at.desc())
            .limit(per_page)
            .offset((page - 1) * per_page)
        )
    ).scalars()
    return ApiResponse(
        data=[_response(r) for r in rows],
        meta={"pagination": {"page": page, "per_page": per_page, "total": total, "pages": ceil(total / per_page)}},
    )


@router.get("/{record_id}", response_model=ApiResponse[RecordResponse])
async def get_record(
    record_id: int,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> ApiResponse[RecordResponse]:
    # NAIVE: any authenticated user reads any record (no ownership check).
    record = await _load(db, record_id)
    return ApiResponse(data=_response(record))


@router.patch("/{record_id}", response_model=ApiResponse[RecordResponse])
async def update_record(
    record_id: int,
    payload: RecordUpdate,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> ApiResponse[RecordResponse]:
    # NAIVE: model_dump() includes None for missing fields -> PATCH wipes them.
    record = await _load(db, record_id)
    for field, value in payload.model_dump().items():
        setattr(record, field, value)
    await db.commit()
    await db.refresh(record)
    return ApiResponse(data=_response(record))


@router.delete("/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_record(
    record_id: int,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> Response:
    # NAIVE: no creator check — any participant deletes.
    record = await _load(db, record_id)
    await db.delete(record)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)