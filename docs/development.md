---
sidebar_position: 3
---

# Desarrollo y calidad

## Requisitos locales

- Python 3.12.
- PostgreSQL con `pgvector` y Redis para las pruebas de integración.
- Credenciales de proveedor únicamente cuando se vaya a validar una integración real.

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

La API expone `/health`, `/ready`, `/docs` y `/openapi.json`. Para webhooks locales se requiere un
túnel HTTPS y `PUBLIC_BASE_URL` debe apuntar a ese túnel.

## Comprobaciones antes de entregar

```bash
.venv/bin/ruff check src tests
.venv/bin/python scripts/check_mypy_ratchet.py
.venv/bin/pytest -q tests
```

La suite automática se limita a `tests`; ejecutar `pytest` sin esa ruta puede recoger scripts
manuales de proveedores. Una prueba unitaria, mock o de build no valida credenciales ni una
integración externa real.
