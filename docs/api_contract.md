# RIWI MATCH — Contrato de API HTTP (Backend)

> Generado a partir del código real en `Backend/src/api/` (no del PRD). Fuente de verdad para
> implementar `riwi-match/src/lib/api.ts`. Fecha de auditoría: 2026-07-10 (commit `e6674d3`).
> Auditoría previa: 2026-07-08 (commit `ca48351`) — entre ambas hubo 6 commits que tocaron
> `src/api/` (nuevos routers `profiling`, `metrics`, `ai_config`, `users`; versionado real de
> question-sets; endpoints de JD con IA; ver cambios marcados abajo).
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
| `profiling.py` (`router`) | `/processes` | `/api/v1/processes` | Profiling | siempre — **nuevo desde el último audit** |
| `profiling.py` (`global_router`) | `/profiling` | `/api/v1/profiling` | Profiling | siempre — **nuevo** |
| `metrics.py` | `/metrics` | `/api/v1/metrics` | Metrics | siempre — **nuevo** |
| `ai_config.py` | `/ai-config` | `/api/v1/ai-config` | AI Config | siempre — **nuevo** |
| `users.py` | `/users` | `/api/v1/users` | Users | siempre — **nuevo** |
| `debug.py` | `/debug` | `/api/v1/debug` | Debug (dev only) | **solo si `APP_ENV != production`** (`settings.is_production` es `False`) |

Nota: `processes.py`, `candidates.py`, `match.py` y `profiling.py` (`router`) comparten el mismo
prefix `/processes` — sus rutas conviven bajo `/api/v1/processes/...`.

**Routers huérfanos — existen como archivo con `APIRouter` pero NO están importados ni montados
en `main.py`, por lo tanto son inaccesibles vía HTTP hoy:** `ai_tools.py` (`/ai-tools`),
`audit.py` (`/audit-logs`), `feedback.py` (`/feedback`), `reports.py` (`/reports`). Ver sección 12.

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
- **El filtrado por dueño/recruiter sigue siendo la excepción, no la regla** — hoy filtran por
  `recruiter_id == current_user.id` cuando el rol es `RECRUITER`: `GET /processes` y (novedad)
  `GET /profiling/runs` (global). **`GET /metrics/dashboard`, `GET /processes/{id}/metrics`,
  `GET /processes/{id}/profiling/runs` (el scoped a un proceso) y `GET /ai-config/*` no filtran
  por dueño** — cualquier usuario autenticado con rol suficiente ve datos de todos los recruiters.

## Mapeo global de excepciones de dominio → HTTP (`src/api/main.py`)

| Excepción (`src/domain/shared/exceptions.py`) | HTTP | Cuándo |
|---|---|---|
| `UnauthorizedException` | 401 | credenciales inválidas, token inválido/expirado, usuario suspendido |
| `ForbiddenException` | 403 | rol insuficiente (`require_role`) |
| `NotFoundException` | 404 | entidad no encontrada |
| `ConflictException` | 409 | **ya se lanza** en `POST /users` y `PATCH /users/{id}` cuando el email ya existe (`users_use_cases.py`) — a diferencia del audit anterior, esto ya no es una excepción "declarada pero muerta" |
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
- **Novedad**: además de emitir el token, registra un `AuditLog` (`action="USER_LOGIN"`) — ver
  hallazgo sobre el audit trail de solo-escritura (§12/§Hallazgos).

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
  recruiters.
- 200: `{ total: int, processes: [{ process_id, name, job_title, area, seniority, status,
  budget_max_usd, created_at }] }`, orden por `created_at desc`.

### `GET /api/v1/processes/{process_id}` — detalle
- Auth: cualquier usuario autenticado (sin chequeo de dueño).
- 200: incluye `job_description` con la versión más alta (`active_jd`): `jd_id, version,
  text_preview (300 chars + "..."), jd_raw_text (completo), jd_file_url, original_filename,
  created_at`, o `null` si no hay JD. También `match_weights` (el override, no el default real
  usado por el matcher), `question_set_id` (**nuevo campo** — el set asociado, o `null`),
  `voice_override_system_prompt`, `voice_override_first_message`, `created_at`, `updated_at`.
- 404 si no existe el proceso.

