# AGENTS.md — Backend cv-match-api

> Reglas y contexto para el agente de IA (Antigravity / Claude Code) que trabaja en
> **este subrepositorio de backend**. NO cubre el monorepo ni el frontend
> (`riwi-match/`); trabaja exclusivamente dentro de `cv-match-api/`.
>
> Convención obligatoria: **todo el código nuevo, comentarios y mensajes de error se
> escriben en español**. Respeta el estilo existente.

---

## 1. Qué es este proyecto

**RIWI MATCH — API de matching de CVs con IA para procesos de contratación.**
Backend en **FastAPI (Python 3.12+)** con **workers Celery**. Recibe CVs, los parsea
con visión de OpenAI, los rankea contra una Job Description (JD), gestiona
consentimiento por WhatsApp y ejecuta profiling por voz (ElevenLabs).

Servicios externos (todos configurables por `.env`):

- **Supabase Postgres** con extensión **pgvector** (embeddings `Vector(1536)`).
- **Upstash Redis** (TLS `rediss://`) como broker y backend de Celery.
- **Cloudflare R2** (S3-compatible vía boto3) para almacenar CVs originales y normalizados.
- **OpenAI** (`gpt-4o`, visión) para extracción de CV y matching.
- **ElevenLabs** para llamadas de profiling por voz (contexto `voice/`, aún sin implementar).
- **Meta WhatsApp Business** para el consentimiento (contrato en `docs/whatsapp_api_contract.md`).

---

## 2. Comandos clave

Requiere un archivo `.env` en la raíz de `cv-match-api/` (copiar de `.env.example`).

```bash
pip install -e ".[dev]"                  # instalar con dependencias de desarrollo

python main.py                           # API en http://localhost:8000 (uvicorn --reload)

# Worker Celery (en Windows añadir --pool=solo)
celery -A src.infrastructure.workers.celery_app worker --loglevel=info

alembic upgrade head                     # aplicar migraciones
alembic revision --autogenerate -m "…"   # nueva migración (revisar SIEMPRE el archivo generado)

pytest                                   # tests (asyncio_mode=auto, testpaths=tests)
pytest tests/unit/ruta/test_x.py -k nombre   # un solo test

ruff check src/                          # lint (line-length 100, reglas E, F, I, UP)
mypy src/                                # type check (modo strict)
```

- `start_dev.bat` levanta API + worker juntos en Windows.
- Scripts útiles en `scripts/`: `create_admin.py`, `create_recruiter.py`,
  `seed_test_data.py`, `reset_and_verify.py`, `test_whatsapp.py`.
- Antes de abrir un PR corre: `ruff check src/`, `mypy src/` y `pytest`.

---

## 3. Arquitectura (clean architecture, 4 capas)

Regla de dependencia: **hacia adentro**. `domain` no importa de `application` ni de
`api`; `application` no importa de `api`. La infraestructura implementa detalles que las
capas internas solo conocen por contrato.

Todo el código vive bajo `src/`:

### `src/api/` — Capa de entrada (FastAPI)
- Routers versionados en `src/api/v1/`: `auth.py`, `processes.py`, `candidates.py`,
  `match.py`, `question_sets.py`, `webhooks.py`, `debug.py` (este último solo se monta
  si **no** es producción).
- `src/api/main.py` crea la app, configura CORS y **mapea las excepciones de dominio a
  HTTP** (ver sección 5). Registra los routers con prefijo `/api/v1`. Expone `/health`.
- `src/api/deps.py` — autenticación JWT Bearer (`get_current_user`,
  `get_current_user_with_query`) y control por roles (`require_role`). Dependencias
  listas: `RequireAdmin`, `RequireRecruiter`, `RequireTALeader` (y sus variantes
  `*WithQuery` para endpoints que reciben el token por query string, p. ej. descargas).
  Roles en `UserRole`: `ADMIN`, `RECRUITER`, `TA_LEADER`.

### `src/application/` — Casos de uso
- Un subpaquete por contexto: `auth/`, `candidate/`, `cv/`, `hiring_process/`,
  `match/`, `profiling/`. La lógica está típicamente en `use_cases.py`.
- Implementados hoy: `src/application/cv/use_cases.py` (`UploadCVsUseCase`),
  `src/application/auth/use_cases.py`,
  `src/application/candidate/whatsapp_message_usecase.py`.
- `match/`, `hiring_process/`, `profiling/` son paquetes **placeholder** (solo
  `__init__.py`); parte de esa lógica vive hoy dentro de las tareas Celery o de los
  routers. Al crecer, extraerla a casos de uso aquí.

