import uuid
import csv
from io import StringIO
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.api.deps import RequireRecruiter
from src.domain.shared.exceptions import NotFoundException
from src.infrastructure.db.database import get_db
from src.infrastructure.db.models import HiringProcess, ProcessCandidate, CostLog, User

# We append to processes.py so we read the file and find the end
with open('src/api/v1/processes.py', 'r', encoding='utf-8') as f:
    content = f.read()

new_endpoints = '''

@router.get("/{process_id}/export/ranking")
async def export_ranking(
    process_id: uuid.UUID,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db)
) -> StreamingResponse:
    process = await db.get(HiringProcess, process_id)
    if not process:
        raise NotFoundException("Proceso no encontrado")

    query = select(ProcessCandidate).where(ProcessCandidate.process_id == process_id).order_by(ProcessCandidate.match_score.desc().nullslast())
    result = await db.execute(query)
    candidates = result.scalars().all()

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Email", "Status", "Match Score", "Match Category", "Profiling Score", "Created At"])
    for c in candidates:
        email = c.candidate.email if c.candidate else ""
        writer.writerow([str(c.id), email, c.status, c.match_score, c.match_category, c.profiling_score, c.created_at])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=ranking_{process_id}.csv"}
    )

@router.get("/{process_id}/export/costs")
async def export_costs(
    process_id: uuid.UUID,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db)
) -> StreamingResponse:
    process = await db.get(HiringProcess, process_id)
    if not process:
        raise NotFoundException("Proceso no encontrado")

    query = select(CostLog).where(CostLog.process_id == process_id).order_by(CostLog.created_at.desc())
    result = await db.execute(query)
    logs = result.scalars().all()

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Action", "Provider", "Estimated Cost", "Created At"])
    for log in logs:
        writer.writerow([str(log.id), log.action, log.provider, log.estimated_cost, log.created_at])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=costs_{process_id}.csv"}
    )
'''

content += new_endpoints

with open('src/api/v1/processes.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Added export endpoints to processes.py")