### `PATCH /api/v1/processes/{process_id}/question-set` — **nuevo endpoint**, asocia un QuestionSet
- Auth: RequireRecruiter.
- Body: `{ question_set_id: uuid }`.
- 404 si el proceso o el set no existen. 422 (RB-009) si el proceso está `CLOSED`/`ARCHIVED`.
- 200: `{ process_id, question_set_id }`.
- **Este endpoint resuelve el hallazgo histórico** ("no existe forma de asociar un QuestionSet a
  un HiringProcess") — RB-003 ya puede satisfacerse vía API sin ir directo a la base de datos.
  No valida que el `question_set_id` esté en estado `ACTIVE` — se puede asociar un set en `DRAFT`
  o `ARCHIVED` sin error.

### `PATCH /api/v1/processes/{process_id}` — **nuevo endpoint**, editar metadata del proceso
- Auth: RequireRecruiter.
- Body (`UpdateProcessRequest`, todo opcional): `name, job_title, area, seniority, budget_max_usd`.
- 404 si no existe. 422 (`require_active_process`) si está `CLOSED`/`ARCHIVED`.
- 200: eco de los campos actualizados (mismo shape que el `POST` de creación).
- No permite editar `match_weights_override` desde este endpoint (solo se setea al crear).

### `PATCH /api/v1/processes/{process_id}/status` — **nuevo endpoint**, cambiar estado del proceso
- Auth: RequireRecruiter.
- Body: `{ status: ProcessStatus }`.
- A diferencia de `POST /processes/{id}/match` (que muta `process.status` directo, ver hallazgo),
  este endpoint **sí pasa por `HiringProcessStateMachine.transition()`** — lanza la excepción que
  la máquina de estados lance (típicamente `BusinessRuleException`/422) si la transición pedida no
  es válida desde el estado actual.
- 200: `{ process_id, status }`.

### `POST /api/v1/processes/{process_id}/job-description` — crear JD (texto plano)
- Auth: RequireRecruiter. Status 201.
- Body: `{ jd_raw_text: string (min 10 chars) }`.
- Versión incremental automática (`version = max existente + 1`).
- 404 si el proceso no existe. **422 `BusinessRuleException("RB-009: Proceso cerrado o
  archivado")`** si `process.status` es `CLOSED` o `ARCHIVED`.
- 201: `{ jd_id, process_id, version, created_at }`.

### `POST /api/v1/processes/{process_id}/job-description/parse` — **nuevo endpoint**, analiza JD con IA
- Auth: RequireRecruiter. Body igual al anterior (`jd_raw_text`).
- **No persiste nada** — es análisis puro (`ParseJobDescriptionUseCase`, OpenAI `gpt-4o` hardcodeado,
  `temperature=0.2`) para que el recruiter revise antes de decidir guardar con el `POST` de arriba.
- 200: `{ must_have: string[], nice_to_have: string[], deal_breakers: string[], summary: string }`.
- 422 `BusinessRuleException` si la llamada a OpenAI falla o devuelve JSON inválido.
- No valida `RB-009` (proceso cerrado/archivado) — solo chequea que el proceso exista.

### `POST /api/v1/processes/{process_id}/job-description/enhance` — **nuevo endpoint**, mejora la JD activa con IA
- Auth: RequireRecruiter. Status 201. Sin body (usa la JD activa del proceso).
- 404 si el proceso no existe. 422 (RB-009) si `CLOSED`/`ARCHIVED`. 422 si no hay ninguna JD para mejorar.
- **A diferencia de `/parse`, este sí persiste**: llama a `EnhanceJDUseCase` (OpenAI `gpt-4o`
  hardcodeado, `temperature=0.6`, prompt distinto de `/parse`) y guarda el resultado como una
  **nueva versión** de `JobDescription` (`version = activa + 1`), con
  `structured_jd.ai_enhanced = true` y las `recommendations`/`missing_elements` de la IA embebidas.
- 201: `{ jd_id, process_id, version, recommendations: string[], missing_elements: string[], created_at }`.
- **Existe una segunda implementación duplicada e inalcanzable** de esta misma idea en
  `src/api/v1/ai_tools.py` (`POST /ai-tools/enhance-jd`, usa
  `src.application.ai.enhance_jd_usecase.EnhanceJDUseCase`, una clase *distinta* con firma distinta
  — recibe `db` y `user_id`) — ese router no está montado en `main.py` (ver §12), es código muerto.

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

### `GET /api/v1/processes/{process_id}/job-descriptions` — **nuevo endpoint**, historial de versiones de JD
- Auth: RequireRecruiter.
- 200: `list[{ jd_id, version, text_preview, jd_file_url, original_filename, created_at }]`, orden
  `version desc`. Es el único lugar donde se puede ver el historial completo de versiones — el
  detalle del proceso (`GET /processes/{id}`) solo expone la más reciente.

### `GET /api/v1/processes/{process_id}/metrics` — **nuevo endpoint**, métricas de un proceso
- Auth: RequireRecruiter (sin filtro de dueño — cualquier recruiter ve las métricas de cualquier proceso).
- 200: `{ process_id, total_cvs, status_distribution: {status: count}, match_distribution:
  {category: count}, total_cost_usd, budget_max_usd }`.
- No confundir con `GET /processes/{id}/match/status` (§4), que es progreso de matching en curso;
  este es un resumen agregado de costos y distribución de candidatos.

### `GET /api/v1/processes/{process_id}/export/ranking` — **nuevo endpoint, ROTO**
- Auth: RequireRecruiter. Pensado para devolver un CSV (`StreamingResponse`,
  `Content-Disposition: attachment`) con el ranking de candidatos del proceso.
- **Este endpoint lanza `NameError` en cualquier invocación real**: el módulo `processes.py` usa
  `csv.writer(...)`, `StringIO()`, `ProcessCandidate` y `CostLog` en el cuerpo de la función, pero
  **ninguno de los cuatro está importado** en ese archivo (`import csv` y `from io import StringIO`
  no existen; `ProcessCandidate`/`CostLog` solo se importan localmente dentro de otra función,
  `get_process_metrics`, no a nivel de módulo). Verificado por AST: los cuatro nombres se
  *referencian* pero no están en el conjunto de imports del archivo. **No usar en el frontend hasta
  que se corrija** — hoy devolvería 500.

### `GET /api/v1/processes/{process_id}/export/costs` — **nuevo endpoint, ROTO**
- Mismo problema exacto que `/export/ranking`: usa `csv`, `StringIO` y `CostLog` sin importarlos.
  También lanza `NameError` (500) en cualquier invocación.

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

---

## 3. Candidates / Kanban (`/api/v1/processes/{process_id}/candidates/...`) — `src/api/v1/candidates.py`

Sin cambios funcionales desde el audit anterior salvo: `PATCH .../override` ahora además registra
un `AuditLog` (`action="MANUAL_OVERRIDE"`) antes del commit — mismo hallazgo de solo-escritura que
en auth/users (§Hallazgos).

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

Sin cambios funcionales desde el audit anterior (solo reformateo de línea).

### `POST /api/v1/processes/{process_id}/match` — disparar matching batch
- Auth: RequireRecruiter.
- 404 si el proceso no existe.
- 422 **RB-009** si el proceso está `CLOSED`/`ARCHIVED`.
- 422 **RB-001** si el proceso no tiene ninguna `JobDescription` (`not process.job_descriptions`).
- Si no hay candidatos en `MATCH_PENDING`: 200 con `{ process_id, queued: 0, message: "No hay
  candidatos con estado MATCH_PENDING para procesar" }` (no es error).
- Si hay elegibles: pone `process.status = MATCH_PROCESSING` **directo** (sin pasar por
  `HiringProcessStateMachine.transition()` — inconsistente con `PATCH /processes/{id}/status`,
  que sí valida transiciones vía la máquina de estados) y encola `run_match.delay(...)` por cada
  candidato elegible.
- 200: `{ process_id, queued: int, tasks: [{ process_candidate_id, task_id }] }`.
- **No valida `RB-010` (presupuesto)** en este endpoint — el chequeo de presupuesto
  (`require_budget_available`) se aplica en `UploadCVsUseCase` (al subir CVs) y en
  `InitiateProfilingCallUseCase` (al iniciar profiling), no aquí.

### `GET /api/v1/processes/{process_id}/match/status` — progreso del matching
- Auth: cualquier usuario autenticado.
- 404 si el proceso no existe.
- 200: `{ process_id, process_status, total_candidates, matched, match_pending, cv_processing,
  errors, progress_pct (0-100, redondeado a 1 decimal, sobre `matched/total`), is_complete (bool,
  true solo si `process.status == MATCH_DONE`) }`.
- Este es el mecanismo de **polling** para progreso en tiempo real — no existe SSE ni WebSocket
  para esto, ni tampoco para profiling (`GET /profiling/runs` requiere refetch manual, no notifica
  cambios de estado).

---

## 5. Question Sets (`/api/v1/question-sets`) — `src/api/v1/question_sets.py`

CRUD completo de sets de preguntas de profiling + su configuración de voz *default*. Todas las
lecturas: cualquier usuario autenticado. Todas las mutaciones: `RequireRecruiter`.

Enum `type` de pregunta (`QuestionType`): `OPEN`, `CLOSED`, `MULTIPLE_CHOICE`, `YES_NO`, `NUMERIC`.
Enum `status` de set (`QuestionSetStatus`): `DRAFT`, `ACTIVE`, `ARCHIVED`.

**Cambio importante desde el último audit: el versionado ahora SÍ está implementado** (antes el
PATCH editaba in-place). Ver el nuevo comportamiento de clonado abajo — afecta a los 4 endpoints
de mutación de sets/preguntas.

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
- **Versionado real vía clonado silencioso** (`_clone_question_set_if_active`, nuevo desde el
  último audit): si el set tiene `status == ACTIVE` **o** está referenciado por algún
  `HiringProcess.question_set_id`, el PATCH **no edita el registro original** — crea un
  `QuestionSet` nuevo (`version = actual + 1`, `status = DRAFT`, clona todas las preguntas y los
  9 campos `default_*`) y aplica los cambios del body sobre ese clon. **El `id` que vuelve en la
  respuesta puede no ser el mismo `question_set_id` que se mandó en la URL** — el frontend debe
  usar el `id` de la respuesta para operaciones subsiguientes, no asumir que es el mismo.
  **Ningún `HiringProcess` que ya apuntaba al set original se re-asocia automáticamente al
  clon** — hay que llamar explícitamente a `PATCH /processes/{id}/question-set` con el nuevo id,
  o los procesos existentes seguirán usando la versión vieja (sin los cambios que se acaban de
  guardar). Mismo comportamiento de clonado aplica a `POST .../questions`,
  `PATCH .../questions/{id}` y `DELETE .../questions/{id}` (ver abajo).

### `DELETE /api/v1/question-sets/{question_set_id}` — 204
- Borra el set (cascada a sus preguntas por FK `ondelete=CASCADE`, ver `ProfilingQuestion`). **No
  valida si el set está referenciado por `HiringProcess.question_set_id`** (esa FK es
  `ondelete=SET NULL`) ni por `ProfilingRun.question_set_id` (esa FK es **`ondelete=RESTRICT`** —
  en la práctica, si hay `ProfilingRun`s históricos que lo usaron, el DELETE fallará con un error
  de integridad de Postgres sin traducir, no con un `ConflictException`/409 limpio). **A diferencia
  de los otros 4 endpoints de este recurso, este NO clona** — sigue operando directo sobre el
  registro pedido incluso si está `ACTIVE` o en uso, sin ningún chequeo de seguridad equivalente al
  de arriba.

### `POST /api/v1/question-sets/{question_set_id}/questions` — agregar pregunta suelta
- Status 201. Body igual a `QuestionIn` (`AddQuestionRequest`, mismos campos).
- 404 si el set no existe. 422 si `type` inválido.
- `order_index` autoincrementa sobre el máximo existente si no viene explícito.
- Sujeto al mismo clonado silencioso descrito arriba: la pregunta puede terminar creada en un
  `question_set_id` distinto al de la URL si el set original está `ACTIVE`/en uso.

### `PATCH /api/v1/question-sets/{question_set_id}/questions/{question_id}`
- Todos los campos opcionales, solo se aplican los no-`None`.
- 404 si la pregunta no existe o no pertenece a ese `question_set_id`.
- 422 si `type` viene y es inválido.
- Sujeto al mismo clonado silencioso: internamente busca la pregunta equivalente en el clon por
  `id` y, si no la encuentra (porque es una pregunta recién clonada con `id` nuevo), hace un
  segundo intento por `(text, order_index)` — si tampoco matchea, 404 "tras versionamiento".

### `DELETE /api/v1/question-sets/{question_set_id}/questions/{question_id}` — 204
- 404 si no existe o no pertenece al set.
- Mismo mecanismo de clonado + búsqueda por `(text, order_index)` que el PATCH de arriba.

---

## 6. Webhooks (`/api/v1/webhooks`) — `src/api/v1/webhooks.py`

Sin cambios desde el audit anterior. **Ninguno usa JWT de usuario** — se autentican con firma HMAC
del proveedor externo. No deben llamarse desde el frontend, se documentan por completitud/contexto.

### `GET /api/v1/webhooks/whatsapp` — verificación de Meta
- Público. Query: `hub.mode`, `hub.verify_token`, `hub.challenge`.
- 200 texto plano con el `challenge` si `mode == "subscribe"` y el token coincide con
  `settings.meta_whatsapp_verify_token`. 403 (`HTTPException`, no excepción de dominio) si no.

### `POST /api/v1/webhooks/whatsapp` — recepción de mensajes de Meta
- Valida firma HMAC-SHA256 (`X-Hub-Signature-256`) contra `meta_whatsapp_webhook_secret` — **se
  omite en `APP_ENV=development`** (bypass explícito de seguridad, solo aceptable en local).
- 403 si firma inválida. 404 si `body.object != "whatsapp_business_account"`.
- Delega a `ProcessWhatsAppMessageUseCase` (clasifica intención vía OpenAI, actualiza
  `whatsapp_consent_status`, y si `ACCEPTED` transiciona el candidato a `PROFILING_QUEUED` y
  encola `start_profiling_call` con un countdown de `settings.profiling_delay_seconds` (24h
  default)). **Ya no es el único disparador de profiling** — ahora también existe
  `POST /processes/{id}/profiling/trigger` (manual, ver §8) montado en producción.
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
  este webhook; usa `get_active_ai_prompt_sync`/`get_active_ai_model_sync` — ver hallazgo sobre
  `ai-config` en §10/§Hallazgos).

