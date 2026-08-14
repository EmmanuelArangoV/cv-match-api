---
name: maquina-de-estados
description: Úsala al cambiar estados o reglas del pipeline RIWI MATCH. Obliga a consultar las máquinas de dominio y el lifecycle de ProfilingRun en vez de escribir estados desde routers/workers.
---

# Estados y lifecycle

La fuente de verdad está en código:

- candidato: `src/domain/candidate/state_machine.py`;
- proceso: `src/domain/hiring_process/state_machine.py`;
- intento de profiling: `src/domain/profiling/state_machine.py`;
- alineación run/candidato/proceso: `src/application/profiling/lifecycle.py`;
- proyección de proceso: `src/application/hiring_process/progress.py`;
- reglas: `src/domain/hiring_process/rules.py`.

## Candidato

```text
LOADED → CV_PROCESSING → MATCH_PENDING → MATCH_PROCESSING → MATCHED
MATCHED → SELECTED_FOR_PROFILING → PROFILING_QUEUED → PROFILING_CALLING
        → PROFILING_COMPLETED
```

Ramas: `CV_ERROR` reintenta análisis; match puede volver a pending; selección puede revertirse;
fallos de profiling permiten retry; `DISCARDED → MATCHED` conserva reversibilidad. Nunca hay
descarte automático.

## Proceso

```text
DRAFT → CVS_UPLOADED → MATCH_PROCESSING → MATCH_DONE
      → PROFILING_CONFIGURED → PROFILING_ACTIVE → PROFILING_COMPLETED
      → CLOSED → ARCHIVED
```

El código permite reproceso/carga adicional y cierre desde estados concretos. No copies este
diagrama para validar una transición: llama la máquina.

## ProfilingRun

`ProfilingRun` distingue `PENDING`, `QUEUED`, `CALLING`, `ANSWERED`, `RETRY_PENDING` y estados
terminales (`COMPLETED`, cancelación/no-answer/voicemail/fallo según el enum vigente). Persiste el
run antes de publicar y usa `transition_profiling_async/sync`; esas funciones alinean
`ProcessCandidate` y el estado proyectado del proceso.

## Reglas

- No match sin JD ni CV procesado.
- Profiling exige selección manual, Question Set y consentimiento/política vigentes.
- Concurrencia y presupuesto se validan antes de proveedores.
- `CLOSED`/`ARCHIVED` bloquean acciones operativas.
- Una plantilla WhatsApp no aprobada/deshabilitada no habilita profiling.
- El consentimiento ambiguo no se convierte en aceptación.

Usa excepciones de dominio. No asignes `pc.status`, `run.status` o `process.status` directamente en
routers/workers. Excepciones técnicas muy acotadas deben mantener el mismo mapa, sincronizar la
proyección y tener prueba de regresión.

## QA

Prueba transición válida/inválida, idempotencia de webhook, duplicado activo, decisión humana
posterior, registro histórico incompleto y proceso cerrado/archivado. Ejecuta suite dirigida más
Ruff y ratchet mypy.
