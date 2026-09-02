# RIWI MATCH Backend

API y workers de la plataforma RIWI MATCH. Implementa autenticación por roles, procesos/JD,
extracción de CV, match explicable, profiling con WhatsApp + Twilio + ElevenLabs, configuración de
IA, costos, auditoría, métricas, reportes y búsqueda.

La autenticación admite cuentas locales y SSO central mediante Órbita. Match valida el JWT RS256
de Órbita, aprovisiona una identidad local vinculada por `orbita_user_id` y emite su propia sesión
con los permisos `ADMIN`, `TA_LEADER` o `RECRUITER`.

## Stack

- Python 3.12, FastAPI y Pydantic.
- SQLAlchemy 2 async, Alembic, PostgreSQL + pgvector.
- Celery worker/beat y Redis.
- Cloudflare R2, OpenAI, Meta WhatsApp, Twilio y ElevenLabs.

## Inicio rápido

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env
.venv/bin/alembic upgrade head
.venv/bin/uvicorn src.api.main:app --reload --port 8000
```

En terminales separadas:

```bash
.venv/bin/celery -A src.infrastructure.workers.celery_app worker --loglevel=info
.venv/bin/celery -A src.infrastructure.workers.celery_app beat --loglevel=info
```

- Health: <http://localhost:8000/health>
- Readiness: <http://localhost:8000/ready>
- Swagger: <http://localhost:8000/docs>

Para webhooks locales ejecuta `ngrok http 8000`, actualiza `PUBLIC_BASE_URL` y registra las URLs
descritas en `../.agents/skills/start-project/SKILL.md`.

## Flujo de negocio

```text
Proceso + JD
  → carga de CV
  → análisis de CV (manual)
  → match (manual)
  → selección para profiling
  → plantilla WhatsApp + consentimiento
  → llamada Twilio/ElevenLabs
  → transcript/audio/evaluación
  → decisión humana
```

El análisis solo toma `LOADED`/`CV_ERROR`. Un candidato nunca se descarta automáticamente y el
descarte puede revertirse. `ProfilingRun` conserva cada intento y el watchdog evita que quede
indefinidamente en `CALLING`.

## Configuración de IA

Los modelos/prompts se resuelven en runtime desde configuración versionada. El workload actual usa
`gpt-5.6-luna`. Los prompts de extracción, match, mejora de JD y evaluación de profiling son
globales/Admin. Cada proceso solo configura WhatsApp y agente de llamada. El saludo de voz forma
parte de `VOICE_CALL_AGENT`; Question Set no guarda prompts.

## API

OpenAPI es la fuente exacta y se genera desde los routers. Los grupos principales son:

- `/api/v1/auth`, `/users`, `/system`;
- `/processes`, `/processes/home`, `/candidates`, `/match`;
- `/question-sets`, `/profiling`, `/webhooks`;
- `/ai-config`, `/whatsapp-templates`;
- `/metrics`, `/reports`, `/audit`, `/feedback`, `/search`, `/notifications`.

Consulta [`docs/api_contract.md`](docs/api_contract.md) y
[`docs/whatsapp_api_contract.md`](docs/whatsapp_api_contract.md).

## Variables

`.env.example` es el inventario operativo. Los grupos obligatorios dependen del flujo probado:

- core: `APP_SECRET_KEY`, `DATABASE_URL`, `DATABASE_URL_SYNC`, `REDIS_URL`;
- CV/IA: `R2_*`, `OPENAI_API_KEY`;
- voz: `PUBLIC_BASE_URL`, `TWILIO_*`, `ELEVENLABS_*`;
- consentimiento: `META_WHATSAPP_*`.
- SSO: `ORBITA_SSO_BASE_URL`, `ORBITA_SSO_CLIENT_ID`, `ORBITA_SSO_CLIENT_SECRET` y
  `ORBITA_SSO_REDIRECT_URI`, solo en el servicio API.

No declares una integración lista solo porque `/health` responde: valida conexión, firma y una
operación controlada del proveedor.

Tras registrar la aplicación y guardar el secreto, sincroniza el catálogo completo de roles:

```bash
python -m src.scripts.sync_orbita_role_catalog
```

El comando publica `admin`, `ta_leader` y `recruiter` sin imprimir el secreto. Las asignaciones de
usuarios se administran después desde Órbita.

## QA

```bash
.venv/bin/ruff check src tests
.venv/bin/python scripts/check_mypy_ratchet.py
.venv/bin/pytest -q tests
```

CI también audita dependencias y construye la imagen Docker. Pruebas reales de proveedores deben
ser explícitamente autorizadas y conciliar DB/costos después.

## Desarrollo

Las reglas para agentes están en [`AGENTS.md`](AGENTS.md). Las migraciones son append-only; no
reescribas una migración ya desplegada. Commits de este repo deben preceder el cambio de puntero en
el monorepo padre.
