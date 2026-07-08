import enum
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DECIMAL,
    TEXT,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import DateTime
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.db.database import Base


# Enums

class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    RECRUITER = "RECRUITER"
    TA_LEADER = "TA_LEADER"


class UserStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ProcessStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    CVS_UPLOADED = "CVS_UPLOADED"
    MATCH_PROCESSING = "MATCH_PROCESSING"
    MATCH_DONE = "MATCH_DONE"
    PROFILING_CONFIGURED = "PROFILING_CONFIGURED"
    PROFILING_ACTIVE = "PROFILING_ACTIVE"
    PROFILING_COMPLETED = "PROFILING_COMPLETED"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"


class CandidateStatus(str, enum.Enum):
    LOADED = "LOADED"
    CV_PROCESSING = "CV_PROCESSING"
    CV_ERROR = "CV_ERROR"
    MATCH_PENDING = "MATCH_PENDING"
    MATCHED = "MATCHED"
    SELECTED_FOR_PROFILING = "SELECTED_FOR_PROFILING"
    PROFILING_QUEUED = "PROFILING_QUEUED"
    PROFILING_CALLING = "PROFILING_CALLING"
    PROFILING_COMPLETED = "PROFILING_COMPLETED"
    PROFILING_FAILED = "PROFILING_FAILED"
    DISCARDED = "DISCARDED"


