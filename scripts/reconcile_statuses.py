"""Audita y reconcilia estados históricos sin originar llamadas externas.

Uso:
    venv/bin/python scripts/reconcile_statuses.py          # dry-run
    venv/bin/python scripts/reconcile_statuses.py --apply # aplica cambios
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from src.application.hiring_process.progress import (
    get_process_progress_sync,
    sync_process_status_sync,
)
from src.config import settings
from src.domain.candidate.state_machine import CandidateStateMachine
from src.domain.profiling.watchdog import is_run_stale
from src.infrastructure.db.models import (
    CandidateStatus,
    HiringProcess,
    ProcessCandidate,
    ProfilingRun,
    ProfilingRunStatus,
)


def _mark_candidate_failed(pc: ProcessCandidate | None) -> bool:
    if not pc or pc.status in {
        CandidateStatus.PROFILING_FAILED.value,
        CandidateStatus.PROFILING_COMPLETED.value,
        CandidateStatus.DISCARDED.value,
    }:
        return False
    pc.status = CandidateStateMachine.transition(
        CandidateStatus(pc.status), CandidateStatus.PROFILING_FAILED
    ).value
    return True


def reconcile(db: Session, apply: bool) -> tuple[list[str], list[str]]:
    now = datetime.now(UTC)
    stale_ids: list[str] = []
    status_changes: list[str] = []

    runs = db.execute(
        select(ProfilingRun).where(
            ProfilingRun.status.in_((
                ProfilingRunStatus.CALLING.value,
                ProfilingRunStatus.ANSWERED.value,
            ))
        )
    ).scalars().all()
    for run in runs:
        if not is_run_stale(
            run.status,
            run.started_at,
            now,
            settings.stale_calling_timeout_seconds,
            settings.stale_answered_timeout_seconds,
        ):
            continue
        stale_ids.append(str(run.id))
        if not apply:
            continue
        pc = db.get(ProcessCandidate, run.process_candidate_id)
        run.status = ProfilingRunStatus.FAILED.value
        run.completed_at = now
        run.twilio_status_detail = "reconciled_stale"
        _mark_candidate_failed(pc)
        if pc:
            sync_process_status_sync(db, pc.process_id)

    for process in db.execute(select(HiringProcess)).scalars().all():
        before = process.status
        progress = get_process_progress_sync(db, process.id)
        if before != progress.process_status:
            status_changes.append(f"{process.id}: {before} -> {progress.process_status}")
            if apply and process.status not in {"CLOSED", "ARCHIVED"}:
                process.status = progress.process_status

    if apply:
        db.commit()
    else:
        db.rollback()
    return stale_ids, status_changes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Aplica los cambios; sin esta opción solo informa.",
    )
    args = parser.parse_args()

    engine = create_engine(settings.database_url_sync)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as db:
        stale_ids, status_changes = reconcile(db, args.apply)

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] profiling_runs stale: {len(stale_ids)}")
    for run_id in stale_ids:
        print(f"  run {run_id}: -> FAILED (reconciled_stale)")
    print(f"[{mode}] process status changes: {len(status_changes)}")
    for change in status_changes:
        print(f"  {change}")


if __name__ == "__main__":
    main()
