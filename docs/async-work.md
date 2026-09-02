---
sidebar_position: 5
---

# Trabajo asíncrono: Celery, webhooks y watchdogs

La API se ocupa de validar, persistir y publicar trabajo. El worker ejecuta operaciones lentas y
el beat publica revisiones periódicas. Los tres procesos comparten el registro de tareas de
`src/infrastructure/workers/celery_app.py`, con Redis como broker y backend de resultados.

## Tareas registradas

| Tarea | Archivo | Entrada | Resultado de negocio |
| --- | --- | --- | --- |
| `parse_cv` | `tasks/parse_cv.py` | candidato, participación y proceso | Lee R2, extrae PDF/DOCX/imagen, normaliza el CV, genera embedding/PDF y registra costos. |
| `run_match` | `tasks/run_match.py` | participación y proceso | Evalúa CV normalizado contra la JD activa, guarda score/desglose y sincroniza progreso. |
| `send_whatsapp_consent` | `tasks/whatsapp.py` | `profiling_run_id` | Valida teléfono y plantilla aprobada; envía consentimiento o falla el intento con lifecycle. |
| `start_profiling_call` | `tasks/profiling.py` | `profiling_run_id` | Inicia la llamada mediante el caso de uso de profiling. |
| `retry_or_fail_profiling_call` | `tasks/profiling.py` | corrida y motivo | Reintenta dentro del límite o cierra el intento. |
| `evaluate_profiling_transcription` | `tasks/profiling.py` | corrida y transcript | Evalúa respuestas del Question Set y registra el costo de IA. |

Las tareas `parse_cv` y `run_match` se invocan por acciones humanas separadas. No se deben
encadenar para “agilizar” el pipeline, pues ocultaría una decisión explícita del reclutador.

## Trabajo programado

Celery Beat ejecuta una sola réplica y programa:

- `check_stale_profiling_calls`: revisa corridas `CALLING`/`ANSWERED` estancadas; usa bloqueo
  por fila (`SKIP LOCKED`) y no publica otra llamada al reparar registros antiguos.
- `resolve_whatsapp_timeouts`: resuelve consentimientos `PENDING` vencidos, mueve la corrida a
  cola mediante lifecycle y entonces publica el inicio de llamada.

El intervalo procede de la configuración. Un worker puede escalarse si la carga lo exige; Beat no,
para no duplicar watchdogs.

## Reintentos, idempotencia y callbacks

Errores de dominio (por ejemplo, transición inválida o recurso inexistente) no son transitorios y
no deben reintentarse. Los fallos de infraestructura se reintentan con el límite de la tarea.
Cada operación pagada debe persistir un `CostLog` idempotente con una referencia externa o del
intento Celery.

Webhooks de Meta, Twilio y ElevenLabs deben verificar firma, correlacionar la corrida y llamar al
lifecycle. Un callback repetido no puede duplicar una llamada, una transición ni un costo.
