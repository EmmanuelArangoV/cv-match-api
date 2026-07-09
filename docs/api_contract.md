# RIWI MATCH — Contrato de API HTTP (Backend)

> Generado a partir del código real en `Backend/src/api/` (no del PRD). Fuente de verdad para
> implementar `riwi-match/src/lib/api.ts`. Fecha de auditoría: 2026-07-08.
>
> Base URL: `http://localhost:8000` en desarrollo (`NEXT_PUBLIC_API_URL`). Todos los routers de
> negocio se montan bajo el prefijo **`/api/v1`** (ver `src/api/main.py`). Además existe
> `GET /health` (sin prefijo, sin auth) que devuelve `{"status": "ok", "env": "..."}`.

## Cómo se monta cada router (`src/api/main.py`)

| Router (archivo) | Prefix propio del router | Prefix final montado | Tags | Condición |
|---|---|---|---|---|
| `auth.py` | `/auth` | `/api/v1/auth` | Auth | siempre |
| `processes.py` | `/processes` | `/api/v1/processes` | Processes | siempre |
| `candidates.py` | `/processes` | `/api/v1/processes` | Candidates | siempre |
| `webhooks.py` | `/webhooks` | `/api/v1/webhooks` | Webhooks | siempre |
| `match.py` | `/processes` | `/api/v1/processes` | Match | siempre |
| `question_sets.py` | `/question-sets` | `/api/v1/question-sets` | Question Sets | siempre |
| `debug.py` | `/debug` | `/api/v1/debug` | Debug (dev only) | **solo si `APP_ENV != production`** (`settings.is_production` es `False`) |

Nota: `processes.py`, `candidates.py` y `match.py` comparten el mismo prefix `/processes` — sus
rutas conviven bajo `/api/v1/processes/...`.

## Autenticación y roles

- Bearer JWT (`Authorization: Bearer <token>`), decodificado en `src/api/deps.py::get_current_user`.
  Rechaza con `UnauthorizedException` (401) si el token es inválido o el usuario no existe o no
  está `ACTIVE`.
- Variante `get_current_user_with_query` acepta el token también por **query param `?token=`**
  (usada solo en 3 endpoints de descarga de archivo, pensados para `<a href>`/`<iframe>` que no
  pueden mandar el header `Authorization`).
- Roles (`UserRole`): `ADMIN`, `RECRUITER`, `TA_LEADER`. No existe un rol público/"viewer".
- Helpers de rol listos para usar:
  - `RequireAdmin` → solo `ADMIN`.
  - `RequireRecruiter` → `ADMIN`, `RECRUITER`, `TA_LEADER` (a pesar del nombre, es el más permisivo).
  - `RequireTALeader` → `ADMIN`, `TA_LEADER`.
  - Variantes `*WithQuery` → mismos roles, pero aceptan el token por query string.
- Sin permiso → `ForbiddenException` → **403**.
- **Nadie filtra por proceso/recruiter salvo `GET /processes`** (ver esa sección) — no hay Row
  Level Security a nivel de fila para candidatos, question-sets, etc. Cualquier usuario autenticado
  con rol suficiente puede leer/editar procesos y candidatos de otros recruiters.

## Mapeo global de excepciones de dominio → HTTP (`src/api/main.py`)

| Excepción (`src/domain/shared/exceptions.py`) | HTTP | Cuándo |
|---|---|---|
| `UnauthorizedException` | 401 | credenciales inválidas, token inválido/expirado, usuario suspendido |
| `ForbiddenException` | 403 | rol insuficiente (`require_role`) |
| `NotFoundException` | 404 | entidad no encontrada |
| `ConflictException` | 409 | (declarada, pero **ningún endpoint la lanza actualmente** — ver hallazgos) |
| `BusinessRuleException` | 422 | violación de regla de negocio (`RB-xxx`), incluye mensaje con el código |
| `DomainException` (genérica) | 400 | fallback para cualquier otra excepción de dominio no listada arriba |