---

## 7. Debug (`/api/v1/debug`) — solo si `APP_ENV != production`

Sin cambios desde el audit anterior. **No montado en producción** (`if not settings.is_production`
en `main.py`). Sin protección de rol más allá de estar deshabilitado en prod.

### `POST /api/v1/debug/seed-whatsapp-test`
- Body: `{ phone, candidate_name?, candidate_email?, job_title? }`.
- Crea (o reusa) un recruiter de prueba, un `HiringProcess` y un `Candidate` con ese teléfono en
  estado `PENDING` de consentimiento. Sin auth alguna (ni siquiera rol).

### `POST /api/v1/debug/simulate-whatsapp-message`
- Body: `{ from_phone, message }`. Ejecuta el mismo `ProcessWhatsAppMessageUseCase` que el webhook real.

### `POST /api/v1/debug/trigger-profiling-call/{process_candidate_id}`
- Sin body. Encola `start_profiling_call.delay(...)` directamente, saltándose el flujo de
  consentimiento de WhatsApp y el delay de 24h. Sigue siendo dev-only, pero **ya no es la única
  forma de iniciar profiling manualmente** — en producción ahora existe
  `POST /processes/{id}/profiling/trigger` (§8), que sí respeta RB-003/RB-004.

---

## 8. Profiling (`src/api/v1/profiling.py`) — **nuevo router, no existía en el audit anterior**

