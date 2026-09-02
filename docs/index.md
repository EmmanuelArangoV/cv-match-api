---
sidebar_position: 1
slug: /
---

# Backend de RIWI MATCH

Esta documentación describe el repositorio `cv-match-api`: API FastAPI, procesamiento asíncrono
con Celery y las integraciones que soportan el flujo de selección.

## Fuente de verdad

- El contrato HTTP exacto se genera en `/openapi.json` y se explora en `/docs` cuando la API está
  levantada.
- Los routers montados en `src/api/main.py` y sus pruebas son la referencia final de los endpoints.
- Las transiciones de candidatos y profiling se centralizan en `src/application/`; ninguna pantalla,
  router o tarea debe inventar una interpretación paralela del estado.

## Mapa rápido

| Área | Punto de entrada |
| --- | --- |
| HTTP y autenticación | `src/api/` |
| Casos de uso | `src/application/` |
| Reglas y máquinas de estado | `src/domain/` |
| Persistencia, IA, proveedores y workers | `src/infrastructure/` |
| Migraciones | `alembic/versions/` |
| Pruebas | `tests/` |

El análisis de CV y el match son operaciones manuales separadas. El profiling conserva el estado
de negocio en `ProcessCandidate` y cada intento técnico en `ProfilingRun`.