class MatchCategory(str, enum.Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NOT_RECOMMENDED = "NOT_RECOMMENDED"


class WhatsAppConsentStatus(str, enum.Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    TIMEOUT = "TIMEOUT"


class CallConsentStatus(str, enum.Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    NO_RESPONSE = "NO_RESPONSE"


class QuestionSetStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class QuestionType(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    MULTIPLE_CHOICE = "MULTIPLE_CHOICE"
    YES_NO = "YES_NO"
    NUMERIC = "NUMERIC"


class ProfilingRunStatus(str, enum.Enum):
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


class AdvancementProbability(str, enum.Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class AITaskType(str, enum.Enum):
    CV_EXTRACTION = "CV_EXTRACTION"
    CV_MATCH = "CV_MATCH"
    VOICE_PROFILING = "VOICE_PROFILING"
    WHATSAPP_MESSAGE = "WHATSAPP_MESSAGE"


class AIProvider(str, enum.Enum):
    OPENAI = "OPENAI"
    ANTHROPIC = "ANTHROPIC"
    ELEVENLABS = "ELEVENLABS"
    META = "META"


class OperationType(str, enum.Enum):
    CV_EXTRACTION = "CV_EXTRACTION"
    CV_MATCH = "CV_MATCH"
    VOICE_CALL = "VOICE_CALL"
    VOICE_TRANSCRIPTION = "VOICE_TRANSCRIPTION"
    WHATSAPP_MESSAGE = "WHATSAPP_MESSAGE"
    ANSWER_EVALUATION = "ANSWER_EVALUATION"


# Dominio: Identidad y Configuración

class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(String(50), nullable=False)
    status: Mapped[UserStatus] = mapped_column(String(20), nullable=False, default=UserStatus.ACTIVE)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

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
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AIPrompt(Base):
    """Append-only: nunca se hace UPDATE, siempre INSERT con nueva versión."""
    __tablename__ = "ai_prompts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_type: Mapped[AITaskType] = mapped_column(String(50), nullable=False)
    version_name: Mapped[str] = mapped_column(String(100), nullable=False)
    system_prompt_text: Mapped[str] = mapped_column(TEXT, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class GlobalBusinessSetting(Base):
    __tablename__ = "global_business_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    setting_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    setting_value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# Dominio: Procesos y Job Descriptions

class HiringProcess(Base):
    __tablename__ = "hiring_processes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    job_title: Mapped[str] = mapped_column(String(255), nullable=False)
    area: Mapped[str] = mapped_column(String(100), nullable=False)
    seniority: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[ProcessStatus] = mapped_column(String(50), nullable=False, default=ProcessStatus.DRAFT)
    budget_max_usd: Mapped[float] = mapped_column(DECIMAL(10, 2), nullable=False, default=0.00)
    match_weights_override: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    recruiter_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    question_set_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("question_sets.id", ondelete="SET NULL"), nullable=True)

    # Override de configuracion de voz (ElevenLabs) para este proceso especifico.
    # Si un campo es NULL, se usa el default_* del QuestionSet asociado (ver QuestionSet).
    voice_override_agent_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    voice_override_system_prompt: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    voice_override_first_message: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    voice_override_language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    voice_override_llm_model: Mapped[str | None] = mapped_column(String(50), nullable=True)
    voice_override_voice_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    voice_override_tts_stability: Mapped[float | None] = mapped_column(Float, nullable=True)
    voice_override_tts_speed: Mapped[float | None] = mapped_column(Float, nullable=True)
    voice_override_tts_similarity_boost: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    recruiter: Mapped["User"] = relationship(back_populates="hiring_processes")
    question_set: Mapped["QuestionSet | None"] = relationship()
    job_descriptions: Mapped[list["JobDescription"]] = relationship(back_populates="process", order_by="JobDescription.version")
    process_candidates: Mapped[list["ProcessCandidate"]] = relationship(back_populates="process")


class JobDescription(Base):
    __tablename__ = "job_descriptions"
    __table_args__ = (UniqueConstraint("process_id", "version", name="uq_jd_process_version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    process_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("hiring_processes.id", ondelete="CASCADE"), nullable=False)
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
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    process_candidates: Mapped[list["ProcessCandidate"]] = relationship(back_populates="candidate")


class ProcessCandidate(Base):
    __tablename__ = "process_candidates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    process_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("hiring_processes.id", ondelete="CASCADE"), nullable=False)
    candidate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[CandidateStatus] = mapped_column(String(50), nullable=False, default=CandidateStatus.LOADED)

    # Match
    match_percentage: Mapped[float] = mapped_column(DECIMAL(5, 2), nullable=False, default=0.00)
    match_category: Mapped[MatchCategory | None] = mapped_column(String(20), nullable=True)
    match_explanation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # WhatsApp consent
    whatsapp_consent_status: Mapped[WhatsAppConsentStatus] = mapped_column(String(20), nullable=False, default=WhatsAppConsentStatus.PENDING)
    whatsapp_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    whatsapp_responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    availability_preference: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Notas del recruiter y override humano
    human_notes: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    human_override_match: Mapped[float | None] = mapped_column(DECIMAL(5, 2), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

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
    status: Mapped[QuestionSetStatus] = mapped_column(String(20), nullable=False, default=QuestionSetStatus.DRAFT)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)

    # Configuracion de voz (ElevenLabs) por defecto para los procesos que usen este set.
    # HiringProcess.voice_override_* tiene prioridad sobre estos campos si esta seteado.
    default_agent_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    default_system_prompt: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    default_first_message: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    default_language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    default_llm_model: Mapped[str | None] = mapped_column(String(50), nullable=True)
    default_voice_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    default_tts_stability: Mapped[float | None] = mapped_column(Float, nullable=True)
    default_tts_speed: Mapped[float | None] = mapped_column(Float, nullable=True)
    default_tts_similarity_boost: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    created_by_user: Mapped["User"] = relationship(back_populates="question_sets")
    questions: Mapped[list["ProfilingQuestion"]] = relationship(back_populates="question_set", order_by="ProfilingQuestion.order_index")


class ProfilingQuestion(Base):
    __tablename__ = "profiling_questions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    question_set_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("question_sets.id", ondelete="CASCADE"), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    text: Mapped[str] = mapped_column(TEXT, nullable=False)
    type: Mapped[QuestionType] = mapped_column(String(30), nullable=False, default=QuestionType.OPEN)
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
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    process_candidate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("process_candidates.id", ondelete="CASCADE"), nullable=False)
    question_set_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("question_sets.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[ProfilingRunStatus] = mapped_column(String(30), nullable=False, default=ProfilingRunStatus.PENDING)
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
    advancement_probability: Mapped[AdvancementProbability | None] = mapped_column(String(10), nullable=True)
    advancement_explanation: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    transcription_url: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    transcript_summary: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    call_embedding: Mapped[list | None] = mapped_column(Vector(1536), nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    process_candidate: Mapped["ProcessCandidate"] = relationship(back_populates="profiling_runs")
    question_set: Mapped["QuestionSet"] = relationship()
    answers: Mapped[list["ProfilingAnswer"]] = relationship(back_populates="profiling_run")


class ProfilingAnswer(Base):
    __tablename__ = "profiling_answers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    profiling_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("profiling_runs.id", ondelete="CASCADE"), nullable=False)
    question_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("profiling_questions.id", ondelete="RESTRICT"), nullable=False)
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
    process_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("hiring_processes.id", ondelete="SET NULL"), nullable=True)
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    operation_type: Mapped[OperationType] = mapped_column(String(50), nullable=False)
    model_used: Mapped[str] = mapped_column(String(100), nullable=False)
    tokens_input: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_output: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    call_duration_s: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost: Mapped[float] = mapped_column(DECIMAL(10, 6), nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    old_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