Expone dos routers montados con prefijos distintos: `router` bajo `/processes/{process_id}/profiling/...`
y `global_router` bajo `/profiling/...` (vista global, cross-proceso).

### `POST /api/v1/processes/{process_id}/profiling/trigger` — disparo manual de profiling (RB-004)
- Auth: RequireRecruiter.
- Body: `{ process_candidate_ids: uuid[] }`.
- 404 si el proceso no existe. 422 (`require_active_process`) si `CLOSED`/`ARCHIVED`. 422
  (**RB-004**, `require_manual_candidate_selection`) si `process_candidate_ids` viene vacío. 422
  (**RB-003**, `require_question_set_for_profiling`) si el proceso no tiene `question_set_id` —
  usar primero `PATCH /processes/{id}/question-set` (§2).
- Por cada id en el body: si no existe en este proceso o su estado actual no es `MATCHED`, se
  reporta en `skipped` (no aborta el resto del batch, a diferencia de la subida de CVs). Si es
  elegible, transiciona `MATCHED → SELECTED_FOR_PROFILING → PROFILING_QUEUED` (dos saltos de la
  máquina de estados en la misma request) y encola `start_profiling_call.delay(...)`.
- **RB-005 (máx. llamadas concurrentes) y RB-010 (presupuesto) no se validan en este endpoint** —
  se validan dentro de `InitiateProfilingCallUseCase`, que corre *dentro* de la tarea Celery
  `start_profiling_call`, no en el request HTTP. Es decir, este endpoint puede devolver `200` con
  candidatos "queued" que luego fallan silenciosamente en background si se supera el límite de
  concurrencia o el presupuesto — el frontend no se entera por esta respuesta, tiene que hacer
  polling de `GET .../profiling/runs` para ver el estado real.
