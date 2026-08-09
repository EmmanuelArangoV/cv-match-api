import enum
import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DECIMAL,
    TEXT,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.db.database import Base

# Enums


class UserRole(enum.StrEnum):
    ADMIN = "ADMIN"
    RECRUITER = "RECRUITER"
    TA_LEADER = "TA_LEADER"


class UserStatus(enum.StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ProcessStatus(enum.StrEnum):
    DRAFT = "DRAFT"
    CVS_UPLOADED = "CVS_UPLOADED"
    MATCH_PROCESSING = "MATCH_PROCESSING"
    MATCH_DONE = "MATCH_DONE"
    PROFILING_CONFIGURED = "PROFILING_CONFIGURED"
    PROFILING_ACTIVE = "PROFILING_ACTIVE"
    PROFILING_COMPLETED = "PROFILING_COMPLETED"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"


class CandidateStatus(enum.StrEnum):
    LOADED = "LOADED"
    CV_PROCESSING = "CV_PROCESSING"
    CV_ERROR = "CV_ERROR"
    MATCH_PENDING = "MATCH_PENDING"
    MATCH_PROCESSING = "MATCH_PROCESSING"
    MATCHED = "MATCHED"
    SELECTED_FOR_PROFILING = "SELECTED_FOR_PROFILING"
    PROFILING_QUEUED = "PROFILING_QUEUED"
    PROFILING_CALLING = "PROFILING_CALLING"
    PROFILING_COMPLETED = "PROFILING_COMPLETED"
    PROFILING_FAILED = "PROFILING_FAILED"
    DISCARDED = "DISCARDED"


class MatchCategory(enum.StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NOT_RECOMMENDED = "NOT_RECOMMENDED"


class WhatsAppConsentStatus(enum.StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    TIMEOUT = "TIMEOUT"


class CallConsentStatus(enum.StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    NO_RESPONSE = "NO_RESPONSE"


class QuestionSetStatus(enum.StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class QuestionType(enum.StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    MULTIPLE_CHOICE = "MULTIPLE_CHOICE"
    YES_NO = "YES_NO"
    NUMERIC = "NUMERIC"


class ProfilingRunStatus(enum.StrEnum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    CALLING = "CALLING"
    ANSWERED = "ANSWERED"
    NO_ANSWER = "NO_ANSWER"
    FAILED = "FAILED"
    RETRY_PENDING = "RETRY_PENDING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    VOICEMAIL_DETECTED = "VOICEMAIL_DETECTED"


class AdvancementProbability(enum.StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class AITaskType(enum.StrEnum):
    CV_EXTRACTION = "CV_EXTRACTION"
    CV_MATCH = "CV_MATCH"
    JD_ENHANCEMENT = "JD_ENHANCEMENT"
    VOICE_PROFILING = "VOICE_PROFILING"
    WHATSAPP_MESSAGE = "WHATSAPP_MESSAGE"
    VOICE_CALL_AGENT = "VOICE_CALL_AGENT"


class AIProvider(enum.StrEnum):
    OPENAI = "OPENAI"
    ANTHROPIC = "ANTHROPIC"
    ELEVENLABS = "ELEVENLABS"
    META = "META"


class OperationType(enum.StrEnum):
    CV_STORAGE = "CV_STORAGE"
    CV_EXTRACTION = "CV_EXTRACTION"
    CV_EMBEDDING = "CV_EMBEDDING"
    CV_MATCH = "CV_MATCH"
    JD_ENHANCEMENT = "JD_ENHANCEMENT"
    VOICE_CALL = "VOICE_CALL"
    VOICE_TRANSCRIPTION = "VOICE_TRANSCRIPTION"
    WHATSAPP_MESSAGE = "WHATSAPP_MESSAGE"
    WHATSAPP_AI = "WHATSAPP_AI"
    ANSWER_EVALUATION = "ANSWER_EVALUATION"
    TWILIO_CALL = "TWILIO_CALL"


# Dominio: Identidad y Configuración


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(String(50), nullable=False)
    status: Mapped[UserStatus] = mapped_column(
        String(20), nullable=False, default=UserStatus.ACTIVE
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    hiring_processes: Mapped[list["HiringProcess"]] = relationship(back_populates="recruiter")
    question_sets: Mapped[list["QuestionSet"]] = relationship(back_populates="created_by_user")


class AIModelConfiguration(Base):
    __tablename__ = "ai_model_configurations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_type: Mapped[AITaskType] = mapped_column(String(50), nullable=False)
    provider: Mapped[AIProvider] = mapped_column(String(50), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    api_key_secret_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AIPrompt(Base):
    """Append-only: nunca se hace UPDATE, siempre INSERT con nueva versión."""

    __tablename__ = "ai_prompts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_type: Mapped[AITaskType] = mapped_column(String(50), nullable=False)
    version_name: Mapped[str] = mapped_column(String(100), nullable=False)
    system_prompt_text: Mapped[str] = mapped_column(TEXT, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProcessAIPrompt(Base):
    """Revisión append-only de un prompt propio de un proceso."""

    __tablename__ = "process_ai_prompts"
    __table_args__ = (
        Index(
            "uq_process_ai_prompts_active_task",
            "process_id",
            "task_type",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    process_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hiring_processes.id", ondelete="CASCADE"), nullable=False
    )
    task_type: Mapped[AITaskType] = mapped_column(String(50), nullable=False)
    version_name: Mapped[str] = mapped_column(String(100), nullable=False)
    system_prompt_text: Mapped[str] = mapped_column(TEXT, nullable=False)
    source_prompt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_prompts.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GlobalBusinessSetting(Base):
    __tablename__ = "global_business_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    setting_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    setting_value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# Dominio: Procesos y Job Descriptions


class HiringProcess(Base):
    __tablename__ = "hiring_processes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    job_title: Mapped[str] = mapped_column(String(255), nullable=False)
    area: Mapped[str] = mapped_column(String(100), nullable=False)
    seniority: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[ProcessStatus] = mapped_column(
        String(50), nullable=False, default=ProcessStatus.DRAFT
    )
    budget_max_usd: Mapped[float] = mapped_column(DECIMAL(10, 2), nullable=False, default=0.00)
    match_weights_override: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    recruiter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    question_set_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("question_sets.id", ondelete="SET NULL"), nullable=True
    )

    # Override de configuracion de voz (ElevenLabs) para este proceso especifico.
    # El prompt vive en ProcessAIPrompt; estos campos solo controlan el agente y la voz.
    voice_override_agent_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    voice_override_first_message: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    voice_override_language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    voice_override_llm_model: Mapped[str | None] = mapped_column(String(50), nullable=True)
    voice_override_voice_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    voice_override_tts_stability: Mapped[float | None] = mapped_column(Float, nullable=True)
    voice_override_tts_speed: Mapped[float | None] = mapped_column(Float, nullable=True)
    voice_override_tts_similarity_boost: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    recruiter: Mapped["User"] = relationship(back_populates="hiring_processes")
    question_set: Mapped["QuestionSet | None"] = relationship()
    job_descriptions: Mapped[list["JobDescription"]] = relationship(
        back_populates="process", order_by="JobDescription.version"
    )
    process_candidates: Mapped[list["ProcessCandidate"]] = relationship(back_populates="process")
    ai_prompts: Mapped[list["ProcessAIPrompt"]] = relationship()


class JobDescription(Base):
    __tablename__ = "job_descriptions"
    __table_args__ = (UniqueConstraint("process_id", "version", name="uq_jd_process_version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    process_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hiring_processes.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    jd_raw_text: Mapped[str] = mapped_column(TEXT, nullable=False)
    structured_jd: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    process: Mapped["HiringProcess"] = relationship(back_populates="job_descriptions")


# Dominio: Candidatos y Pipeline


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cv_file_url: Mapped[str] = mapped_column(TEXT, nullable=False)
    cv_file_hash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    normalized_cv_url: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    extracted_profile: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    normalized_cv: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    cv_embedding: Mapped[list | None] = mapped_column(Vector(1536), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    process_candidates: Mapped[list["ProcessCandidate"]] = relationship(back_populates="candidate")


class ProcessCandidate(Base):
    __tablename__ = "process_candidates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    process_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hiring_processes.id", ondelete="CASCADE"), nullable=False
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[CandidateStatus] = mapped_column(
        String(50), nullable=False, default=CandidateStatus.LOADED
    )

    # Match
    match_percentage: Mapped[float] = mapped_column(DECIMAL(5, 2), nullable=False, default=0.00)
    match_category: Mapped[MatchCategory | None] = mapped_column(String(20), nullable=True)
    match_explanation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # WhatsApp consent
    whatsapp_consent_status: Mapped[WhatsAppConsentStatus] = mapped_column(
        String(20), nullable=False, default=WhatsAppConsentStatus.PENDING
    )
    whatsapp_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    whatsapp_responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    availability_preference: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Historial conversacional (turnos {role, text, at}) del chatbot de WhatsApp para
    # ESTE proceso puntual — vive en la fila de ProcessCandidate a proposito: si el mismo
    # telefono vuelve a aplicar en una solicitud/proceso distinto, se crea una fila nueva y
    # el contexto arranca limpio, sin arrastrar conversaciones de procesos anteriores.
    whatsapp_conversation: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    @property
    def effective_whatsapp_consent_status(self) -> str | None:
        """Retorna el consentimiento solo cuando el mensaje de WhatsApp ya fue enviado.

        Un estado PENDING sin ``whatsapp_sent_at`` todavía no representa una solicitud real.
        """
        if (
            self.whatsapp_consent_status == WhatsAppConsentStatus.PENDING.value
            or self.whatsapp_consent_status == WhatsAppConsentStatus.PENDING
        ) and self.whatsapp_sent_at is None:
            return None
        return (
            str(self.whatsapp_consent_status) if self.whatsapp_consent_status is not None else None
        )

    # Notas del recruiter y override humano
    human_notes: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    human_override_match: Mapped[float | None] = mapped_column(DECIMAL(5, 2), nullable=True)

    # Contexto libre que el recruiter proporciona antes de analizar el CV.
    # Es específico de este proceso y se inyecta en el prompt de extracción.
    analysis_context: Mapped[str | None] = mapped_column(TEXT, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    process: Mapped["HiringProcess"] = relationship(back_populates="process_candidates")
    candidate: Mapped["Candidate"] = relationship(back_populates="process_candidates")
    profiling_runs: Mapped[list["ProfilingRun"]] = relationship(back_populates="process_candidate")


# Dominio: Cuestionarios y Profiling


class QuestionSet(Base):
    __tablename__ = "question_sets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[QuestionSetStatus] = mapped_column(
        String(20), nullable=False, default=QuestionSetStatus.DRAFT
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    # Configuracion de voz (ElevenLabs) por defecto para los procesos que usen este set.
    # El prompt se configura por proceso; el set solo aporta configuración técnica.
    default_agent_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    default_first_message: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    default_language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    default_llm_model: Mapped[str | None] = mapped_column(String(50), nullable=True)
    default_voice_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    default_tts_stability: Mapped[float | None] = mapped_column(Float, nullable=True)
    default_tts_speed: Mapped[float | None] = mapped_column(Float, nullable=True)
    default_tts_similarity_boost: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    created_by_user: Mapped["User"] = relationship(back_populates="question_sets")
    questions: Mapped[list["ProfilingQuestion"]] = relationship(
        back_populates="question_set", order_by="ProfilingQuestion.order_index"
    )


class ProfilingQuestion(Base):
    __tablename__ = "profiling_questions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    question_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("question_sets.id", ondelete="CASCADE"), nullable=False
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    text: Mapped[str] = mapped_column(TEXT, nullable=False)
    type: Mapped[QuestionType] = mapped_column(
        String(30), nullable=False, default=QuestionType.OPEN
    )
    expected_answer: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    positive_keywords: Mapped[list | None] = mapped_column(ARRAY(TEXT), nullable=True)
    risk_keywords: Mapped[list | None] = mapped_column(ARRAY(TEXT), nullable=True)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_critical: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    eval_criteria: Mapped[str | None] = mapped_column(TEXT, nullable=True)

    question_set: Mapped["QuestionSet"] = relationship(back_populates="questions")
    answers: Mapped[list["ProfilingAnswer"]] = relationship(back_populates="question")


class ProfilingRun(Base):
    __tablename__ = "profiling_runs"
    __table_args__ = (
        Index(
            "uq_profiling_runs_twilio_call_sid",
            "twilio_call_sid",
            unique=True,
            postgresql_where=text("twilio_call_sid IS NOT NULL"),
        ),
        Index(
            "uq_profiling_runs_elevenlabs_conversation_id",
            "elevenlabs_conversation_id",
            unique=True,
            postgresql_where=text("elevenlabs_conversation_id IS NOT NULL"),
        ),
        Index(
            "ix_profiling_runs_candidate_latest",
            "process_candidate_id",
            "created_at",
        ),
        Index(
            "uq_profiling_runs_active_candidate",
            "process_candidate_id",
            unique=True,
            postgresql_where=text(
                "status IN ('PENDING', 'QUEUED', 'CALLING', 'ANSWERED', 'RETRY_PENDING')"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    process_candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("process_candidates.id", ondelete="CASCADE"), nullable=False
    )
    question_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("question_sets.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[ProfilingRunStatus] = mapped_column(
        String(30), nullable=False, default=ProfilingRunStatus.PENDING
    )
    call_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Consentimiento en llamada (aplica si WhatsApp fue TIMEOUT o NO_RESPONSE)
    call_consent_status: Mapped[CallConsentStatus | None] = mapped_column(String(20), nullable=True)
    call_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Correlacion con Twilio/ElevenLabs
    twilio_call_sid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    elevenlabs_conversation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    amd_result: Mapped[str | None] = mapped_column(String(30), nullable=True)
    twilio_status_detail: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # Resultado
    advancement_probability: Mapped[AdvancementProbability | None] = mapped_column(
        String(10), nullable=True
    )
    advancement_explanation: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    transcription_url: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    transcript_summary: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    # Array de turnos crudo de ElevenLabs: [{role, message, time_in_call_secs}, ...] —
    # para renderizar la conversacion completa tipo chat en el frontend.
    transcript_turns: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    call_embedding: Mapped[list | None] = mapped_column(Vector(1536), nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    process_candidate: Mapped["ProcessCandidate"] = relationship(back_populates="profiling_runs")
    question_set: Mapped["QuestionSet"] = relationship()
    answers: Mapped[list["ProfilingAnswer"]] = relationship(back_populates="profiling_run")


class ProfilingAnswer(Base):
    __tablename__ = "profiling_answers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    profiling_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiling_runs.id", ondelete="CASCADE"), nullable=False
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("profiling_questions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    transcription: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    normalized_answer: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    evaluation_result: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    detected_keywords: Mapped[list | None] = mapped_column(ARRAY(TEXT), nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(DECIMAL(4, 3), nullable=True)
    requires_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    profiling_run: Mapped["ProfilingRun"] = relationship(back_populates="answers")
    question: Mapped["ProfilingQuestion"] = relationship(back_populates="answers")


# Dominio: Telemetría


class CostLog(Base):
    __tablename__ = "cost_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    process_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hiring_processes.id", ondelete="SET NULL"), nullable=True
    )
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    operation_type: Mapped[OperationType] = mapped_column(String(50), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model_used: Mapped[str] = mapped_column(String(100), nullable=False)
    tokens_input: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_cached: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_output: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    call_duration_s: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost: Mapped[float] = mapped_column(DECIMAL(14, 9), nullable=False, default=0.0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    cost_source: Mapped[str] = mapped_column(
        String(40), nullable=False, default="legacy_estimate"
    )
    external_reference: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True
    )
    cost_breakdown: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    old_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AIFeedback(Base):
    __tablename__ = "ai_feedback"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    process_candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("process_candidates.id", ondelete="CASCADE"), nullable=False
    )
    context: Mapped[str] = mapped_column(String(50), nullable=False)  # 'MATCH' o 'PROFILING'
    evaluation: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # 'CORRECT', 'PARTIAL', 'INCORRECT'
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    process_candidate: Mapped["ProcessCandidate"] = relationship()


class NotificationModel(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    process_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hiring_processes.id", ondelete="SET NULL"), nullable=True
    )
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="SYSTEM_INFO")
    type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="INFO"
    )  # INFO, SUCCESS, WARNING, ALERT
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(TEXT, nullable=False)
    link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