Todas devuelven `{"detail": "<mensaje en español>"}`. Errores de validación de Pydantic (body/query
mal formado) los maneja FastAPI por su cuenta y devuelven **422** con el formato estándar
`{"detail": [{"loc": [...], "msg": "...", "type": "..."}]}` — un shape distinto del anterior, el
frontend debe manejar ambos formatos de 422.

---

## 1. Auth (`/api/v1/auth`)

Público (sin Bearer requerido para llamarlos; no hay rate limiting visible).

### `POST /api/v1/auth/login`
- Body: `{ email: string (EmailStr), password: string }`
- 200: `{ access_token: string, refresh_token: string, token_type: "bearer", role: string }`
- Errores: 401 si credenciales inválidas o usuario `SUSPENDED`.
- `response_model=TokenResponse` (sí está tipado).

### `POST /api/v1/auth/refresh`
- Body: `{ refresh_token: string }`
- 200: mismo shape que login (rotación: revoca el refresh usado y emite uno nuevo).
- Errores: 401 si el refresh token es inválido/expirado, o si el usuario ya no existe/está suspendido.

### `POST /api/v1/auth/logout`
- Body: `{ refresh_token: string }`
- 204 sin body. Revoca el refresh token. **No requiere Bearer** (no usa `get_current_user`) — cualquiera
  con el refresh token puede invalidarlo, pero no hay forma de invalidar el access token vigente
  (los access tokens JWT no son revocables hasta que expiren).

---

## 2. Processes (`/api/v1/processes`) — `src/api/v1/processes.py`

Todos requieren Bearer. Auth: `RequireRecruiter` = ADMIN/RECRUITER/TA_LEADER para mutaciones,
`get_current_user` (cualquier rol autenticado) para lecturas.

### `POST /api/v1/processes` — crear proceso
- Auth: RequireRecruiter. Status 201.
- Body (`CreateProcessRequest`): `name` (str, 1-255), `job_title` (str, 1-255), `area` (str, 1-100),
  `seniority` (str, 1-50), `budget_max_usd` (float, default 0.0, >=0), `match_weights_override`
  (dict opcional, validado contra `MatchWeights.from_dict` — lanza `BusinessRuleException`/422 si
  el dict no calza con el value object).
- 201: `{ process_id, name, job_title, area, seniority, status: "DRAFT", budget_max_usd }`.
- `recruiter_id` se asigna automáticamente al `current_user.id` — no es parte del body.
- No response_model (retorna `dict` suelto).

### `GET /api/v1/processes` — listar procesos
- Auth: cualquier usuario autenticado.
- **Filtro por rol**: si `current_user.role == RECRUITER`, solo ve `HiringProcess` donde
  `recruiter_id == current_user.id`. `ADMIN` y `TA_LEADER` ven **todos** los procesos de todos los
  recruiters (es el único endpoint con este filtrado; en ningún otro se restringe por dueño).
- 200: `{ total: int, processes: [{ process_id, name, job_title, area, seniority, status,
  budget_max_usd, created_at }] }`, orden por `created_at desc`.

### `GET /api/v1/processes/{process_id}` — detalle
- Auth: cualquier usuario autenticado (sin chequeo de dueño).
- 200: incluye `job_description` con la versión más alta (`active_jd`): `jd_id, version,
  text_preview (300 chars + "..."), jd_raw_text (completo), jd_file_url, original_filename,
  created_at`, o `null` si no hay JD. También `match_weights` (el override, no el default real
  usado por el matcher), `created_at`, `updated_at`.
- 404 si no existe el proceso.

