---
sidebar_position: 4
---

# Lifecycle, estados y proyecciones

El pipeline tiene dos niveles deliberadamente distintos:

- `ProcessCandidate.status` expresa la etapa de negocio que consume recruiting.
- `ProfilingRun.status` expresa el estado técnico de un intento de llamada.

`src/application/profiling/lifecycle.py` es la única pieza que alinea ambos. Después de cada
transición también sincroniza el agregado del proceso mediante
`src/application/hiring_process/progress.py`.

## Pipeline de candidato

```text
LOADED -> CV_PROCESSING -> MATCH_PENDING -> MATCH_PROCESSING -> MATCHED
                  \-> CV_ERROR --(reintento)--------------------/

MATCHED -> SELECTED_FOR_PROFILING -> PROFILING_QUEUED -> PROFILING_CALLING
   |                 |                       |                     |
   |                 +-> MATCHED              +-> PROFILING_FAILED  +-> PROFILING_COMPLETED
   +-> DISCARDED --(restaurar)-> MATCHED                         |
                                             (reintento)-----------+
```

La gráfica resume transiciones frecuentes; la validación exacta está en
`src/domain/candidate/state_machine.py`. En especial:

- El análisis no desencadena el match: `LOADED`/`CV_ERROR` se analizan por acción humana y el
  match se solicita después, por separado.
- Solo `MATCHED` puede seleccionarse para profiling.
- El descarte nunca es automático y puede revertirse a `MATCHED`.
- `PROFILING_COMPLETED` es terminal en la máquina de estados; cualquier excepción humana debe
  pasar por el mecanismo autorizado de override, no por una asignación directa.

## Estados técnicos de una corrida

```text
PENDING -> QUEUED -> CALLING -> ANSWERED -> COMPLETED
   |          |         |          \-> FAILED
   |          |         +-> RETRY_PENDING -> QUEUED
   |          +-> CANCELLED / FAILED
   +-> CANCELLED / FAILED

CALLING -> NO_ANSWER | VOICEMAIL_DETECTED | FAILED
```

Los estados activos son `PENDING`, `QUEUED`, `CALLING`, `ANSWERED` y `RETRY_PENDING`. Los demás
son terminales. La máquina exacta vive en `src/domain/profiling/state_machine.py`.

## Alineación entre corrida y candidato

| Transición de `ProfilingRun` | Reflejo habitual en `ProcessCandidate` |
| --- | --- |
| `QUEUED` | `PROFILING_QUEUED` |
| `CALLING` o `ANSWERED` | `PROFILING_CALLING` |
| `COMPLETED` | `PROFILING_COMPLETED` |
| `CANCELLED` desde cola | `SELECTED_FOR_PROFILING` |
| Terminal fallida | `PROFILING_FAILED` |
| `RETRY_PENDING` | Pasa por `PROFILING_FAILED` y vuelve a `PROFILING_QUEUED` cuando aplica. |

La rutina protege registros ya descartados o completados de una mutación accidental. Por ello un
router, tarea Celery o webhook **no** debe cambiar los campos de estado por su cuenta.

## Proyección compartida para la UI

`progress.py` calcula etapa, contadores, llamadas activas y una
`CandidatePipelineProjection`. Sus columnas de tablero son `CV_MATCH`, `QUEUED`, `CALLING`,
`COMPLETED` y `FAILED`.

Cuando encuentra datos históricos contradictorios, conserva la evidencia y marca la consistencia
en vez de ocultarla. Tanto el kanban de un proceso como el board global deben consumir esta misma
proyección; no se recalculan estados o contadores por pantalla.