- 200: `{ process_id, queued: int, tasks: [{ process_candidate_id, task_id }], skipped: [{
  process_candidate_id, reason }] }`.

### `GET /api/v1/processes/{process_id}/profiling/runs` — runs de un proceso
- Auth: cualquier usuario autenticado (**sin filtro de dueño** — cualquiera con rol suficiente ve
  los runs de cualquier proceso, a diferencia del endpoint global de abajo que sí filtra para
  `RECRUITER`).
- 200: `{ total, profiling_runs: [...] }` (ver shape de `_serialize_run` abajo), orden `created_at desc`.

### `GET /api/v1/profiling/runs` — listado global (vista `/profiling` del frontend)
- Auth: cualquier usuario autenticado. **Filtro por rol**: si `RECRUITER`, solo ve runs de procesos
  donde `HiringProcess.recruiter_id == current_user.id`. `ADMIN`/`TA_LEADER` ven todos.
- 200: mismo shape que el anterior.
- Shape de cada `profiling_run` (`_serialize_run`): `id, process_candidate_id, candidate_id,
  candidate_name, question_set_id, status (ProfilingRunStatus), call_attempts,
  advancement_probability, advancement_explanation, transcription_url, transcript_summary,
  started_at, completed_at, created_at, updated_at`.

### `GET /api/v1/profiling/runs/{run_id}` — detalle de un run
- Auth: cualquier usuario autenticado. 404 si no existe.

### `GET /api/v1/profiling/runs/{run_id}/answers` — respuestas evaluadas del run
- Auth: cualquier usuario autenticado.
- 200: `{ answers: [{ id, question: { id, text, weight, is_critical }, transcription,
  normalized_answer, evaluation_result, confidence_score (float|null), requires_review }] }`,
  orden por `question.order_index`.