### `PATCH /api/v1/processes/{process_id}/voice-config` — override de voz (ElevenLabs) del proceso
- Auth: RequireRecruiter.
- Body (`UpdateVoiceConfigRequest`, todos opcionales, solo se aplican los no-`None`):
  `voice_override_agent_id, voice_override_system_prompt, voice_override_first_message,
  voice_override_language, voice_override_llm_model, voice_override_voice_id,
  voice_override_tts_stability (float), voice_override_tts_speed (float),
  voice_override_tts_similarity_boost (float)`.
- 200: eco de los 9 campos actualizados (valores actuales en DB tras el patch).
- 404 si el proceso no existe.
- Estos overrides tienen prioridad sobre los `default_*` del `QuestionSet` asociado — resuelto en
  `resolve_voice_config()` (usado por el webhook `/twilio/twiml`, no por HTTP directo).

### `POST /api/v1/processes/{process_id}/job-description` — crear JD (texto plano)
- Auth: RequireRecruiter. Status 201.
- Body: `{ jd_raw_text: string (min 10 chars) }`.
- Versión incremental automática (`version = max existente + 1`).
- 404 si el proceso no existe. **422 `BusinessRuleException("RB-009: Proceso cerrado o
  archivado")`** si `process.status` es `CLOSED` o `ARCHIVED`.
- 201: `{ jd_id, process_id, version, created_at }`.

### `POST /api/v1/processes/{process_id}/job-description/upload` — subir JD como archivo
- Auth: RequireRecruiter. Status 201. `multipart/form-data`, campo `file`.
- Acepta PDF/DOCX/DOC/TXT, límite 10 MB (`BusinessRuleException` si se supera o formato no soportado
  o no se puede extraer texto — p. ej. PDF escaneado sin OCR).
- Sube el archivo original a R2 (`jds/{process_id}/{jd_id}.{ext}`) y extrae el texto para
  `jd_raw_text`.
- Mismo chequeo RB-009 que el endpoint de texto plano.
- 201: `{ jd_id, process_id, version, jd_file_url (key interna de R2, no URL pública),
  original_filename, text_length, created_at }`.

### `GET /api/v1/processes/{process_id}/job-description/file` — descargar archivo de la JD activa
- Auth: `RequireRecruiterWithQuery` (acepta `?token=`).
- 302 redirect a URL firmada de R2 (expira en 1h).
- 404 si el proceso no existe, si no hay JD guardada, o si la JD activa no tiene archivo adjunto
  (fue creada solo con texto, no con `/job-description/upload`).

---

## 3. Candidates / Kanban (`/api/v1/processes/{process_id}/candidates/...`) — `src/api/v1/candidates.py`

### `POST /api/v1/processes/{process_id}/candidates/upload` — subir CVs (multipart, batch)
- Auth: RequireRecruiter.
- `files: list[UploadFile]` (campo `files`, uno o varios).
- Validaciones (todas en `UploadCVsUseCase`, todas devuelven **422** `BusinessRuleException` salvo
  la primera que es 404):
  - 404 si el proceso no existe.
  - 422 si el proceso está `CLOSED`/`ARCHIVED` (`require_active_process`).
  - 422 si el estado del proceso no permite carga de CVs (`can_upload_cvs`: solo desde `DRAFT`,
    `CVS_UPLOADED`, `MATCH_DONE`, `PROFILING_CONFIGURED`).
  - 422 si `candidatos_actuales + nuevos_archivos > settings.cv_batch_limit` (default 50).
  - 422 por archivo con extensión no permitida (solo PDF, DOCX, DOC, JPG, JPEG, PNG, WEBP, TIFF,
    TIF, BMP) o que supere 10 MB.
  - **Nota**: la validación de tamaño/formato es *todo o nada por request* — si un archivo del lote
    falla, se aborta el batch completo (excepción lanzada dentro del loop antes de persistir nada),
    incluso si otros archivos del mismo lote eran válidos.
