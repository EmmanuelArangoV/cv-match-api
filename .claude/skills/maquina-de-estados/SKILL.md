---
name: maquina-de-estados
description: Úsala en cv-match-api al trabajar con el ciclo de vida de un candidato o de un proceso de contratación, o al aplicar cualquier regla de negocio RB-001..RB-010. Es la referencia autoritativa de las dos máquinas de estado, sus transiciones válidas, estados terminales, helpers de guarda y las reglas RB con dónde se aplican. Garantiza que ningún cambio de estado ni acción viole las invariantes del dominio.
---

# Máquinas de estado y reglas de negocio (cv-match-api)

El dominio tiene **dos** máquinas de estado estrictas y un conjunto de reglas de negocio
`RB-xxx`. Toda operación que cambie estado o ejecute una acción del flujo debe respetarlas.
La fuente de verdad es el dominio, no los routers ni los workers.

- Candidato: `src/domain/candidate/state_machine.py` (`CandidateStateMachine`, mapa `_TRANSITIONS`).
- Proceso: `src/domain/hiring_process/state_machine.py` (`HiringProcessStateMachine`, mapa `_TRANSITIONS`).
- Reglas: `src/domain/hiring_process/rules.py` (`HiringProcessRules`).
- Enums: `src/infrastructure/db/models.py` (`CandidateStatus`, `ProcessStatus`, `WhatsAppConsentStatus`, `OperationType`).

## Máquina del CANDIDATO

Flujo feliz y ramas de error/reversión:

```
LOADED → CV_PROCESSING → MATCH_PENDING → MATCHED → SELECTED_FOR_PROFILING
       → PROFILING_QUEUED → PROFILING_CALLING → PROFILING_COMPLETED (terminal)

CV_PROCESSING → CV_ERROR → CV_PROCESSING            (reintento)
MATCHED → MATCH_PENDING                              (reprocesar si cambia el JD)
MATCHED → DISCARDED → MATCHED                        (RB-008: recruiter revierte)
SELECTED_FOR_PROFILING → MATCHED                     (deseleccionar)
PROFILING_QUEUED → SELECTED_FOR_PROFILING            (cancelado de la cola)
PROFILING_CALLING → PROFILING_FAILED → PROFILING_QUEUED | DISCARDED
```

- Terminal: `PROFILING_COMPLETED` (permite override humano posterior).
- Guardas: `can_be_ranked(status)` (RB-002), `can_be_selected_for_profiling(status)` (== MATCHED).

## Máquina del PROCESO

```
DRAFT → CVS_UPLOADED → MATCH_PROCESSING → MATCH_DONE → PROFILING_CONFIGURED
      → PROFILING_ACTIVE → PROFILING_COMPLETED → CLOSED → ARCHIVED (terminal)
```

Ramas de reproceso/carga: `CVS_UPLOADED`/`MATCH_DONE`/`PROFILING_CONFIGURED` pueden volver a
`MATCH_PROCESSING` (reprocesar con nuevo JD) o `CVS_UPLOADED` (cargar más CVs); casi todos
pueden ir a `CLOSED`. `PROFILING_ACTIVE → PROFILING_CONFIGURED` (cancelar profiling).

- Guardas: `can_upload_cvs`, `can_run_match`, `can_start_profiling`, `is_active` (falso si CLOSED/ARCHIVED).

## Cómo cambiar de estado correctamente

En capa de aplicación/servicios (sesión async):

```python
from src.domain.candidate.state_machine import CandidateStateMachine
from src.infrastructure.db.models import CandidateStatus

target = CandidateStateMachine.transition(CandidateStatus(pc.status), CandidateStatus.MATCHED)
pc.status = target.value   # solo tras validar
```

`transition()` lanza `BusinessRuleException` (→ HTTP 422 vía `src/api/main.py`) si la
transición no está en `_TRANSITIONS`. **Nunca** asignes un estado sin pasar por aquí en la
capa de aplicación. En workers Celery el estado se asigna como string por rendimiento, pero
debe respetar el mapa (ver [[crear-tarea-celery]]). Para añadir una transición nueva usa
[[agregar-transicion-estado]].

## Reglas de negocio RB-001..RB-010

Valida la regla **antes** de ejecutar la acción, lanzando la excepción de dominio adecuada
(nunca `HTTPException`). Tabla y dónde viven:

| Regla | Qué exige | Dónde se aplica |
|-------|-----------|-----------------|
| RB-001 | No hay match sin Job Description activa | `HiringProcessRules.require_job_description`; `api/v1/match.py`, `workers/tasks/run_match.py` |
| RB-002 | Un CV no se rankea si no fue procesado (no en LOADED/CV_PROCESSING/CV_ERROR) | `HiringProcessRules.require_cv_processed`, `CandidateStateMachine.can_be_ranked`; `run_match.py` |
| RB-003 | Profiling requiere set de preguntas asignado | `HiringProcessRules.require_question_set_for_profiling` |
| RB-004 | No se inician llamadas sin selección manual del usuario | `HiringProcessRules.require_manual_candidate_selection` |
| RB-005 | Concurrencia máx. de llamadas activas (default 4) | `HiringProcessRules.enforce_max_concurrent_calls` |
| RB-006 | Preguntas críticas incumplidas → resultado mínimo MEDIUM | `src/domain/profiling/value_objects.py` |
| RB-007 | Respuesta crítica incorrecta → puede bajar a LOW | `src/domain/profiling/value_objects.py` |
| RB-008 | Un candidato **nunca** se descarta automáticamente; el recruiter puede revertir (`DISCARDED → MATCHED`) | `CandidateStateMachine` (transición y `is_discarded_automatically_blocked`) |
| RB-009 | No se ejecutan acciones en proceso CLOSED/ARCHIVED | `HiringProcessRules.require_active_process`; `api/v1/processes.py`, `api/v1/match.py` |
| RB-010 | Si el costo supera el presupuesto, bloquear nuevas ejecuciones | `HiringProcessRules.require_budget_available` |

Consentimiento WhatsApp (`can_candidate_be_called`): `REJECTED` → no llamar; `ACCEPTED` →
llamar sin pedir consentimiento; `PENDING`/`TIMEOUT` → llamada en frío pidiendo consentimiento.

## Invariantes que nunca debes romper

- Ningún `pc.status = ...` en capa de aplicación sin `transition()`.
- Nunca descartar un candidato de forma automática (RB-008).
- Nunca operar sobre un proceso CLOSED/ARCHIVED (RB-009); usa `is_active`/`require_active_process`.
- Nunca ejecutar match sin JD (RB-001) ni rankear un CV no procesado (RB-002).
- Señala violaciones con `BusinessRuleException` (422), no con `HTTPException`.

## Verificación

- Transición válida pasa; inválida lanza `BusinessRuleException` → 422 vía API.
- Cada acción de flujo valida su regla RB antes de ejecutarse.
- `ruff check src/` y `mypy src/` sin errores.
