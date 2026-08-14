---
name: crear-tarea-celery
description: Úsala al crear o cambiar tareas Celery de RIWI MATCH. Cubre registro, sesiones, lifecycle, idempotencia, retries, costos y publicación segura.
---

# Crear o cambiar una tarea Celery

El request handler valida/persiste el estado inicial y publica trabajo; no ejecuta cargas pesadas.
Antes de usar una receta genérica, lee una tarea vigente del mismo dominio y el lifecycle
correspondiente.

## Reglas

1. Registra el módulo en `src/infrastructure/workers/celery_app.py` y usa un nombre de tarea
   explícito/estable.
2. Payload JSON: IDs como strings; evita objetos ORM o datos sensibles.
3. Usa la sesión adecuada y una transacción acotada. Rollback ante fallo.
4. La tarea debe tolerar entrega duplicada. Haz claim/guardas antes de cobrar o llamar proveedores.
5. No asignes estados técnicos de profiling directamente: usa
   `src/application/profiling/lifecycle.py` y propaga `run_id`.
6. Para candidatos/procesos, valida `CandidateStateMachine`/`HiringProcessStateMachine` y sincroniza
   la proyección central.
7. Persiste entidad/run antes de `.delay()`. Si la publicación falla, deja un estado recuperable y
   una respuesta coherente; no escondas el fallo.
8. Retry solo para fallos recuperables. Un retry no debe duplicar mensajes, llamadas ni costos.
9. Toda operación pagada crea/actualiza `CostLog` mediante helpers centrales, con
   `external_reference`, `cost_source`, proveedor y breakdown. No uses un simple
   `estimated_cost` calculado ad hoc.
10. No encadenes extracción → match ni análisis → WhatsApp automáticamente: son decisiones de
    usuario separadas. Solo encadena pasos que formen parte del mismo comando de negocio aprobado.

## Procesos periódicos

Celery Beat publica `check_stale_profiling_calls` y `resolve_whatsapp_timeouts`. Debe existir una
sola réplica de beat. Los reconciliadores no deben llamar proveedores al reparar proyecciones.

## Verificación

- worker arranca y registra la tarea;
- happy path, payload inexistente, duplicado, proveedor temporalmente caído y retry agotado;
- estado de error/terminal y proyección quedan coherentes;
- proveedor/costo aparece una sola vez;
- `ruff`, ratchet mypy y pruebas dirigidas pasan.

```bash
.venv/bin/celery -A src.infrastructure.workers.celery_app worker --loglevel=info
.venv/bin/ruff check src tests
.venv/bin/python scripts/check_mypy_ratchet.py
.venv/bin/pytest -q tests
```
