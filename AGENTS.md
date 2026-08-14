# AGENTS.md — Backend

Reglas para trabajar en `cv-match-api`.

- Lee `CLAUDE.md` y `README.md` antes de modificar flujos.
- Respeta las capas `api → application → domain`; infraestructura implementa adaptadores.
- Usa excepciones de dominio y el lifecycle central. No cambies estados directamente desde un
  router, worker o webhook.
- Persiste `ProfilingRun` antes de publicar la tarea y propaga siempre `run_id`.
- CV extraction y match son operaciones manuales separadas.
- El Question Set no contiene system prompt ni saludo. Los prompts globales y por proceso se
  resuelven mediante `AIConfigService`/`ProcessAIPrompt`.
- Toda operación pagada debe persistir `CostLog` idempotente con procedencia y desglose.
- Un router nuevo debe montarse en `src/api/main.py` y tener prueba de contrato/roles.
- Mensajes de dominio y API en español; identificadores de código en inglés.
- Nunca agregues credenciales ni datos reales de candidatos a fixtures.

QA antes de entregar:

```bash
.venv/bin/ruff check src tests
.venv/bin/python scripts/check_mypy_ratchet.py
.venv/bin/pytest -q tests
```

Para Git, sigue `../.agents/skills/monorepo-git/SKILL.md`: este submódulo se commitea antes de
actualizar su puntero en el repositorio padre.
