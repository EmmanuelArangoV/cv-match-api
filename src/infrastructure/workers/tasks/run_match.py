"""
Tarea Celery: ejecuta el match de un candidato contra la JD del proceso.
Consume normalized_cv del candidato y jd_raw_text de la JobDescription activa.
Guarda match_percentage, match_explanation (breakdown JSONB) y match_category.
"""

from __future__ import annotations

import json
import uuid

from openai import OpenAI
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import selectinload, sessionmaker

from src.config import settings
from src.domain.match.value_objects import MatchThresholds, MatchWeights
from src.infrastructure.ai.prompts import MATCH_SYSTEM_PROMPT, build_match_messages
from src.infrastructure.cache.redis_client import (
    get_active_ai_model_sync,
    get_active_ai_prompt_sync,
    get_global_setting_dict_sync,
)
from src.infrastructure.workers.celery_app import celery_app

_engine = create_engine(settings.database_url_sync)
_SyncSession = sessionmaker(bind=_engine)

# Costo estimado gpt-4o (USD por token)
_INPUT_COST = 0.0000025
_OUTPUT_COST = 0.000010


def _get_openai() -> OpenAI:
    return OpenAI(api_key=settings.openai_api_key)


def _call_openai_match(
    normalized_cv: dict,
    jd_text: str,
    weights: dict,
    thresholds: dict,
    system_prompt: str,
    model: str,
    client: OpenAI,
) -> tuple[dict, int, int]:
    """Llama a OpenAI con el prompt de match y retorna (resultado_json, tokens_in, tokens_out)."""
    messages = build_match_messages(
        normalized_cv=normalized_cv,
        jd_text=jd_text,
        weights=weights,
        thresholds=thresholds,
        system_prompt=system_prompt,
    )
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        response_format={"type": "json_object"},
        max_tokens=4096,
        temperature=0.1,
    )
    result = json.loads(response.choices[0].message.content)
    return result, response.usage.prompt_tokens, response.usage.completion_tokens


