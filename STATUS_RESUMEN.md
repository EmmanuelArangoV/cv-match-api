# Estado actual del Backend

> Actualizado: 2026-08-09. Este es un resumen operativo; OpenAPI y el código son la fuente exacta.

## Implementado

- JWT con refresh/logout, roles `ADMIN`, `RECRUITER`, `TA_LEADER` y SSO central con Órbita
  mediante código de un solo uso, validación RS256 y aprovisionamiento local seguro.
- Procesos, JD versionadas, cierre/archivo y filtros server-side.
- Home paginado con resumen/opciones, sin cargar el detalle de todos los procesos.
- Carga, deduplicación, extracción/normalización de CV y nota prioritaria del recruiter.
- Match manual explicable, ranking y override humano.
- Descarte/restauración reversible y disponibilidad del candidato.
- Question Sets versionados sin prompts ni saludo inicial.
- Configuración de modelos/prompts globales y prompts de comunicación por proceso.
- Plantillas WhatsApp administrables, sincronización de estado Meta y selección por proceso.
- Consentimiento, llamadas Twilio + ElevenLabs, contexto/TwiML precargado y AMD opcional/asíncrono.
- Profiling con transcript, audio, respuestas, evaluación y lifecycle central por `ProfilingRun`.
- Watchdog/reconciliación de intentos atascados y protección contra duplicados activos.
- `CostLog` auditable a lo largo del pipeline y agregados por proceso/candidato/proveedor.
- Auditoría, feedback, reportes CSV, búsqueda, notificaciones, métricas y administración de usuarios.

## Decisiones vigentes

- Modelo de workloads: `gpt-5.6-luna`.
- La IA recomienda; ninguna exclusión de candidato es automática.
- Extracción y match requieren acciones separadas.
- Prompts globales: extracción, match, mejora de JD y evaluación de profiling.
- Prompts por proceso: WhatsApp y agente de llamada. El saludo pertenece al agente; Question Set
  solo define preguntas.
- Home usa paginación/filtros en backend. Cerrados/archivados se excluyen por defecto pero son
  recuperables mediante filtro.
- AMD está controlado por entorno; habilitarlo cambia clasificación/latencia y requiere QA real.

## Dependencias operativas

Una demo completa necesita PostgreSQL con pgvector, Redis, R2, OpenAI, Meta, Twilio, ElevenLabs,
API, worker, beat y endpoints públicos HTTPS. Sin una credencial concreta solo se considera
validado el comportamiento mock/local correspondiente.

## QA vigente

CI ejecuta auditoría de dependencias, Ruff, ratchet de mypy, pytest y build Docker. La suite
automatizada local se ejecuta con:

```bash
.venv/bin/pytest -q tests
```

No usar este documento como conteo fijo de tests: el número cambia; consulta la ejecución CI más
reciente.

## Riesgos/pendientes para producción

- Revisar rotación de secretos, retención de CV/audio/transcript y recuperación de DB.
- Validar plantillas Meta y firmas webhooks en el ambiente de destino.
- Confirmar una sola réplica de Celery Beat y observabilidad/alertas del watchdog.
- Conciliar tarifas de proveedores cuando cambien; los costos históricos conservan su fuente.
- Ejecutar E2E real controlada después de cambios de proveedor, modelo, prompt, AMD o telefonía.