### `src/domain/` — Reglas de negocio puras (sin I/O)
- Máquinas de estado:
  - `src/domain/candidate/state_machine.py` → `CandidateStateMachine`.
  - `src/domain/hiring_process/state_machine.py` → `HiringProcessStateMachine`.
- Reglas de negocio `RB-xxx`: `src/domain/hiring_process/rules.py` (`HiringProcessRules`).
- Value objects: `src/domain/match/value_objects.py` (`MatchWeights`, deben sumar 100),
  `src/domain/candidate/value_objects.py`, `src/domain/profiling/value_objects.py`,
  `src/domain/shared/value_objects.py` (`ValueObject` base con `_validate`).
- Excepciones: `src/domain/shared/exceptions.py`.

### `src/infrastructure/` — Adaptadores (detalles técnicos)
- `db/` — SQLAlchemy 2 async + asyncpg. Modelos y **enums** en
  `src/infrastructure/db/models.py`. Sesión async en `db/database.py` (`get_db`,
  `AsyncSessionFactory`, `Base`). Patrón repositorio en `db/repositories/`
  (`candidate_repository.py`, `process_repository.py`, `user_repository.py`).
- `workers/` — Celery. App en `workers/celery_app.py`. Tareas en `workers/tasks/`:
  `parse_cv.py` (`parse_cv`), `run_match.py` (`run_match`),
  `whatsapp.py` (`send_whatsapp_consent`).
- `ai/` — `prompts.py` (`CV_EXTRACTION_PROMPT`, `build_match_messages`) para OpenAI.
- `messaging/` — `whatsapp_client.py` (cliente Meta WhatsApp Business).
- `storage/` — `r2_client.py` (Cloudflare R2 vía boto3; funciones async y `_sync`).
- `auth/` — `password.py` (hashing), `tokens.py` (JWT access), `refresh_tokens.py`.
- `cv/` — `pdf_renderer.py` (genera el PDF normalizado estilo BBLABS).
- `cache/` — `redis_client.py`.
- `voice/` y `queue/` — paquetes placeholder (aún sin implementación).

**IMPORTANTE sobre las sesiones de DB:** la app usa **async** (asyncpg,
`DATABASE_URL`); las **tareas Celery usan sesiones síncronas** (psycopg2,
`DATABASE_URL_SYNC`) creadas con `create_engine(settings.database_url_sync)` +
`sessionmaker`. No mezcles ambos mundos.

---

## 4. Flujo central — ciclo de vida del candidato

El estado de un candidato dentro de un proceso (`ProcessCandidate.status`) es una
**máquina de estados estricta**. Estados (`CandidateStatus` en `models.py`):

```
LOADED → CV_PROCESSING → MATCH_PENDING → MATCHED → SELECTED_FOR_PROFILING
       → PROFILING_QUEUED → PROFILING_CALLING → PROFILING_COMPLETED
```

Con estados de error/reintento: `CV_ERROR` (reintenta a `CV_PROCESSING`),
`PROFILING_FAILED` (reintenta a `PROFILING_QUEUED`) y `DISCARDED` (terminal salvo
reversión manual, ver RB-008).

**Regla dura:** toda transición debe pasar por
`CandidateStateMachine.transition(current, target)`, que lanza `BusinessRuleException`
si la transición no está permitida en el diccionario `_TRANSITIONS`. Nunca asignes
`pc.status = ...` a un estado nuevo sin validar la transición (las tareas Celery hoy
escriben `.value` directamente por razones de rendimiento/claim atómico; si añades
transiciones nuevas de negocio, hazlas pasar por la máquina de estados).

El proceso de contratación tiene su propia máquina de estados
(`HiringProcessStateMachine`, `ProcessStatus`):
`DRAFT → CVS_UPLOADED → MATCH_PROCESSING → MATCH_DONE → PROFILING_CONFIGURED →
PROFILING_ACTIVE → PROFILING_COMPLETED → CLOSED → ARCHIVED`.

**El trabajo pesado corre en Celery, no en los request handlers:** parseo de CV,
matching y mensajes de WhatsApp. El endpoint solo valida, persiste el estado inicial y
encola la tarea con `.delay(...)`. Cadena típica: `UploadCVsUseCase` encola `parse_cv`
→ al terminar `parse_cv` encola `run_match` (y `send_whatsapp_consent` si hay
credenciales de WhatsApp).