def execute_match(
    process_candidate_id: str,
    process_id: str,
) -> dict:
    from src.infrastructure.db.models import (
        CandidateStatus,
        CostLog,
        HiringProcess,
        JobDescription,
        MatchCategory,
        OperationType,
        ProcessCandidate,
        ProcessStatus,
    )

    pc_uuid = uuid.UUID(process_candidate_id)
    proc_uuid = uuid.UUID(process_id)

    with _SyncSession() as db:
        # Cargar ProcessCandidate con candidato
        pc: ProcessCandidate = db.execute(
            select(ProcessCandidate)
            .where(ProcessCandidate.id == pc_uuid)
            .options(selectinload(ProcessCandidate.candidate))
        ).scalar_one_or_none()

        if not pc:
            return {"error": "ProcessCandidate not found"}

        # Guard against double-dispatch (auto from parse_cv + manual UI trigger)
        if pc.status not in (CandidateStatus.MATCH_PENDING.value,):
            return {"skipped": f"Candidate already in status {pc.status}"}

        # Claim immediately so a concurrent bulk trigger skips this candidate
        pc.status = CandidateStatus.MATCH_PROCESSING.value
        db.flush()
        db.commit()

        candidate = pc.candidate

        # RB-002: CV debe estar procesado
        if not candidate.normalized_cv:
            pc.status = CandidateStatus.MATCH_PENDING.value
            db.commit()
            return {"error": "CV not yet processed — normalized_cv is empty"}

        # Cargar proceso con JD activa (la de mayor versión)
        process: HiringProcess = db.execute(
            select(HiringProcess)
            .where(HiringProcess.id == proc_uuid)
            .options(selectinload(HiringProcess.job_descriptions))
        ).scalar_one_or_none()

        if not process:
            pc.status = CandidateStatus.MATCH_PENDING.value
            db.commit()
            return {"error": "Process not found"}

        # Cambiar a MATCH_PROCESSING al iniciar el match
        if process.status in (
            ProcessStatus.CVS_UPLOADED.value,
            ProcessStatus.MATCH_DONE.value,
            ProcessStatus.PROFILING_CONFIGURED.value,
        ):
            process.status = ProcessStatus.MATCH_PROCESSING.value
            db.flush()

        # RB-001: debe existir una JD
        jds = sorted(process.job_descriptions, key=lambda j: j.version, reverse=True)
        if not jds:
            pc.status = CandidateStatus.MATCH_PENDING.value
            db.commit()
            return {"error": "RB-001: No active Job Description for this process"}

        active_jd: JobDescription = jds[0]
        jd_text = active_jd.jd_raw_text

        # Obtener pesos: override del proceso > default global
        if process.match_weights_override:
            weights = MatchWeights.from_dict(process.match_weights_override).to_dict()
        else:
            weights = MatchWeights.default().to_dict()

        # Obtener umbrales de clasificación (configurables desde ajustes, global)
        raw_thresholds = get_global_setting_dict_sync(
            db, "match_thresholds", MatchThresholds.default().to_dict()
        )
        thresholds = MatchThresholds.from_dict(raw_thresholds)

        # Prompt y modelo activos (configurables desde ajustes), con fallback al default de código
        system_prompt = get_active_ai_prompt_sync(db, "CV_MATCH", MATCH_SYSTEM_PROMPT)
        model = get_active_ai_model_sync(db, "CV_MATCH", "OPENAI", "gpt-4o")

        # Llamar a OpenAI
        client = _get_openai()
        match_result, tokens_in, tokens_out = _call_openai_match(
            normalized_cv=candidate.normalized_cv,
            jd_text=jd_text,
            weights=weights,
            thresholds=thresholds.to_dict(),
            system_prompt=system_prompt,
            model=model,
            client=client,
        )

        # Parsear resultado
        overall_score = float(match_result.get("overall_score", 0))

        # match_category se calcula en Python con los umbrales configurados, no se confía en
        # el valor que devuelve el LLM — así un cambio de umbral en ajustes se refleja siempre
        # con exactitud, sin depender de que el modelo aplique bien la regla del prompt.
        match_category = MatchCategory(thresholds.category_for(overall_score))

        # Guardar resultado
        pc.match_percentage = round(overall_score, 2)
        pc.match_category = match_category.value
        pc.match_explanation = match_result
        pc.status = CandidateStatus.MATCHED.value

        # Registrar costo
        estimated_cost = (tokens_in * _INPUT_COST) + (tokens_out * _OUTPUT_COST)
        cost_log = CostLog(
            process_id=proc_uuid,
            candidate_id=candidate.id,
            operation_type=OperationType.CV_MATCH.value,
            model_used=model,
            tokens_input=tokens_in,
            tokens_output=tokens_out,
            estimated_cost=estimated_cost,
        )
        db.add(cost_log)
        db.flush()

        # Transición MATCH_DONE si todos los candidatos del proceso ya fueron matcheados
        remaining = db.execute(
            select(func.count(ProcessCandidate.id))
            .where(ProcessCandidate.process_id == proc_uuid)
            .where(ProcessCandidate.status == CandidateStatus.MATCH_PENDING.value)
        ).scalar()

        if remaining == 0:
            process.status = ProcessStatus.MATCH_DONE.value

        db.commit()

        return {
            "process_candidate_id": process_candidate_id,
            "candidate_id": str(candidate.id),
            "overall_score": overall_score,
            "match_category": match_category.value,
            "status": "MATCHED",
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "estimated_cost_usd": round(estimated_cost, 6),
        }


@celery_app.task(
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    name="run_match",
)
def run_match(
    self,
    process_candidate_id: str,
    process_id: str,
) -> dict:
    from src.infrastructure.db.models import CandidateStatus, ProcessCandidate

    try:
        return execute_match(process_candidate_id, process_id)
    except Exception as exc:
        pc_uuid = uuid.UUID(process_candidate_id)
        with _SyncSession() as db:
            try:
                pc = db.get(ProcessCandidate, pc_uuid)
                if pc:
                    pc.status = CandidateStatus.MATCH_PENDING.value
                    db.commit()
            except Exception:
                pass
        raise self.retry(exc=exc)
