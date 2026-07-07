---
name: agregar-transicion-estado
description: Úsala al cambiar el estado de un candidato o de un proceso de contratación, o al añadir/modificar una transición de estado permitida en cv-match-api. Fuerza que todo cambio de estado respete el mapa _TRANSITIONS y pase la validación de la máquina de estados, evitando el bug clásico de asignar un estado no permitido y dejar el flujo inconsistente.
---

# Agregar o usar una transición de estado en cv-match-api

El ciclo de vida del candidato es una **máquina de estados estricta**. El flujo feliz es:

```
LOADED → CV_PROCESSING → MATCH_PENDING → MATCHED → SELECTED_FOR_PROFILING
       → PROFILING_QUEUED → PROFILING_CALLING → PROFILING_COMPLETED
```

más estados de error/reintento (`CV_ERROR`, `PROFILING_FAILED`) y `DISCARDED`.
Existe una máquina análoga para el proceso de contratación.

- Candidato: `src/domain/candidate/state_machine.py` (mapa `_TRANSITIONS`, clase `CandidateStateMachine`).
- Proceso: `src/domain/hiring_process/state_machine.py`.
- Los estados viven como enums en `src/infrastructure/db/models.py` (`CandidateStatus`, ...).

## Regla de oro

**Ninguna transición puede ocurrir si no está declarada en `_TRANSITIONS`.** Antes de
asignar un estado nuevo, valida contra la máquina de estados. Reglas de negocio relevantes:
RB-002 (`can_be_ranked`), RB-008 (un candidato **nunca** se descarta automáticamente y el
recruiter puede revertir un descarte: `DISCARDED → MATCHED`).

## Cómo cambiar un estado existente (caso de uso / servicio con sesión async)

```python
from src.domain.candidate.state_machine import CandidateStateMachine
from src.infrastructure.db.models import CandidateStatus

current = CandidateStatus(pc.status)
target = CandidateStateMachine.transition(current, CandidateStatus.MATCHED)  # lanza BusinessRuleException si es inválida
pc.status = target.value
```

`transition()` valida y devuelve el estado destino, o lanza `BusinessRuleException`
(que `src/api/main.py` mapea a HTTP 422). Nunca asignes `pc.status` sin pasar por aquí
en la capa de aplicación.

> Nota sobre workers: en las tareas Celery (p. ej. `parse_cv.py`) el estado se asigna como
> string (`pc.status = CandidateStatus.CV_PROCESSING.value`) por rendimiento, **pero debe
> respetar el orden permitido por `_TRANSITIONS`**. Si dudas, valida igualmente con
> `CandidateStateMachine.transition()`. Ver la skill [[crear-tarea-celery]].

## Cómo AÑADIR una transición nueva

1. Confirma que la transición tiene sentido de negocio y, si aplica, un código `RB-xxx`.
2. Añade el estado destino al `set` del estado origen en `_TRANSITIONS` (candidato o proceso):
   ```python
   CandidateStatus.MATCHED: {
       CandidateStatus.SELECTED_FOR_PROFILING,
       CandidateStatus.DISCARDED,
       CandidateStatus.MATCH_PENDING,   # reprocesar si cambia el JD
       # ← agrega aquí el nuevo destino, con comentario del porqué
   },
   ```
3. Si el nuevo destino es un estado nuevo, agrégalo primero al enum en `models.py` y crea la
   migración con la skill de migraciones alembic (revisa manualmente los enums).
4. Si necesitas un helper de consulta (tipo `can_be_ranked`), añádelo como `@staticmethod`
   en la clase de la máquina, con docstring que cite la regla `RB-xxx`.

## Anti-patrones a evitar

- ❌ `pc.status = "MATCHED"` o `pc.status = CandidateStatus.MATCHED.value` en un caso de uso sin validar.
- ❌ Agregar la transición solo en el código que la usa pero no en `_TRANSITIONS`.
- ❌ Descartar (`DISCARDED`) un candidato de forma automática desde una tarea (viola RB-008).

## Verificación

- Prueba una transición válida y una inválida; la inválida debe lanzar `BusinessRuleException`
  y, vía API, devolver 422.
- `ruff check src/` y `mypy src/` sin errores.
