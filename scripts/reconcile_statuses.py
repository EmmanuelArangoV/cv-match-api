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
    build_candidate_projection,
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
    ProcessStatus,
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

    # Cierra duplicados activos antes de crear el indice unico parcial. La corrida
    # mas nueva conserva la intencion; las anteriores quedan canceladas sin publicar.
    all_runs = (
        db.execute(
            select(ProfilingRun).order_by(
                ProfilingRun.process_candidate_id, ProfilingRun.created_at.desc()
            )
        )
        .scalars()
        .all()
    )
    runs_by_candidate: dict[str, list[ProfilingRun]] = {}
    for run in all_runs:
        runs_by_candidate.setdefault(str(run.process_candidate_id), []).append(run)
    active_values = {
        ProfilingRunStatus.PENDING.value,
        ProfilingRunStatus.QUEUED.value,
        ProfilingRunStatus.CALLING.value,
        ProfilingRunStatus.ANSWERED.value,
        ProfilingRunStatus.RETRY_PENDING.value,
    }
    terminal_values = {
        ProfilingRunStatus.COMPLETED.value,
        ProfilingRunStatus.FAILED.value,
        ProfilingRunStatus.NO_ANSWER.value,
        ProfilingRunStatus.VOICEMAIL_DETECTED.value,
        ProfilingRunStatus.CANCELLED.value,
    }
    for candidate_id, candidate_runs in runs_by_candidate.items():
        active = [run for run in candidate_runs if run.status in active_values]
        for duplicate in active[1:]:
            status_changes.append(
                f"run {duplicate.id}: {duplicate.status} -> CANCELLED (duplicada)"
            )
            if apply:
                duplicate.status = ProfilingRunStatus.CANCELLED.value
                duplicate.completed_at = duplicate.completed_at or now
                duplicate.twilio_status_detail = "reconciled_duplicate"
        for run in candidate_runs:
            if run.status in terminal_values and run.completed_at is None:
                status_changes.append(f"run {run.id}: completed_at faltante")
                if apply:
                    run.completed_at = run.updated_at or run.created_at or now

    candidates = db.execute(select(ProcessCandidate)).scalars().all()
    for pc in candidates:
        candidate_runs = runs_by_candidate.get(str(pc.id), [])
        latest = candidate_runs[0] if candidate_runs else None
        process = db.get(HiringProcess, pc.process_id)
        if not process or process.status in {
            ProcessStatus.CLOSED.value,
            ProcessStatus.ARCHIVED.value,
        }:
            continue
        if pc.status == CandidateStatus.DISCARDED.value:
            continue

        # Una seleccion que espera consentimiento necesita una corrida visible,
        # pero el reconciliador nunca publica el worker ni envia WhatsApp.
        if (
            latest is None
            and pc.status == CandidateStatus.SELECTED_FOR_PROFILING.value
            and process.question_set_id
        ):
            status_changes.append(f"candidate {pc.id}: crear run PENDING sin publicar")
            if apply:
                pending = ProfilingRun(
                    process_candidate_id=pc.id,
                    question_set_id=process.question_set_id,
                    status=ProfilingRunStatus.PENDING.value,
                )
                db.add(pending)
            continue
        if latest is None:
            continue

        projection = build_candidate_projection(pc, latest)
        if projection.consistency == "OK":
            continue
        # Las intenciones humanas posteriores a un terminal se conservan y solo
        # aparecen como ATTENTION; no se reparan ni originan otra llamada.
        if latest.status in terminal_values and pc.updated_at > latest.updated_at:
            status_changes.append(
                f"candidate {pc.id}: ATTENTION preservado ({projection.consistency_explanation})"
            )
            continue
        if not apply:
            status_changes.append(
                f"candidate {pc.id}: alinear con run {latest.id} ({latest.status})"
            )
            continue
        try:
            # Reaplica la alineacion usando una transicion valida desde el estado
            # tecnico anterior cuando existe una contradiccion reparable.
            if (
                latest.status
                in {
                    ProfilingRunStatus.QUEUED.value,
                    ProfilingRunStatus.RETRY_PENDING.value,
                }
                and pc.status == CandidateStatus.SELECTED_FOR_PROFILING.value
            ):
                pc.status = CandidateStateMachine.transition(
                    CandidateStatus(pc.status), CandidateStatus.PROFILING_QUEUED
                ).value
            elif (
                latest.status
                in {
                    ProfilingRunStatus.CALLING.value,
                    ProfilingRunStatus.ANSWERED.value,
                }
                and pc.status == CandidateStatus.PROFILING_QUEUED.value
            ):
                pc.status = CandidateStateMachine.transition(
                    CandidateStatus(pc.status), CandidateStatus.PROFILING_CALLING
                ).value
            elif (
                latest.status == ProfilingRunStatus.COMPLETED.value
                and pc.status == CandidateStatus.PROFILING_CALLING.value
            ):
                pc.status = CandidateStateMachine.transition(
                    CandidateStatus(pc.status), CandidateStatus.PROFILING_COMPLETED
                ).value
            elif latest.status in terminal_values - {
                ProfilingRunStatus.COMPLETED.value
            } and pc.status in {
                CandidateStatus.PROFILING_QUEUED.value,
                CandidateStatus.PROFILING_CALLING.value,
            }:
                pc.status = CandidateStateMachine.transition(
                    CandidateStatus(pc.status), CandidateStatus.PROFILING_FAILED
                ).value
            status_changes.append(
                f"candidate {pc.id}: alineado con run {latest.id} ({latest.status})"
            )
        except Exception as exc:
            status_changes.append(f"candidate {pc.id}: ATTENTION no deterministica ({exc})")

    runs = (
        db.execute(
            select(ProfilingRun).where(
                ProfilingRun.status.in_(
                    (
                        ProfilingRunStatus.CALLING.value,
                        ProfilingRunStatus.ANSWERED.value,
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    for run in runs:
        if not is_run_stale(
            run.status,
            run.started_at,
            now,
            settings.stale_calling_timeout_seconds,
            settings.stale_answered_timeout_seconds,
            created_at=run.created_at,
        ):
            continue
        stale_ids.append(str(run.id))
        if not apply:
            continue
        pc = db.get(ProcessCandidate, run.process_candidate_id)
        run.started_at = run.started_at or run.created_at
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
