import asyncio
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import async_session_factory, engine
from app.models import Appointment, User, UserRole


async def seed(session: AsyncSession, n: int) -> int:
    stamp = int(time.time())
    # Distinct doctor+patient per appointment -> identity map can NOT absorb
    # the per-row lookups, so the 1+N is real. Timestamped emails keep reruns
    # collision-free.
    doctors = [
        User(
            email=f"n1-{stamp}-{i}-doc@cardicheck.io",
            hashed_password="x",
            full_name=f"Doctor {i}",
            role=UserRole.DOCTOR,
        )
        for i in range(n)
    ]
    patients = [
        User(
            email=f"n1-{stamp}-{i}-pat@cardicheck.io",
            hashed_password="x",
            full_name=f"Patient {i}",
            role=UserRole.PATIENT,
        )
        for i in range(n)
    ]
    session.add_all(doctors + patients)
    await session.commit()
    for i, (d, p) in enumerate(zip(doctors, patients)):
        await session.refresh(d)
        await session.refresh(p)
        session.add(
            Appointment(
                patient_id=p.id,
                doctor_id=d.id,
                scheduled_at=datetime.now(timezone.utc) + timedelta(days=i + 1, hours=9),
            )
        )
    await session.commit()
    return n


def run() -> None:
    async def main() -> None:
        queries: list[str] = []

        def countql(_conn, cursor, statement, _params, _context, _executemany):
            queries.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", countql)
        try:
            async with async_session_factory() as session:
                total = await seed(session, 100)

                # ---- NAIVE: fetch all, then one query per row for participants
                queries.clear()
                t0 = time.perf_counter()
                appts = (await session.execute(select(Appointment))).scalars().all()
                naive_queries = 1
                for appt in appts:
                    await session.get(User, appt.patient_id)
                    await session.get(User, appt.doctor_id)
                naive_queries = len(queries)
                naive_time = (time.perf_counter() - t0) * 1000

                # ---- FIXED: selectinload fetches both collections in bulk
                queries.clear()
                t0 = time.perf_counter()
                page = (
                    await session.execute(
                        select(Appointment)
                        .options(selectinload(Appointment.patient), selectinload(Appointment.doctor))
                        .limit(20)
                        .offset(0)
                    )
                ).scalars().all()
                total_rows = (await session.execute(select(func.count()).select_from(Appointment))).scalar_one()
                fixed_queries = len(queries)
                fixed_time = (time.perf_counter() - t0) * 1000
                names_ok = all(a.doctor.full_name and a.patient.full_name for a in page)

            print(f"seed: {total} appointments, {total_rows} in table")
            print(f"naive : {naive_queries:>3} cursor executions ({naive_time:6.1f} ms) for {total} rows")
            print(f"fixed : {fixed_queries:>3} cursor executions ({fixed_time:6.1f} ms) for 1 page of 20, names_ok={names_ok}")
            print(f"ratio : ~{naive_queries / max(fixed_queries, 1):.0f}x query volume")
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", countql)

    asyncio.run(main())


if __name__ == "__main__":
    run()