- Deduplicación por hash SHA-256 del contenido: si el mismo archivo ya existe como `Candidate` en
  otro proceso, reutiliza el `Candidate` y solo crea un nuevo `ProcessCandidate` (dispara `run_match`
  directamente, no `parse_cv`, porque ya está normalizado). Si ya existía en *este mismo* proceso,
  no crea nada y el `task_id` devuelto es el string literal `"already_exists"`.
- Candidatos nuevos: crea `Candidate` en estado `LOADED` con `name="Procesando"` y
  `email=pending_{uuid}@placeholder.riwi` (placeholders hasta que `parse_cv` complete la
  normalización), sube el archivo a R2, encola `parse_cv.delay(...)`.
- 200 (no 201, aunque crea recursos): `{ uploaded: int, candidates: [{ candidate_id,
  process_candidate_id, filename, task_id, status: "LOADED" }] }` — **`status` siempre se reporta
  como `"LOADED"` en la respuesta aunque el candidato en realidad haya sido reusado/dedupeado**
  (bug cosmético: para los reusados el estado real es `MATCH_PENDING`, no `LOADED`).
- Sin `response_model`.

### `GET /api/v1/processes/{process_id}/candidates` — listado tipo Kanban
- Auth: cualquier usuario autenticado.
- 200: `{ process_id, total, candidates: [...] }`. Cada entrada:
  `rank` (1-based, orden por `match_percentage desc` — ver `find_process_candidates`),
  `process_candidate_id`, `candidate_id`, `name` (concat
  `name + last_name`), `email`, `phone`, `status` (uno de `CandidateStatus`), `match_percentage`
  (float), `match_category`, `whatsapp_consent` (uno de `WhatsAppConsentStatus`),
  `normalized_cv_url` (key R2 o null), `city` (extraído de `normalized_cv.location`, primer
  segmento antes de la coma, o `null`), y si ya hay `match_explanation`: `match_summary`,
  `strengths` (list), `gaps` (list), `breakdown` (dict).
- No pagina — devuelve todos los `ProcessCandidate` del proceso en una sola respuesta.

