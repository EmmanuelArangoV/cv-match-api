import asyncio
import uuid

from sqlalchemy import select

from src.infrastructure.auth.password import hash_password
from src.infrastructure.db.database import AsyncSessionFactory
from src.infrastructure.db.models import (
    Candidate,
    CandidateStatus,
    HiringProcess,
    MatchCategory,
    ProcessCandidate,
    ProcessStatus,
    User,
    UserRole,
    UserStatus,
    WhatsAppConsentStatus,
)

# (nombre, apellido, telefono con codigo de pais, categoria de match para verla en el kanban)
TEST_CANDIDATES = [
    ("Maryhug", "Duran", "573112790495", MatchCategory.HIGH),
    ("Emmanuel", "Arango", "573193696490", MatchCategory.HIGH),
    ("Valeria", "Taborda", "573114509897", MatchCategory.MEDIUM),
    ("Sarahi", "Cruz", "573206040624", MatchCategory.LOW),
]


async def seed() -> None:
    async with AsyncSessionFactory() as session:
        # Reusa un recruiter de prueba si ya existe (mismo que usa /debug/seed-whatsapp-test)
        recruiter_email = "recruiter-test@riwi.io"
        recruiter = (
            await session.execute(select(User).where(User.email == recruiter_email))
        ).scalar_one_or_none()
        if not recruiter:
            recruiter = User(
                id=uuid.uuid4(),
                name="Recruiter",
                last_name="Test",
                email=recruiter_email,
                password_hash=hash_password("test1234"),
                role=UserRole.RECRUITER,
                status=UserStatus.ACTIVE,
            )
            session.add(recruiter)
            await session.flush()

        process = HiringProcess(
            id=uuid.uuid4(),
            name="Proceso de Prueba WhatsApp",
            job_title="Desarrollador Backend (Test)",
            area="IT",
            seniority="Senior",
            recruiter_id=recruiter.id,
            status=ProcessStatus.MATCH_DONE,
        )
        session.add(process)
        await session.flush()

        for i, (name, last_name, phone, category) in enumerate(TEST_CANDIDATES):
            candidate = Candidate(
                id=uuid.uuid4(),
                name=name,
                last_name=last_name,
                email=f"{name.lower()}.{last_name.lower()}@riwi-test.io",
                phone=phone,
                cv_file_url="test-seed.pdf",
            )
            session.add(candidate)
            await session.flush()

            pc = ProcessCandidate(
                id=uuid.uuid4(),
                process_id=process.id,
                candidate_id=candidate.id,
                status=CandidateStatus.MATCHED,
                match_percentage=90.0 - i * 5,
                match_category=category,
                whatsapp_consent_status=WhatsAppConsentStatus.PENDING,
            )
            session.add(pc)
            print(f"Creado: {name} {last_name} ({phone}) -> process_candidate_id={pc.id}")

        await session.commit()
        print(f"\nProceso de prueba creado: {process.id}")
        print(f"Ver en frontend: http://localhost:3000/hiring-processes/{process.id}/candidates")


if __name__ == "__main__":
    asyncio.run(seed())