---

## 5. Convenciones obligatorias

1. **Idioma:** código, comentarios y mensajes de error en **español**.

2. **Errores con excepciones de dominio, nunca `HTTPException`.** Para señalar un error
   desde cualquier capa lanza una excepción de `src/domain/shared/exceptions.py`; la app
   la mapea a HTTP en `src/api/main.py`:

   | Excepción de dominio      | HTTP |
   |---------------------------|------|
   | `UnauthorizedException`   | 401  |
   | `ForbiddenException`      | 403  |
   | `NotFoundException`       | 404  |
   | `ConflictException`       | 409  |
   | `BusinessRuleException`   | 422  |
   | `DomainException` (base)  | 400  |

   `NotFoundException(entity, entity_id)` construye el mensaje automáticamente.

3. **Transiciones de estado:** siempre vía `CandidateStateMachine.transition()` /
   `HiringProcessStateMachine.transition()`. No hardcodees saltos de estado.

4. **Reglas de negocio `RB-xxx`:** viven en `HiringProcessRules` (y en los helpers de
   las máquinas de estado). Cada método referencia su código en el docstring. Reglas
   presentes hoy:
   - RB-001: no se ejecuta match sin Job Description.
   - RB-002: un CV no se puede rankear si no fue procesado (`LOADED`/`CV_PROCESSING`/`CV_ERROR`).
   - RB-003: profiling solo con set de preguntas asignado.
   - RB-004: no se inician llamadas sin selección manual del recruiter.
   - RB-005: concurrencia máxima de llamadas configurable (`max_concurrent_calls`, default 4).
   - RB-008: un candidato **nunca** se descarta automáticamente; el recruiter puede
     revertir un `DISCARDED` a `MATCHED`.
   - RB-010: si el costo supera el presupuesto (`budget_max_usd`), bloquear nuevas ejecuciones.

5. **Tareas Celery:** decoradas con `@celery_app.task(bind=True, max_retries=..., name=...)`,
   registradas en el `include=[...]` de `celery_app.py`. Importa los modelos **dentro**
   de la función de la tarea (evita import circular). Usa sesión síncrona con
   `DATABASE_URL_SYNC`. En caso de error: `db.rollback()`, deja el registro en un estado
   de error/pendiente coherente y llama a `raise self.retry(exc=exc)`. Registra el costo
   de IA en `CostLog`.

6. **Migraciones Alembic:** genera con `--autogenerate`, **revisa el archivo generado**
   antes de aplicar (pgvector y los enums-como-String pueden requerir ajustes manuales).
   `alembic/env.py` importa `Base` de `models.py` y toma la URL de `settings.database_url`.
   Migraciones existentes en `alembic/versions/`.

7. **Estilo:** ruff (`line-length=100`, reglas `E,F,I,UP`) y mypy strict. Ejecuta ambos
   antes de commitear. No hagas commits ni cambies de rama salvo que se te pida.

---

## 6. Configuración

- `src/config.py` — `Settings` (pydantic-settings) que lee `.env`; se expone como
  **singleton** `settings`. Importa `from src.config import settings`.
- **Dos URLs de base de datos** (ambas apuntan a Supabase):
  - `DATABASE_URL` — driver **asyncpg**, usada por la app FastAPI.
  - `DATABASE_URL_SYNC` — driver **psycopg2**, usada por las tareas Celery y Alembic.
- Redis: `REDIS_URL` (TLS `rediss://` en Upstash; `celery_app.py` activa
  `broker_use_ssl`/`redis_backend_use_ssl` automáticamente si el URL empieza por `rediss://`).
- Parámetros de negocio configurables: `max_concurrent_calls` (4),
  `whatsapp_consent_timeout_hours` (24), `cv_batch_limit` (50).
- `settings.is_production` (`app_env == "production"`) apaga `/docs`, `/redoc`, el router
  `debug` y restringe CORS.

---

## 7. Puntos de atención frecuentes

- No pongas trabajo pesado (OpenAI, R2, WhatsApp) en un request handler: encólalo en Celery.
- No lances `HTTPException`: usa las excepciones de dominio.
- No saltes estados a mano: usa las máquinas de estado.
- Recuerda las **dos sesiones** de DB (async en app, sync en tareas).
- Los enums se persisten como **String** (`.value`), no como tipos ENUM nativos de Postgres.
- Al añadir un peso/campo a `MatchWeights`, mantén la suma en 100 (lo valida `_validate`).