### `GET /api/v1/processes/{process_id}/candidates/{process_candidate_id}` — detalle de candidato
- Auth: cualquier usuario autenticado.
- 404 si no existe o pertenece a otro proceso (`pc.process_id != process_id`).
- 200: `{ process_candidate_id, process_id, candidate: { candidate_id, name, email, phone, cv_url
  (key R2, no URL descargable directamente — usar el endpoint de archivo), normalized_cv_url,
  profile (todo el JSON normalizado del CV) }, status, whatsapp_consent, human_notes,
  human_override_match (float|null), match: { percentage, category, summary, strengths, gaps,
  breakdown } | null si `match_percentage` es 0/None }.

### `PATCH /api/v1/processes/{process_id}/candidates/{process_candidate_id}/override`
- Auth: RequireRecruiter.
- Body (`OverrideBody`): `human_notes?: string`, `human_override_match?: float`.
- Semántica poco intuitiva: si `human_override_match` viene explícito como `null` en el JSON (el
  campo está presente en el payload pero con valor `null`), se **limpia** el override
  (`model_fields_set` lo detecta). Si el campo simplemente se omite del body, no se toca. El
  frontend debe enviar el campo explícitamente (aunque sea `null`) para poder borrar un override
  existente — omitirlo no basta.
- 404 si no existe o no pertenece al proceso.
- 200: `{ status: "updated" }` — no devuelve el candidato actualizado, el frontend debe refetch.

### `GET /api/v1/processes/{process_id}/candidates/{process_candidate_id}/cv/file`
- Auth: `RequireRecruiterWithQuery`.
- 302 a URL firmada de R2 (1h) del CV **original**. 404 si no hay `cv_file_url`.

### `GET /api/v1/processes/{process_id}/candidates/{process_candidate_id}/cv-normalized/file`
- Igual que el anterior pero para `normalized_cv_url` (el CV normalizado/reescrito por la IA).

### `POST /api/v1/processes/{process_id}/candidates/{process_candidate_id}/whatsapp/send`
- Auth: RequireRecruiter. Dispara manualmente (o reenvía) la plantilla de consentimiento de WhatsApp.
- 404 si no existe/no pertenece al proceso.
- 422 si el candidato no tiene teléfono registrado.
- 422 si `whatsapp_consent_status` ya es `ACCEPTED` o `REJECTED` (no se puede "reenviar" una
  respuesta ya dada).
- 200: `{ process_candidate_id, task_id, status: "queued" }` (encola `send_whatsapp_consent.delay`).

---

## 4. Match (`/api/v1/processes/{process_id}/match...`) — `src/api/v1/match.py`

### `POST /api/v1/processes/{process_id}/match` — disparar matching batch
- Auth: RequireRecruiter.
- 404 si el proceso no existe.
- 422 **RB-009** si el proceso está `CLOSED`/`ARCHIVED`.
- 422 **RB-001** si el proceso no tiene ninguna `JobDescription` (`not process.job_descriptions`).
- Si no hay candidatos en `MATCH_PENDING`: 200 con `{ process_id, queued: 0, message: "No hay
  candidatos con estado MATCH_PENDING para procesar" }` (no es error).
- Si hay elegibles: pone `process.status = MATCH_PROCESSING` **directo** (sin pasar por
  `HiringProcessStateMachine.transition()` — inconsistente con el resto del código que sí valida
  transiciones vía la máquina de estados) y encola `run_match.delay(...)` por cada candidato
  elegible.
- 200: `{ process_id, queued: int, tasks: [{ process_candidate_id, task_id }] }`.
- **No valida `RB-010` (presupuesto)** en este endpoint — el chequeo de presupuesto
  (`require_budget_available`) solo se aplica en el flujo de profiling
  (`InitiateProfilingCallUseCase`), no en el matching de CVs.

### `GET /api/v1/processes/{process_id}/match/status` — progreso del matching
- Auth: cualquier usuario autenticado.
- 404 si el proceso no existe.
- 200: `{ process_id, process_status, total_candidates, matched, match_pending, cv_processing,
  errors, progress_pct (0-100, redondeado a 1 decimal, sobre `matched/total`), is_complete (bool,
  true solo si `process.status == MATCH_DONE`) }`.
- Este es el mecanismo de **polling** para progreso en tiempo real — **no existe SSE ni WebSocket**
  para esto (ver hallazgos: el PRD `RIWI_MATCH.md` línea 537 menciona un evento SSE al terminar
  evaluación de profiling que tampoco existe en el código).

---

## 5. Question Sets (`/api/v1/question-sets`) — `src/api/v1/question_sets.py`

CRUD completo de sets de preguntas de profiling + su configuración de voz *default*. Todas las
lecturas: cualquier usuario autenticado. Todas las mutaciones: `RequireRecruiter`.

Enum `type` de pregunta (`QuestionType`): `OPEN`, `CLOSED`, `MULTIPLE_CHOICE`, `YES_NO`, `NUMERIC`.
Enum `status` de set (`QuestionSetStatus`): `DRAFT`, `ACTIVE`, `ARCHIVED`.

### `POST /api/v1/question-sets` — crear set (con preguntas embebidas opcionales)
- Status 201. Body (`CreateQuestionSetRequest`):
  - `name` (str, 3-255), `description?: string`
  - `questions?: QuestionIn[]` — cada una: `order_index?: int (default 0, autoincrementa si no
    viene)`, `text` (str, min 5), `type` (str, default `"OPEN"`, validado contra `QuestionType`,
    **422** `BusinessRuleException` si no es válido), `expected_answer?: string`,
    `positive_keywords?: string[]`, `risk_keywords?: string[]`, `weight (int 1-100, default 10)`,
    `is_critical (bool, default false)`, `eval_criteria?: string`.
- `version` siempre se crea en `1`, `status` siempre `DRAFT`, `created_by = current_user.id`
  (ninguno de estos 3 es configurable desde el body).
- 201: el set serializado completo (`_serialize_set`, incluye `questions`).

### `GET /api/v1/question-sets` — listar todos
- 200: `{ total, question_sets: [...] }` (cada uno con `questions` incluidas), orden `created_at desc`.
- **No filtra por `created_by` ni por proceso** — cualquier usuario ve todos los sets de todos.

### `GET /api/v1/question-sets/{question_set_id}` — detalle (con preguntas)
- 404 si no existe.

### `PATCH /api/v1/question-sets/{question_set_id}` — editar metadata + voz default
- Body (`UpdateQuestionSetRequest`, todo opcional): `name?, description?, status?` (validado contra
  `QuestionSetStatus`, 422 si inválido) + 9 campos `default_*` de voz (mismos nombres que
  `voice-config` de processes pero sin el prefijo `voice_override_`): `default_agent_id,
  default_system_prompt, default_first_message, default_language, default_llm_model,
  default_voice_id, default_tts_stability, default_tts_speed, default_tts_similarity_boost`.
- 200: el set serializado **sin** `questions` (a diferencia de POST/GET que sí las incluyen —
  inconsistencia menor de shape entre endpoints del mismo recurso).
- Nota PRD: "una vez usado en un proceso, no se edita destructivamente — editar crea nueva versión"
  (RIWI_MATCH.md línea 180) — **el código no implementa versionado real**: este PATCH edita el
  mismo registro in-place, no crea v2. Está marcado explícitamente como brecha (ver hallazgos).

### `DELETE /api/v1/question-sets/{question_set_id}` — 204
- Borra el set (cascada a sus preguntas por FK `ondelete=CASCADE`, ver `ProfilingQuestion`). **No
  valida si el set está referenciado por `HiringProcess.question_set_id`** (esa FK es
  `ondelete=SET NULL`) ni por `ProfilingRun.question_set_id` (esa FK es **`ondelete=RESTRICT`** —
  en la práctica, si hay `ProfilingRun`s históricos que lo usaron, el DELETE fallará con un error
  de integridad de Postgres sin traducir, no con un `ConflictException`/409 limpio — ver hallazgos).

### `POST /api/v1/question-sets/{question_set_id}/questions` — agregar pregunta suelta
- Status 201. Body igual a `QuestionIn` (`AddQuestionRequest`, mismos campos).
- 404 si el set no existe. 422 si `type` inválido.
- `order_index` autoincrementa sobre el máximo existente si no viene explícito.

### `PATCH /api/v1/question-sets/{question_set_id}/questions/{question_id}`
- Todos los campos opcionales, solo se aplican los no-`None`.
- 404 si la pregunta no existe o no pertenece a ese `question_set_id`.
- 422 si `type` viene y es inválido.

### `DELETE /api/v1/question-sets/{question_set_id}/questions/{question_id}` — 204
- 404 si no existe o no pertenece al set.

---

## 6. Webhooks (`/api/v1/webhooks`) — `src/api/v1/webhooks.py`

**Ninguno usa JWT de usuario** — se autentican con firma HMAC del proveedor externo. No deben
llamarse desde el frontend, se documentan por completitud/contexto.

### `GET /api/v1/webhooks/whatsapp` — verificación de Meta
- Público. Query: `hub.mode`, `hub.verify_token`, `hub.challenge`.
- 200 texto plano con el `challenge` si `mode == "subscribe"` y el token coincide con
  `settings.meta_whatsapp_verify_token`. 403 (`HTTPException`, no excepción de dominio) si no.

### `POST /api/v1/webhooks/whatsapp` — recepción de mensajes de Meta
- Valida firma HMAC-SHA256 (`X-Hub-Signature-256`) contra `meta_whatsapp_webhook_secret` — **se
  omite en `APP_ENV=development`** (bypass explícito de seguridad, solo aceptable en local).
- 403 si firma inválida. 404 si `body.object != "whatsapp_business_account"`.
- Delega a `ProcessWhatsAppMessageUseCase` (clasifica intención vía OpenAI, actualiza
  `whatsapp_consent_status`, y si `ACCEPTED` **transiciona el candidato a `PROFILING_QUEUED` y
  encola `start_profiling_call` con un countdown de `settings.profiling_delay_seconds` (24h
  default)** — este es el único disparador real de profiling en todo el sistema, ver hallazgos).
- 200: `{ status: "ok" }` siempre (no reporta errores de procesamiento individual de mensajes al emisor).

### `POST /api/v1/webhooks/twilio/twiml` — callback de Twilio tras AMD
- Query: `run_id` (UUID de `ProfilingRun`). Valida firma `X-Twilio-Signature`.
- Si AMD detectó máquina/buzón → `ProfilingRunStatus.VOICEMAIL_DETECTED`, encola
  `retry_or_fail_profiling_call`, responde TwiML de colgar.
- Si contestó humano → resuelve config de voz efectiva (override de proceso > default de
  question_set) y registra la llamada en ElevenLabs (`register_call`), devuelve el TwiML que arma
  el SDK de ElevenLabs.

### `POST /api/v1/webhooks/twilio/status` — status callback de Twilio
- Captura `no-answer/busy/failed/canceled` (casos que nunca llegan a `/twiml`). Idempotente por
  `call_sid` + estado actual `CALLING`.

### `POST /api/v1/webhooks/elevenlabs/post-call-transcription` — cierre de llamada
- Valida firma `ElevenLabs-Signature`. Correlaciona por `twilio_call_sid` (dynamic variable) o
  `elevenlabs_conversation_id`. Marca `ProfilingRun.COMPLETED`, transiciona el candidato a
  `PROFILING_COMPLETED`, registra `CostLog` (estimación de costo vía créditos ElevenLabs → USD,
  constante hardcodeada `_ELEVENLABS_USD_PER_MINUTE_DEFAULT = 0.09`), encola
  `evaluate_profiling_transcription` (la evaluación IA de las respuestas es asíncrona, posterior a
  este webhook).

---

## 7. Debug (`/api/v1/debug`) — solo si `APP_ENV != production`

**No montado en producción** (`if not settings.is_production` en `main.py`). Sin protección de rol
más allá de estar deshabilitado en prod — cualquiera con acceso a un entorno de desarrollo/staging
puede llamarlos sin JWT.

### `POST /api/v1/debug/seed-whatsapp-test`
- Body: `{ phone, candidate_name?, candidate_email?, job_title? }`.
- Crea (o reusa) un recruiter de prueba, un `HiringProcess` y un `Candidate` con ese teléfono en
  estado `PENDING` de consentimiento. Sin auth alguna (ni siquiera rol).

### `POST /api/v1/debug/simulate-whatsapp-message`
- Body: `{ from_phone, message }`. Ejecuta el mismo `ProcessWhatsAppMessageUseCase` que el webhook real.

### `POST /api/v1/debug/trigger-profiling-call/{process_candidate_id}`
- Sin body. Encola `start_profiling_call.delay(...)` directamente, saltándose el flujo de
  consentimiento de WhatsApp y el delay de 24h. **Esta es, hoy, la única forma de iniciar una
  llamada de profiling fuera del flujo automático de WhatsApp** — y solo existe fuera de producción.

---

## Hallazgos relevantes para el frontend (riesgos / incompletitud)

1. **No existe forma en producción de disparar profiling manualmente.** El PRD (`RIWI_MATCH.md`,
   RF-027 "Activar profiling por candidato — selección + activación manual", RB-004 "no se pueden
   iniciar llamadas sin selección manual") describe una acción manual del recruiter, pero el único
   camino real en el código es automático: WhatsApp `ACCEPTED` → `start_profiling_call` con
   countdown de 24h. El endpoint que sí hace esto sin esperar (`POST
   /debug/trigger-profiling-call/{id}`) es **dev-only** y no está montado en producción. Si el
   frontend necesita un botón "Iniciar profiling" en producción, **ese endpoint no existe todavía**
   — hay que construirlo antes de conectar esa UI.

2. **No hay endpoint para asociar un `QuestionSet` a un `HiringProcess`.** `HiringProcess.question_set_id`
   existe como columna (FK, nullable) y es la precondición de RB-003 para habilitar profiling, pero
   ningún router expone un PATCH/POST para setearlo — no está en `processes.py` ni en
   `question_sets.py`. Sin esto, `RB-003` (`require_question_set_for_profiling`) siempre fallará en
   `InitiateProfilingCallUseCase` para cualquier proceso creado vía API.

3. **Sin `response_model` en casi ningún endpoint de negocio.** Solo `auth.py` (`TokenResponse`)
   tipa la respuesta. El resto (`processes`, `candidates`, `match`, `question_sets`) retorna `dict`
   suelto — el shape documentado aquí viene de leer el código línea por línea, no de OpenAPI/Swagger
   generado (`/docs` no ayuda a verificar tipos de respuesta en estos routers).

4. **`POST /processes/{id}/match` muta `process.status` sin pasar por
   `HiringProcessStateMachine.transition()`** (línea `process.status =
   ProcessStatus.MATCH_PROCESSING.value` directa) — inconsistente con el resto del dominio, que sí
   valida transiciones. Riesgo de estado inválido si se llama en un momento no contemplado por la
   máquina de estados.

5. **SSE mencionado en el PRD no existe.** `RIWI_MATCH.md` línea 537 describe "el backend emite un
   evento vía SSE" al persistir la evaluación de profiling — no hay ningún endpoint SSE/WebSocket en
   el código. El único mecanismo de progreso en tiempo real disponible hoy es **polling** vía `GET
   /processes/{id}/match/status` (y no existe un equivalente `/profiling/status`).

6. **No existen endpoints de `ai_config`.** Los modelos `AIModelConfiguration` y
   `GlobalBusinessSetting` existen en `models.py` pero no tienen router — no hay forma de leer/editar
   qué modelo de IA usa cada tarea (`CV_EXTRACTION`, `CV_MATCH`, etc.) vía API. Confirma lo ya
   registrado en memoria (`riwimatch_master_doc_pending_items`).

7. **`ConflictException` (409) está declarada y mapeada pero ningún caso de uso la lanza** en el
   código auditado — en la práctica ningún endpoint de negocio devuelve 409 hoy (el candidato más
   cercano, el `DELETE question-sets/{id}` con `ProfilingRun`s dependientes por `ondelete=RESTRICT`,
   probablemente rompe con un error crudo de Postgres/SQLAlchemy sin traducir a excepción de dominio).

8. **Endpoints de descarga de archivo (`cv/file`, `cv-normalized/file`, `job-description/file`)
   devuelven 302 con URL firmada de R2**, no el archivo directo ni JSON con la URL — el frontend
   debe usarlos como `href`/`src` de un `<a>`/`<iframe>` (aceptan `?token=` para eso), no
   `fetch()`+parsear JSON.

9. **`whatsapp/send` y el flujo de reintento de consentimiento no tiene endpoint para "cancelar" o
   resetear un `whatsapp_consent_status` distinto de `ACCEPTED`/`REJECTED`** — solo se puede
   reenviar mientras siga `PENDING` o `TIMEOUT`.

10. **`upload_cvs` reporta `status: "LOADED"` siempre** en la respuesta, incluso para candidatos
    deduplicados/reusados cuyo estado real ya es `MATCH_PENDING` — no confiar en ese campo de la
    respuesta del upload para decidir el estado inicial en el Kanban; conviene refetch de
    `GET /candidates` tras el upload.
