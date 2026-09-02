---
sidebar_position: 4
---

# Operación del pipeline

La guía de despliegue, dimensionamiento de Celery y diagnóstico por servicio está en
[`deployment.md`](deployment.md). Esta página se centra en la recuperación de datos y estados.

`ProcessCandidate` representa el estado de negocio; `ProfilingRun`, cada intento de profiling.
API, workers y callbacks deben utilizar el lifecycle central para que el kanban por proceso y el
tablero global proyecten la misma información.

## Reconciliación

El reconciliador corrige contradicciones históricas conocidas sin contactar proveedores ni publicar
tareas nuevas.

```bash
.venv/bin/python scripts/reconcile_statuses.py
.venv/bin/python scripts/reconcile_statuses.py --apply
```

En un entorno productivo, primero respalda PostgreSQL, revisa el informe en seco y aplica solo las
reparaciones deterministas aprobadas. Después de migrar o reiniciar, ejecuta de nuevo el informe en
seco.

## Servicios de ejecución

La misma imagen Docker se usa en tres procesos independientes:

| Servicio | Responsabilidad |
| --- | --- |
| API | HTTP, health/readiness y migraciones previas al despliegue. |
| Worker | Consumo de tareas de CV, match, WhatsApp y profiling. |
| Beat | Publicación programada de watchdogs; debe tener una sola réplica. |

No se debe declarar un proveedor listo solo porque `/health` responda. Verifica conectividad,
firmas de webhook y una operación controlada antes de etiquetar la integración como real.
