---
sidebar_position: 3
---

# Mapa del código backend

Esta página permite localizar una responsabilidad antes de modificarla. La dirección esperada es
`api -> application -> domain`; infraestructura aporta implementaciones concretas y no debe
convertirse en un segundo lugar para reglas de negocio.

## Capas y puntos de entrada

| Capa | Directorio | Responsabilidad | No debe hacer |
| --- | --- | --- | --- |
| HTTP | `src/api/` | Routers, schemas, JWT/roles, webhooks y traducción de errores de dominio a HTTP. | Decidir transiciones de estado o llamar proveedores desde el router. |
| Aplicación | `src/application/` | Casos de uso, orquestación transaccional, resolución de prompts y proyección de progreso. | Acoplar reglas a FastAPI. |
| Dominio | `src/domain/` | Excepciones, value objects, reglas y máquinas de estado. | Importar SQLAlchemy, Celery o SDKs externos. |
| Infraestructura | `src/infrastructure/` | Modelos SQLAlchemy, repositorios, cache, storage, IA, mensajería, voz y tareas Celery. | Crear una vía alternativa para modificar el lifecycle. |

`src/api/main.py` es el ensamblador HTTP: monta todos los routers bajo `/api/v1`, salvo
`/health` y `/ready`, y convierte `DomainException` en errores HTTP coherentes (`401`, `403`,
`404`, `409`, `422` o `400`, según el subtipo).

## Módulos de aplicación

| Módulo | Responsabilidad principal | Punto de cuidado |
| --- | --- | --- |
| `auth/` y `users_use_cases.py` | Sesión, usuarios, roles y autorización. | El frontend es consumidor; la autorización final se evalúa aquí/backend. |
| `candidate/` y `cv/` | Carga, contexto adicional, análisis y datos normalizados del CV. | Analizar es una acción explícita; solo se procesa el conjunto permitido. |
| `hiring_process/` | Proceso, JD y proyección compartida de progreso. | `progress.py` es la fuente de los contadores, la etapa y el tablero. |
| `profiling/` | Crear intentos, consentimientos, llamadas, reintentos y callbacks. | `lifecycle.py` debe acompañar cada cambio técnico con su reflejo de negocio. |
| `ai/` | Resolución de modelo y prompt efectivo. | Los prompts globales no se duplican en la configuración de un proceso. |
| `notifications/` | Alertas de aplicación, incluido control de presupuesto. | Las notificaciones no sustituyen el registro auditable de costos. |

## Persistencia y límites de modelo

`ProcessCandidate` no es un candidato global: es la participación de una persona dentro de un
proceso y contiene el estado de negocio del pipeline. `ProfilingRun` representa **cada intento
técnico** de profiling. Esta separación permite reintentos y conserva el histórico sin inventar un
estado nuevo en la interfaz.

Los modelos SQLAlchemy se encuentran en `src/infrastructure/db/models/`; las migraciones se
agregan, en orden, a `alembic/versions/`. Nunca se reescribe una migración ya desplegada.

## Dónde investigar un cambio

1. Parte del router y del esquema de OpenAPI para entender autorización y payload.
2. Sigue el caso de uso en `src/application/`.
3. Revisa la regla o máquina de estado en `src/domain/`.
4. Solo entonces cambia el repositorio, worker o adaptador de `src/infrastructure/`.
5. Añade pruebas de contrato/rol y pruebas de la regla afectada.

Este recorrido evita que un cambio visualmente pequeño deje desincronizado el proceso, el tablero
global o un callback asíncrono.
