# CLAUDE.md — Backend (cv-match-api)

Backend FastAPI (Python 3.12+) de RIWI MATCH con workers Celery. Este repo es un **submódulo** del
monorepo `RiwiMatch`; la guía completa de arquitectura vive en el `CLAUDE.md` de la raíz del repo
padre.

## Plan de cierre del MVP

**El plan para llevar F1–F3 al 100% está en `PLAN_MVP_100.md`, en la raíz del monorepo (repo padre
`RiwiMatch`, un nivel arriba de este submódulo).** Consúltalo antes de priorizar trabajo nuevo:
lista cada brecha con los archivos de backend y frontend a tocar. El estado actual resumido está en
`STATUS_RESUMEN.md` (este repo).

## Esencial

- Arquitectura limpia con 4 capas bajo `src/` (`api/`, `application/`, `domain/`,
  `infrastructure/`); la regla de dependencia va hacia adentro.
- Toda transición de estado pasa por las máquinas de estado de `src/domain/`; errores se señalan
  con las excepciones de dominio (`src/domain/shared/exceptions.py`), nunca con `HTTPException`.
- El trabajo pesado (parseo de CV, match, WhatsApp, llamadas de voz) corre en tareas Celery.
- Comentarios y mensajes de error **en español**.
- **Todo router nuevo en `src/api/v1/` debe montarse explícitamente en `src/api/main.py`** con
  `app.include_router(...)` — crear el archivo con `APIRouter` no lo expone por HTTP. `feedback.py`,
  `audit.py` y `reports.py` existieron como código muerto por esta razón hasta que se integró el
  frontend; verifica `main.py` si un router "existe" pero responde 404.
- `GET /api/v1/users/me` devuelve el perfil del usuario autenticado (cualquier rol) — úsalo en vez
  de decodificar el JWT para obtener nombre/email, que no van en el payload del token.

```bash
pip install -e ".[dev]"    # instalar
python main.py             # API en http://localhost:8000
celery -A src.infrastructure.workers.celery_app worker --loglevel=info
celery -A src.infrastructure.workers.celery_app beat --loglevel=info
pytest                     # tests
ruff check src/ && mypy src/
```

## Skills

En `.claude/skills/` de este repo: `maquina-de-estados` (referencia autoritativa de las dos
máquinas de estado y reglas RB-001..RB-010), `agregar-transicion-estado` y `crear-tarea-celery`.
Úsalas antes de tocar estados, reglas de negocio o tareas Celery.
