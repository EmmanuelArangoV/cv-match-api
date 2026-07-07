import uuid
import logging
from datetime import datetime
from celery import shared_task
from src.infrastructure.db.database import _SyncSession
from src.infrastructure.db.models import (
    ProcessCandidate,
    CandidateStatus,
    ProfilingRun,
    ProfilingRunStatus,
    HiringProcess
)
from src.domain.candidate.state_machine import CandidateStateMachine
from src.infrastructure.voice.twilio_client import twilio_client

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3, default_retry_delay=60, name="start_profiling_call")
def start_profiling_call(self, process_candidate_id: str):
    """
    Inicia una llamada saliente hacia el candidato utilizando Twilio.
    """
    pc_uuid = uuid.UUID(process_candidate_id)
    with _SyncSession() as db:
        try:
            pc = db.get(ProcessCandidate, pc_uuid)
            if not pc:
                return {"error": "ProcessCandidate not found"}

            process = db.get(HiringProcess, pc.process_id)
            if not process or not process.question_set_id:
                return {"error": "Process has no active question set"}

            # Cambiar estado del candidato a PROFILING_CALLING
            try:
                CandidateStateMachine.transition(
                    pc.status,
                    CandidateStatus.PROFILING_CALLING.value,
                    pc
                )
            except Exception as e:
                logger.error(f"Error transitioning candidate state: {e}")
                return {"error": str(e)}

            # Crear ProfilingRun
            profiling_run = ProfilingRun(
                process_candidate_id=pc_uuid,
                question_set_id=process.question_set_id,
                status=ProfilingRunStatus.CALLING.value,
                call_attempts=1,
                started_at=datetime.utcnow()
            )
            db.add(profiling_run)
            db.flush()

            # Obtener teléfono del candidato
            candidate = pc.candidate
            phone = candidate.phone
            if not phone:
                profiling_run.status = ProfilingRunStatus.FAILED.value
                pc.status = CandidateStatus.PROFILING_FAILED.value
                db.commit()
                return {"error": "Candidate has no phone number"}

            # Llamar a Twilio de forma síncrona/simulada (usando un wrapper sincrónico o event loop si fuera async real, 
            # pero aquí nuestro mock es async. En celery podemos usar asyncio.run)
            import asyncio
            result = asyncio.run(twilio_client.make_outbound_call(phone, str(profiling_run.id)))

            db.commit()
            return {
                "status": "CALLING",
                "profiling_run_id": str(profiling_run.id),
                "twilio_sid": result.get("sid")
            }

        except Exception as exc:
            db.rollback()
            logger.error(f"Error starting profiling call: {exc}")
            raise self.retry(exc=exc)

@shared_task(bind=True, max_retries=3, default_retry_delay=60, name="evaluate_profiling_transcription")
def evaluate_profiling_transcription(self, profiling_run_id: str, transcript: str):
    """
    Toma la transcripción de la llamada a ElevenLabs y la evalúa contra las preguntas del QuestionSet.
    """
    from src.infrastructure.ai.prompts import PROFILING_EVALUATION_PROMPT
    from src.infrastructure.workers.tasks.parse_cv import _get_openai
    from src.infrastructure.db.models import ProfilingAnswer, ProfilingQuestion, QuestionSet, AdvancementProbability
    import json
    
    run_uuid = uuid.UUID(profiling_run_id)
    with _SyncSession() as db:
        try:
            profiling_run = db.get(ProfilingRun, run_uuid)
            if not profiling_run:
                return {"error": "ProfilingRun not found"}
                
            question_set = db.get(QuestionSet, profiling_run.question_set_id)
            questions = db.query(ProfilingQuestion).filter_by(question_set_id=question_set.id).all()
            
            # Construir el JSON de preguntas
            questions_data = []
            for q in questions:
                questions_data.append({
                    "id": str(q.id),
                    "text": q.text,
                    "is_critical": q.is_critical,
                    "expected_answer": q.expected_answer,
                    "positive_keywords": q.positive_keywords,
                    "risk_keywords": q.risk_keywords
                })
                
            prompt = f"{PROFILING_EVALUATION_PROMPT}\n\n=== QUESTION SET ===\n{json.dumps(questions_data, indent=2)}\n\n=== TRANSCRIPT ===\n{transcript}\n"
            
            client = _get_openai()
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            
            result_str = response.choices[0].message.content
            result_data = json.loads(result_str)
            
            # Guardar respuestas
            for ans in result_data.get("answers", []):
                db.add(ProfilingAnswer(
                    profiling_run_id=profiling_run.id,
                    question_id=uuid.UUID(ans["question_id"]),
                    transcription=ans.get("transcription_snippet"),
                    normalized_answer=ans.get("normalized_answer"),
                    evaluation_result=ans.get("evaluation_result"),
                    detected_keywords=ans.get("detected_keywords", []),
                    confidence_score=ans.get("confidence_score", 0.0),
                    requires_review=ans.get("requires_review", False)
                ))
            
            # Guardar advancement probability
            prob_str = result_data.get("advancement_probability", "MEDIUM")
            advancement_map = {
                "HIGH": AdvancementProbability.HIGH,
                "MEDIUM": AdvancementProbability.MEDIUM,
                "LOW": AdvancementProbability.LOW
            }
            profiling_run.advancement_probability = advancement_map.get(prob_str, AdvancementProbability.MEDIUM)
            profiling_run.advancement_explanation = result_data.get("advancement_explanation")
            
            db.commit()
            return {"status": "EVALUATED"}
            
        except Exception as exc:
            db.rollback()
            logger.error(f"Error in evaluate_profiling_transcription: {exc}")
            raise self.retry(exc=exc)