### `POST /api/v1/profiling/runs/{run_id}/cancel` — cancelar una llamada en cola
- Auth: RequireRecruiter.
- 404 si no existe. 422 si `run.status != QUEUED` (solo se pueden cancelar llamadas que **aún no
  empezaron** — no hay forma de cancelar una llamada `CALLING`/`ANSWERED` en curso vía API).
- Efecto: `ProfilingRunStatus.FAILED` + transiciona el `ProcessCandidate` a `PROFILING_FAILED`.
- 200: `{ message: "Llamada cancelada correctamente" }`.

### `PATCH /api/v1/profiling/runs/{run_id}/override` — sobrescribir evaluación de un run
- Auth: RequireRecruiter.
- Body: `{ advancement_probability: string, advancement_explanation: string }`.
- 404 si no existe. 422 si `run.status` no es `EVALUATED` ni `COMPLETED`.
- Registra `AuditLog` (`action="MANUAL_OVERRIDE"`) antes del commit.
- 200: el run serializado completo (con los dos campos ya sobrescritos).

---

## 9. Metrics (`/api/v1/metrics`) — **nuevo router**

### `GET /api/v1/metrics/dashboard`
- Auth: RequireRecruiter (**sin filtro de dueño** — cualquier recruiter/TA/admin ve el dashboard
  agregado de *todos* los procesos y *todos* los usuarios del sistema, no solo los propios).
- Agrega `CostLog` (creado por las tareas Celery de CV/match/WhatsApp/voz) por proceso, por
  usuario, por tipo de operación y por día.
- 200: `{ total_cost_usd, cost_by_process: [{ process_id, process_name, total_cost,
  candidate_count }], cost_by_user: [{ user_id, user_name, total_cost }], cost_by_operation:
  [{ operation_type, total_cost, count }], daily_costs: [{ date, cost }] }`.

---

## 10. AI Config (`/api/v1/ai-config`) — **nuevo router**

CRUD para elegir qué modelo/proveedor de IA y qué versión de prompt usa cada tarea. Lecturas:
cualquier usuario autenticado. Mutaciones: **`RequireAdmin`** (más estricto que el resto de la
API, que usa `RequireRecruiter` para casi todo).

### `GET /api/v1/ai-config/models` / `POST /api/v1/ai-config/models` (201) / `PATCH /api/v1/ai-config/models/{model_id}/activate`
- `AIModelConfiguration`: `task_type, provider, model_name, api_key_secret_ref?`. Se crea siempre
  `is_active=false`; `activate` desactiva los demás modelos **del mismo `task_type`** y activa el
  pedido (exclusión mutua *dentro* de un `task_type`, no entre distintos).
- **Hallazgo crítico de integridad**: el único consumidor real,
  `get_active_ai_model_sync(db, provider, fallback_model)` (`src/infrastructure/cache/redis_client.py`,
  usado por las tareas Celery `parse_cv` y `profiling`), filtra **solo por `provider`**
  (`WHERE provider = 'OPENAI' AND is_active = true`), ignorando `task_type` por completo. Como
  `activate_model` solo impide dos activos para el mismo `task_type`, es perfectamente posible —
  vía esta misma API — activar simultáneamente un modelo para `task_type="PROFILE_EXTRACT"` y otro
  para `task_type="VOICE_PROFILING"`, ambos con `provider="OPENAI"`. La siguiente vez que corra
  `parse_cv` o la evaluación de profiling, la query de `get_active_ai_model_sync` encontrará **2
  filas** y `scalar_one_or_none()` lanzará `MultipleResultsFound`, tumbando esa tarea Celery. No hay
  ninguna validación en `POST /ai-config/models` ni en `.../activate` que lo prevenga.
- Ni el matching (`run_match`) ni los endpoints de JD (`/job-description/parse`, `/job-description/enhance`,
  §2) leen `AIModelConfiguration` — usan `gpt-4o` hardcodeado en el código. Activar un modelo
  distinto en `ai-config` para esas tareas **no tiene ningún efecto observable**.

### `GET /api/v1/ai-config/prompts` / `POST /api/v1/ai-config/prompts` (201)
- `AIPrompt`: append-only real (nunca se edita, cada `POST` es una versión nueva). `activate: bool`
  en el body desactiva las demás versiones activas del mismo `task_type` antes de insertar.
- Consumidor real: `get_active_ai_prompt_sync(db, task_type, fallback)`, cacheado en Redis (TTL no
  documentado aquí, ver `redis_client.py`), usado solo por `parse_cv` (`task_type="PROFILE_EXTRACT"`)
  y la evaluación de profiling (`task_type="VOICE_PROFILING"`) — igual que arriba, el matching y
  los endpoints de JD **no leen esta tabla**.

