# CLAUDE.md — Backend RIWI MATCH

FastAPI + Celery de RIWI MATCH. Lee primero [`AGENTS.md`](AGENTS.md).

## Capas

- `src/api/`: FastAPI, schemas, dependencias JWT/roles, webhooks y mapeo de errores.
- `src/application/`: casos de uso y servicios de aplicación.
- `src/domain/`: reglas puras, enums, máquinas de estado y excepciones.
- `src/infrastructure/`: SQLAlchemy, repositorios, Celery, OpenAI, R2, Meta, Twilio y ElevenLabs.

`src/api/main.py` debe montar cada router. Lanza `DomainException` y sus subclases desde negocio;
no acoples `HTTPException` a dominio/aplicación.

## Pipeline vigente

`ProcessCandidate` es el estado de negocio y `ProfilingRun` representa cada intento técnico. Las
transiciones y la proyección compartida viven en `src/application/profiling/lifecycle.py` y
`src/application/hiring_process/progress.py`. API, tareas y webhooks deben usar esos servicios.
Celery Beat ejecuta el watchdog que repara o falla intentos `CALLING`/`ANSWERED` estancados,
incluidos registros históricos sin timestamp completo.

Extracción de CV y match no se encadenan automáticamente:

1. upload crea candidatos `LOADED`;
2. `candidates/analyze` procesa `LOADED`/`CV_ERROR`;
3. al terminar quedan listos para match;
4. `processes/{id}/match` se ejecuta por acción humana.

## Modelos, prompts y comunicaciones

- El modelo activo de workloads es `gpt-5.6-luna`; evita strings de modelo dispersos.
- Prompts globales Admin: `CV_EXTRACTION`, `CV_MATCH`, `JD_ENHANCEMENT`, `VOICE_PROFILING`.
- Prompts por proceso: `WHATSAPP_MESSAGE`, `VOICE_CALL_AGENT`.
- `VOICE_CALL_AGENT` versiona `first_message` y system prompt. No hay fallback al Question Set.
- Question Sets solo contienen preguntas, pesos, criticidad y criterios.
- `WhatsAppTemplate` conserva nombre Meta, idioma, categoría, componentes, botones, estado,
  habilitación y default. Solo una plantilla aprobada/habilitada puede asignarse a un proceso.
- Twilio registra la llamada con ElevenLabs y precarga contexto/TwiML en Redis durante el ring.
  AMD puede estar deshabilitado, síncrono o asíncrono según variables.

No aceptes overrides arbitrarios en la llamada: solo los campos explícitamente permitidos. Firma
y correlaciona webhooks Twilio, ElevenLabs y Meta.

## Costos

Cada etapa pagada registra `CostLog`: almacenamiento, extracción, match, WhatsApp, telefonía,
ElevenLabs y evaluación final. Conserva proveedor, operación, modelo, unidades,
`provider_reported` frente a `rate_card`, referencia externa y breakdown. La API agrega; el
frontend no estima.

## Comandos

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/alembic upgrade head
.venv/bin/uvicorn src.api.main:app --reload --port 8000
.venv/bin/celery -A src.infrastructure.workers.celery_app worker --loglevel=info
.venv/bin/celery -A src.infrastructure.workers.celery_app beat --loglevel=info

.venv/bin/ruff check src tests
.venv/bin/python scripts/check_mypy_ratchet.py
.venv/bin/pytest -q tests
```

El `pytest -q` sin `tests` también puede recolectar scripts manuales; la suite automatizada es
`pytest -q tests`.

## Contratos

- OpenAPI generado: `/openapi.json`; UI: `/docs`.
- Resumen por dominios: `docs/api_contract.md`.
- WhatsApp/plantillas: `docs/whatsapp_api_contract.md`.
- Variables: `.env.example` y `src/config.py`.
- Estado vigente: `STATUS_RESUMEN.md`.
