---
name: crear-tarea-celery
description: Úsala al crear o modificar una tarea Celery en cv-match-api (parseo de CV, matching, WhatsApp, profiling u otras cargas pesadas). Garantiza el andamiaje correcto — registro en celery_app, sesión síncrona, manejo de errores con rollback + estado de error + retry, y registro de costo en CostLog — para no dejar estados inconsistentes ni fugas de sesión.
---

# Crear una tarea Celery en cv-match-api

El trabajo pesado (parseo de CV, matching, mensajes de WhatsApp, llamadas de profiling)
corre en tareas Celery, **nunca** en los request handlers de FastAPI. El handler solo
encola con `.delay(...)` y responde. Sigue este procedimiento para que la tarea quede bien.

## Contexto obligatorio

- Broker/backend: Redis (Upstash, TLS `rediss://`). Config en `src/infrastructure/workers/celery_app.py`.
- Las tareas usan sesión **síncrona** con `DATABASE_URL_SYNC` (psycopg2), **no** la async de la app.
- Referencia canónica: `src/infrastructure/workers/tasks/parse_cv.py`.

## Pasos

1. **Crea el módulo** en `src/infrastructure/workers/tasks/<nombre>.py`.

2. **Registra la tarea** añadiendo la ruta del módulo a la lista `include=[...]` de
   `src/infrastructure/workers/celery_app.py`. Si no la registras, el worker no la carga.

3. **Crea el engine/session síncronos a nivel de módulo** (uno por proceso worker):
   ```python
   from sqlalchemy import create_engine
   from sqlalchemy.orm import sessionmaker
   from src.config import settings

   _engine = create_engine(settings.database_url_sync)
   _SyncSession = sessionmaker(bind=_engine)
   ```

4. **Declara la tarea** con `bind=True` (para acceder a `self` y hacer `self.retry`),
   un `max_retries`, un `default_retry_delay` y un `name` explícito y estable:
   ```python
   @celery_app.task(bind=True, max_retries=2, default_retry_delay=60, name="<nombre>")
   def <nombre>(self, ...ids como str...) -> dict:
   ```
   Pasa los identificadores como **strings** (JSON serializable) y conviértelos a `uuid.UUID`
   dentro de la función. El serializer es `json` (ver `celery_app.conf`).

5. **Importa los modelos DENTRO de la función**, no en el encabezado del módulo:
   ```python
   from src.infrastructure.db.models import Candidate, CandidateStatus, ProcessCandidate, CostLog, OperationType
   ```
   Esto evita imports circulares entre workers y modelos.

6. **Envuelve toda la lógica en `with _SyncSession() as db:` y un `try/except`**:
   - Marca el estado "en proceso" al inicio y haz `db.commit()`.
   - Ejecuta el trabajo. Respeta el orden de estados definido en las máquinas de estado
     (`src/domain/candidate/state_machine.py`) — si añades una transición nueva usa la skill
     [[agregar-transicion-estado]].
   - Al final, deja el estado de éxito y `db.commit()`.

7. **En el `except`: rollback, marca estado de error y reintenta**:
   ```python
   except Exception as exc:
       db.rollback()
       try:
           pc = db.get(ProcessCandidate, pc_uuid)
           if pc:
               pc.status = CandidateStatus.<X>_ERROR.value
               db.commit()
       except Exception:
           pass
       raise self.retry(exc=exc)
   ```
   Nunca dejes un registro atascado en el estado "en proceso" si la tarea falla.

8. **Registra el costo en `CostLog`** cuando la tarea consuma un servicio pagado
   (OpenAI, ElevenLabs). Calcula `estimated_cost` con las constantes de tokens del módulo,
   crea el `CostLog` con `operation_type=OperationType.<X>.value`, `model_used`, `tokens_input`,
   `tokens_output`, y añádelo antes del commit final.

9. **Encadena tareas** con `<otra_tarea>.delay(...)` al final del bloque de éxito
   (ej.: `parse_cv` dispara `run_match` y, si hay credenciales, `send_whatsapp_consent`).
   Nunca llames a otra tarea de forma síncrona.

10. **Encola desde el caso de uso**, no en la tarea: el handler/caso de uso hace
    `<nombre>.delay(id1=str(...), id2=str(...))`.

## Verificación

- El worker arranca sin error y lista la tarea: `celery -A src.infrastructure.workers.celery_app worker --loglevel=info` (en Windows añade `--pool=solo`).
- Fuerza un fallo controlado y confirma que el registro queda en estado `*_ERROR` (no en el estado "en proceso") y que hubo `retry`.
- `ruff check src/` y `mypy src/` sin errores.