### `GET /api/v1/ai-config/global-settings` / `PATCH /api/v1/ai-config/global-settings/{setting_key}`
- `GlobalBusinessSetting`: upsert por `setting_key` (crea la fila si no existe — no hay seed). El
  PATCH invalida la cache Redis de esa key (`global_setting:{setting_key}`) tras guardar.

---

## 11. Users (`/api/v1/users`) — **nuevo router**

Gestión de cuentas de usuario del sistema (recruiters/admins/TA leads), no de candidatos. Todo
`RequireAdmin`.

### `GET /api/v1/users` — listar
- 200: `list[UserResponse]` donde `UserResponse = { id, name, last_name, email, role, status,
  created_at }`. **Con `response_model` real** (a diferencia de casi todo el resto de la API).

### `POST /api/v1/users` — crear (201)
- Body: `{ name, last_name, email (EmailStr), password (min 8), role }`.
- **409 `ConflictException`** si el email ya existe (`CreateUserUseCase`) — primer caso real de uso
  de esta excepción en toda la API.
- Registra `AuditLog` (`action="USER_MANAGEMENT"`).

### `PATCH /api/v1/users/{user_id}` — editar
- Todos los campos opcionales; si se manda `email` y difiere del actual, vuelve a chequear
  duplicado (409 si ya existe). Si se manda `password`, se re-hashea.
- Registra `AuditLog`.

### `PATCH /api/v1/users/{user_id}/status` — cambiar estado (activar/suspender)
- Body: `{ status: UserStatus }`. 422 si el valor no es un `UserStatus` válido.
- Registra `AuditLog`.
- No hay endpoint para eliminar un usuario, solo para suspenderlo (`status`).

---

## 12. Routers definidos pero NO montados — código muerto hoy

Estos cuatro archivos existen bajo `src/api/v1/` con su propio `APIRouter` y endpoints funcionales,
pero **`src/api/main.py` no los importa ni los registra con `include_router`** — no son alcanzables
por HTTP en ningún entorno hasta que alguien los monte. Se documentan porque el frontend podría
asumir por error que existen (aparecen en el código, en `git log`, y algunos duplican
funcionalidad que sí está montada en otro lado).

### `ai_tools.py` — `POST /ai-tools/enhance-jd`
- Duplica `POST /processes/{id}/job-description/enhance` (§2) pero con una clase de caso de uso
  *distinta* (`src.application.ai.enhance_jd_usecase.EnhanceJDUseCase(db)`, no la que sí está en
  uso). No persiste nada, solo devuelve `{ enhanced_text }`.

### `audit.py` — `GET /audit-logs`
- Sería la única forma de **leer** los `AuditLog` que sí se están escribiendo activamente desde
  `auth.login`, `candidates.override`, `users.*` y `profiling.override` (ver notas en cada
  sección). Hoy esa escritura ocurre pero **no hay ninguna forma de consultarla vía API** — el
  audit trail es de solo-escritura en la práctica. Filtros previstos: `action`, `entity_type`,
  paginación `limit`/`offset`.

### `feedback.py` — `POST /feedback`
- Registraría feedback humano (`CORRECT`/`PARTIAL`/`INCORRECT`) sobre una evaluación de IA
  (match o profiling) de un `ProcessCandidate`, en la tabla `AIFeedback`. Sin este router montado,
  esa tabla nunca se puebla desde HTTP.

### `reports.py` — `GET /reports/ta-dashboard`
- Dashboard agregado para `TA_LEADER` (`RequireTALeader`): total de procesos, procesos activos,
  total de candidatos, costo total. Similar a `GET /metrics/dashboard` pero con métricas distintas
  y rol requerido distinto.

---

## Hallazgos relevantes para el frontend (riesgos / incompletitud)

1. **`GET /processes/{id}/export/ranking` y `GET /processes/{id}/export/costs` están rotos —
   `NameError` garantizado.** Usan `csv`, `StringIO`, `ProcessCandidate` y `CostLog` sin
   importarlos en `processes.py`. Cualquier llamada real devuelve 500. No conectar estos botones de
   exportación en el frontend hasta que se corrija (ver §2).

2. **Editar una pregunta o metadata de un `QuestionSet` `ACTIVE`/en uso clona el set y NO
   re-asocia los procesos existentes al clon.** El `id` que vuelve en la respuesta de `PATCH
   /question-sets/{id}` (y de los 3 endpoints de preguntas) puede diferir del `question_set_id` de
   la URL. Si el frontend no lee ese `id` de vuelta y no llama a `PATCH
   /processes/{id}/question-set` con el nuevo id, los procesos que ya usaban el set seguirán
   ejecutando la versión vieja — el usuario verá que "guardó" cambios que nunca se aplican a sus
   procesos activos (ver §5).

