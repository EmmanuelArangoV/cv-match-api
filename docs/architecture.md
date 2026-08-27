---
sidebar_position: 2
---

# Arquitectura del código

El backend mantiene una dirección de dependencias explícita:

```text
api -> application -> domain
                  -> infrastructure (adaptadores)
```

- `src/api/` contiene routers FastAPI, esquemas, dependencias de roles, webhooks y traducción de
  excepciones a HTTP.
- `src/application/` orquesta casos de uso. Aquí viven los servicios de progreso de proceso,
  lifecycle de profiling, configuración de IA y lógica de candidatos.
- `src/domain/` mantiene value objects, enums, máquinas de estado y reglas de negocio sin acoplarse
  a FastAPI, SQLAlchemy o proveedores.
- `src/infrastructure/` implementa SQLAlchemy, repositorios, Redis/Celery, OpenAI, R2, Meta,
  Twilio y ElevenLabs.

## Pipeline principal

```text
Proceso + JD -> carga de CV -> análisis manual -> match manual
             -> selección humana -> consentimiento WhatsApp
             -> llamada Twilio/ElevenLabs -> transcript/evaluación -> decisión humana
```

Las tareas pesadas se publican a Celery. Antes de publicar una tarea de profiling se persiste un
`ProfilingRun` y se propaga su `run_id`. La proyección compartida de proceso se obtiene desde
`src/application/hiring_process/progress.py`.

## Reglas que no se deben romper

- Un candidato no se descarta automáticamente; el descarte es reversible.
- Un router no cambia estados directamente: usa lifecycle o casos de uso.
- Los prompts globales pertenecen a Admin; por proceso solo existen `WHATSAPP_MESSAGE` y
  `VOICE_CALL_AGENT`.
- Una operación pagada deja un `CostLog` idempotente con procedencia y desglose.
