<div align="center">
  <img src="https://raw.githubusercontent.com/maryhug/riwi-match/main/src/assets/CurvaMatch.svg" alt="RIWI MATCH" width="360" />
  <h1>Backend & Workers</h1>
  <p>API, pipeline asíncrono y gobierno operativo de RIWI MATCH.</p>

  <img src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white" alt="Python 3.12" />
  <img src="https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Celery-Workers-37814A?logo=celery&logoColor=white" alt="Celery" />
  <img src="https://img.shields.io/badge/PostgreSQL-pgvector-4169E1?logo=postgresql&logoColor=white" alt="PostgreSQL con pgvector" />
</div>

## Qué contiene

Este repositorio entrega la API FastAPI y la misma imagen Python para tres procesos: API HTTP,
worker Celery y Celery Beat. Gestiona autenticación, procesos, CVs, match manual, profiling por
voz, costos, auditoría, métricas y reportes.

```text
API -> PostgreSQL + Redis -> Worker
                             ├─ R2 / OpenAI
                             └─ Meta / Twilio / ElevenLabs
Beat -> watchdogs y vencimientos
```

El análisis de CV y el match son acciones manuales separadas. `ProcessCandidate` conserva el estado
de negocio; `ProfilingRun`, cada intento técnico de llamada.

## Inicio local

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
- OpenAPI: <http://localhost:8000/openapi.json>

PostgreSQL debe tener `pgvector` y Redis debe estar disponible antes de iniciar. Para webhooks
locales, expón la API por HTTPS y configura `PUBLIC_BASE_URL`.

## Documentación

El portal Docusaurus vive en [`documentation/`](documentation/README.md) y publica el contenido de
[`docs/`](docs/).

| Tema | Referencia |
| --- | --- |
| Arquitectura y módulos | [Arquitectura](docs/architecture.md) · [Mapa de código](docs/code-map.md) |
| Estados y trabajo asíncrono | [Lifecycle](docs/lifecycle-and-projections.md) · [Celery](docs/async-work.md) |
| Despliegue y datos | [Despliegue](docs/deployment.md) |
| Costos | [Seguimiento y conciliación](docs/costs.md) |
| HTTP | [Contrato API](docs/api_contract.md) · [WhatsApp](docs/whatsapp_api_contract.md) |

Para navegarlo localmente:

```bash
cd documentation
npm install
npm run start
```

## Calidad

```bash
.venv/bin/ruff check src tests
.venv/bin/python scripts/check_mypy_ratchet.py
.venv/bin/pytest -q tests
```

Las pruebas reales de proveedores requieren autorización, credenciales válidas y conciliación de
costos posterior. No incluyas secretos ni datos reales de candidatos en fixtures, logs o commits.