3. **Activar dos `AIModelConfiguration` con el mismo `provider` pero distinto `task_type` rompe
   `parse_cv` y la evaluación de profiling con `MultipleResultsFound`** en la próxima ejecución de
   esas tareas Celery — el bug no se manifiesta en el momento de `PATCH
   /ai-config/models/{id}/activate` (que responde 200 normal), sino después, en background, sin
   ninguna notificación al usuario que lo activó (ver §10).

4. **`ai-config` no controla el matching de CVs ni el análisis/mejora de JD con IA** — esos tres
   flujos usan `gpt-4o` y prompts hardcodeados en el código, ignorando `AIModelConfiguration`/`AIPrompt`
   por completo. Solo `parse_cv` (extracción de CV) y la evaluación de profiling leen esas tablas.
   Si el frontend expone una pantalla de "configuración de IA" que sugiere control total sobre
   todas las tareas, hoy sería engañosa para 3 de las 5 (match, JD parse, JD enhance).

5. **El audit trail (`AuditLog`) es de solo-escritura hoy.** `auth.login`, el override de
   candidatos, la gestión de usuarios y el override de profiling ya registran entradas, pero el
   único endpoint para leerlas (`GET /audit-logs`, en `audit.py`) no está montado en `main.py`
   (§12) — no hay forma de ver el historial de auditoría vía API todavía.

6. **`POST /processes/{id}/match` sigue mutando `process.status` sin pasar por
   `HiringProcessStateMachine.transition()`** (asignación directa) — inconsistente con `PATCH
   /processes/{id}/status`, que sí valida transiciones. Riesgo de estado inválido si se llama en
   un momento no contemplado por la máquina de estados.

7. **RB-005 (concurrencia) y RB-010 (presupuesto) en profiling se validan dentro de la tarea
   Celery, no en el endpoint HTTP.** `POST /processes/{id}/profiling/trigger` puede responder
   `200 queued` para candidatos que luego fallan en background por exceso de concurrencia o de
   presupuesto — sin que esa respuesta lo refleje. El frontend necesita hacer polling de
   `GET .../profiling/runs` para detectar el fallo real.

8. **`ai-tools.py` duplica `job-description/enhance` con una implementación distinta e
   inalcanzable** (código muerto, no montado) — si alguien lo monta a futuro sin darse cuenta de
   que ya existe una versión funcionando en `processes.py`, quedarían dos endpoints con
   comportamiento distinto para "lo mismo". Vale la pena eliminarlo en vez de montarlo.

9. **SSE mencionado en el PRD no existe.** `RIWI_MATCH.md` línea 537 describe "el backend emite un
   evento vía SSE" al persistir la evaluación de profiling — no hay ningún endpoint SSE/WebSocket
   en el código. El único mecanismo de progreso en tiempo real disponible hoy es **polling** vía
   `GET /processes/{id}/match/status` y `GET /profiling/runs`.

10. **Sin `response_model` en casi ningún endpoint de negocio** salvo `auth.py` (`TokenResponse`) y
    `users.py` (`UserResponse`, nuevo). El resto (`processes`, `candidates`, `match`,
    `question_sets`, `profiling`, `metrics`, `ai_config`) retorna `dict` suelto — el shape
    documentado aquí viene de leer el código línea por línea, no de OpenAPI/Swagger generado.

11. **Endpoints de descarga de archivo (`cv/file`, `cv-normalized/file`, `job-description/file`)
    devuelven 302 con URL firmada de R2**, no el archivo directo ni JSON con la URL — el frontend
    debe usarlos como `href`/`src` de un `<a>`/`<iframe>` (aceptan `?token=` para eso), no
    `fetch()`+parsear JSON.

12. **`whatsapp/send` y el flujo de reintento de consentimiento no tiene endpoint para "cancelar" o
    resetear un `whatsapp_consent_status` distinto de `ACCEPTED`/`REJECTED`** — solo se puede
    reenviar mientras siga `PENDING` o `TIMEOUT`.

13. **`upload_cvs` reporta `status: "LOADED"` siempre** en la respuesta, incluso para candidatos
    deduplicados/reusados cuyo estado real ya es `MATCH_PENDING` — no confiar en ese campo de la
    respuesta del upload para decidir el estado inicial en el Kanban; conviene refetch de
    `GET /candidates` tras el upload.

14. **Falta de scoping por dueño es la norma, no la excepción, y ahora incluye datos de costos.**
    Endpoints que sí filtran por `recruiter_id`: `GET /processes`, `GET /profiling/runs` (global).
    Endpoints que NO filtran (cualquier rol suficiente ve todo el sistema): `GET
    /metrics/dashboard`, `GET /processes/{id}/metrics`, `GET /processes/{id}/profiling/runs`,
    `GET /ai-config/*`, `GET /question-sets`. Si el frontend necesita aislar datos por recruiter
    más allá del Kanban de procesos, hoy tiene que hacerlo client-side filtrando por
    `process_id`/`recruiter_id` — el backend no lo hace por él.
