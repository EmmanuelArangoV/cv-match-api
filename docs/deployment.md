---
sidebar_position: 6
---

# Despliegue de la plataforma

Esta guía describe la arquitectura necesaria para desplegar RIWI MATCH en Railway u otro proveedor
de contenedores. El código de backend se construye una vez y se ejecuta con tres roles distintos:
API, worker y scheduler (Beat). Separarlos permite dimensionar y diagnosticar cada responsabilidad
sin convertir una petición HTTP en trabajo costoso.

## Arquitectura obligatoria

```text
Browser
  -> Frontend/BFF (público) --red privada--> API FastAPI (pública para webhooks)
                                              |        |
                                              |        +-> PostgreSQL + pgvector
                                              +-> Redis <-> Worker Celery
                                                           ^
                                                  Beat --+

Worker -> R2 / OpenAI / Meta WhatsApp / Twilio / ElevenLabs
Proveedores de webhook -----------------------------> API pública
```

| Servicio | Necesidad | Exposición | Estado que controla |
| --- | --- | --- | --- |
| Frontend/BFF | UI, SSR, sesión y proxy de descargas. | Público. | Renderizado y llamadas server-side a la API. |
| API | REST, JWT, webhooks, casos de uso y healthchecks. | Público para webhooks; el BFF la consume por red privada. | DB, autorización y publicación de tareas. |
| Worker | CV, match, WhatsApp, llamadas, evaluación y costos. | Privado. | Consumo de la cola y ejecución costosa. |
| Beat | Watchdogs de llamadas y vencimiento de consentimientos. | Privado. | Publicación programada; no ejecuta el trabajo pesado. |
| PostgreSQL + `pgvector` | Fuente de verdad relacional y vectores. | Privado. | Procesos, candidatos, corridas, auditoría y costos. |
| Redis | Broker y backend de resultados Celery. | Privado. | Entrega de tareas y resultados efímeros. |

R2 y los proveedores de IA/voz/mensajería son dependencias externas del worker. Twilio, Meta y
ElevenLabs además llaman de vuelta a la **API pública** mediante webhooks firmados.

## Almacenes de datos: qué guarda cada uno y por qué importa

La plataforma no tiene varias bases de datos equivalentes. Cada almacén tiene una responsabilidad
propia y una política de disponibilidad, persistencia y recuperación distinta.

| Almacén | Datos que contiene | Si falta o se reinicia | Política de despliegue |
| --- | --- | --- | --- |
| PostgreSQL + `pgvector` | Fuente de verdad: usuarios, procesos, candidatos, estados, `ProfilingRun`, auditoría, `CostLog`, JSONB y embeddings. | La API no está lista y no debe aceptar tráfico (`/ready` falla). Una pérdida requiere restauración. | Persistente, backups/PITR, migraciones Alembic y extensión `vector`. |
| Redis | Broker y backend de resultados Celery; refresh tokens; caché de modelos/settings; contexto/TwiML de llamadas con TTL. | Las tareas no se consumen y `/ready` falla. Las cachés pueden regenerarse, pero tareas en espera/resultados y contexto temporal deben tratarse como afectados. | Privado, con persistencia para reducir pérdida ante reinicios y memoria monitorizada. No almacena la verdad de negocio. |
| Cloudflare R2 u objeto S3 compatible | CVs originales, CVs normalizados y archivos de Job Description. PostgreSQL conserva las claves, no el binario. | Carga, análisis y descargas de archivos fallan; un registro puede apuntar a un objeto inaccesible. | Bucket privado, credenciales por variable, retención/versionado acorde a privacidad y prueba de lectura/escritura. |

### Redis es un componente crítico, no solo una caché

`REDIS_URL` conecta simultáneamente API, worker y Beat. Celery lo usa como broker y backend de
resultados; por eso un Redis inaccesible impide publicar y consumir análisis de CV, match,
consentimientos y profiling. Beat también depende de él para programar sus watchdogs.

Además, el backend guarda en Redis:

- refresh tokens de sesión;
- modelos activos y settings globales durante 15 minutos;
- contexto de llamada, `CallSid` activo y TwiML preparado durante 15 minutos;
- permisos de overrides de ElevenLabs con TTL.

Una limpieza o reinicio de Redis invalida esas entradas temporales. Los modelos/settings se vuelven
a leer desde PostgreSQL, pero una sesión puede requerir reautenticación y una llamada que esté en
el periodo de contexto puede necesitar el camino de recuperación del lifecycle. Nunca uses Redis
como sustituto de `ProcessCandidate`, `ProfilingRun`, costos ni estados: esos viven en PostgreSQL.

Para operar Redis con seguridad:

- usa red privada y autenticación/TLS si el proveedor lo ofrece;
- reserva memoria y define política de evicción que no descarte silenciosamente la cola Celery;
- supervisa memoria, conexiones, edad/profundidad de cola y errores de conexión;
- mantén persistencia o servicio administrado para acotar pérdida en un reinicio, pero ensaya el
  comportamiento de reintentos/reconciliación: la durabilidad de negocio sigue estando en PostgreSQL.

### R2 es almacenamiento de objetos, no una base de datos

Los flujos de carga escriben el binario en R2 y guardan su clave en PostgreSQL. El worker descarga
el CV desde esa clave, procesa el contenido y vuelve a subir el PDF normalizado. Las descargas
autorizadas se resuelven mediante URLs firmadas de una hora; no se debe abrir el bucket ni exponer
sus credenciales al navegador.

Incluye R2 en la revisión de despliegue aunque no participe en `/ready`: el endpoint de salud de
integraciones puede comprobar el bucket y una prueba real controlada debe validar `put`, `get` y
URL firmada. Configura retención y borrado conforme a la política de datos de candidatos, y
reconcilia objetos huérfanos antes de eliminarlos.

## Imagen y comandos

`Backend/Dockerfile` crea una sola imagen Python 3.12. La plataforma debe reutilizarla para los
tres roles y sobrescribir solo el comando de arranque:

| Rol | Comando |
| --- | --- |
| API | `uvicorn src.api.main:app --host 0.0.0.0 --port ${PORT:-8000}` |
| Worker | `celery -A src.infrastructure.workers.celery_app worker --loglevel=info --concurrency=1 --prefetch-multiplier=1 --max-tasks-per-child=1` |
| Beat | `celery -A src.infrastructure.workers.celery_app beat --loglevel=info --schedule=/tmp/celerybeat-schedule` |

La API tiene healthcheck de imagen en `/health`; para la plataforma configura `/ready`, que
comprueba PostgreSQL y Redis. Solo la API ejecuta las migraciones como pre-deploy. Worker y Beat
no ejecutan `alembic` ni `uvicorn`.

## Configuración Celery: costo, latencia y fiabilidad

El perfil conservador para operaciones con proveedores pagados es:

```text
--concurrency=1 --prefetch-multiplier=1 --max-tasks-per-child=1
```

| Opción | Efecto | Razón para este proyecto | Coste de la decisión |
| --- | --- | --- | --- |
| `--concurrency=1` | Un proceso ejecuta una tarea a la vez. | Evita picos paralelos de PDF/visión/LLM y llamadas de voz. | Un lote grande espera más. |
| `--prefetch-multiplier=1` | El worker reserva solo la tarea que puede ejecutar. | Evita que una réplica acapare trabajo costoso o deje tareas retenidas al reiniciar. | Menor throughput máximo que un prefetch alto. |
| `--max-tasks-per-child=1` | Recicla el hijo tras cada tarea. | Libera memoria de PDFs, imágenes y SDKs después de cada operación. | Mayor overhead de arranque por tarea. |

No confundir esa concurrencia técnica con `MAX_CONCURRENT_CALLS`: esta última es una regla de
negocio que limita llamadas de profiling activas. Ambas protegen costos, pero en capas distintas.

Beat debe tener exactamente **una réplica**. Programa `check_stale_profiling_calls` y
`resolve_whatsapp_timeouts`; dos réplicas podrían publicar revisiones duplicadas. El schedule en
`/tmp` es efímero: el comportamiento sigue siendo seguro porque las transiciones, locks y costos
son idempotentes, pero el scheduler se reinicia con el contenedor.

### Cuándo escalar

Mantén una réplica de worker mientras la cola y la latencia sean aceptables. Antes de subir su
concurrencia o añadir réplicas, comprueba límites de OpenAI/Meta/Twilio/ElevenLabs,
`MAX_CONCURRENT_CALLS`, tamaño de CV y presupuesto. Si las llamadas de voz necesitan una latencia
distinta al análisis de CV, crea colas y workers dedicados con routing explícito; no subas la
concurrencia global sin separar esas cargas.

## Dimensionamiento inicial por perfil de carga

Estos valores son **reservas iniciales**, no consumo medido ni un compromiso de capacidad. Se
basan en el código: el worker convierte PDFs/DOCX/imágenes, construye contenido para visión,
ejecuta SDKs de IA y persiste resultados; API, Beat y BFF tienen una carga comparativamente más
ligera. Deben ajustarse con métricas reales antes de aumentar el presupuesto.

| Servicio | Arranque funcional | Perfil recomendado para operación ágil | Criterio |
| --- | --- | --- | --- |
| Frontend/BFF | 0.5 vCPU / 768 MiB | 1 vCPU / 1 GiB | SSR y proxy BFF; crece por solicitudes concurrentes. |
| API | 1 vCPU / 1.5 GiB | 1.5 vCPU / 2 GiB | HTTP async, JWT, webhooks y acceso a DB/Redis. |
| Worker Celery | 1 vCPU / 2.5 GiB | 2 vCPU / 3 GiB | Conversión de documentos y clientes de proveedor; mantiene `concurrency=1`. |
| Beat | 0.25 vCPU / 512 MiB | 0.25 vCPU / 512 MiB | Solo publica tareas periódicas; una sola réplica. |
| PostgreSQL + pgvector | 1 vCPU / 2 GiB | 1.5 vCPU / 3 GiB | Fuente de verdad, índices y proyecciones. |
| Redis | 0.25 vCPU / 512 MiB | 0.25 vCPU / 512 MiB | Broker/resultados; vigilar memoria de cola. |

El perfil recomendado reserva aproximadamente **6.5 vCPU y 10 GiB** para los seis servicios. Si
PostgreSQL o Redis son administrados externamente, el presupuesto de contenedores de la aplicación
queda en **4.75 vCPU y 6.5 GiB**. Los proveedores que solo permiten escalones enteros deben redondear
hacia arriba cada servicio, no concentrar todo el margen en el worker.

### Cómo calcular la capacidad, sin adivinar

Mide durante una semana de tráfico representativo y usa el percentil 95, no el promedio:

```text
capacidad_por_hora = (concurrency × 3600) / duracion_P95_segundos
ocupacion_objetivo <= 70%
edad_estimada_de_cola = tareas_en_espera / capacidad_por_segundo
```

Por ejemplo, calcula esos valores por separado para `parse_cv`, `run_match` y profiling. El worker
es estable si la tasa de llegada queda por debajo del 70% de su capacidad P95 y la memoria P95 se
mantiene por debajo del 70% de su límite. El margen restante cubre PDFs inusuales, reintentos y
reinicios.

Escala en este orden:

1. Si la API o BFF supera el 70% de CPU/memoria P95, añade una réplica de ese servicio.
2. Si la edad de cola crece pero el worker tiene memoria disponible, añade **otra réplica con
   `concurrency=1`** antes de aumentar concurrencia dentro del mismo proceso.
3. Si CV/match bloquean llamadas, separa rutas y workers por cola; mide de nuevo cada tipo.
4. Si PostgreSQL presenta latencia o pool saturado, escala la base o sus índices antes de multiplicar
   workers.

No modifiques varios ejes a la vez. Registra la duración P95, edad de cola, CPU, memoria, errores
de proveedor y `CostLog` antes y después de cada cambio; así se puede atribuir una mejora o una
regresión.

## Variables por rol

Los secretos se almacenan como variables selladas del proveedor, nunca en Git ni en logs. Estas son
las dependencias mínimas por responsabilidad; añade los valores reales desde `.env.example`.

| Variable o grupo | API | Worker | Beat | Uso |
| --- | :---: | :---: | :---: | --- |
| `APP_ENV`, `APP_SECRET_KEY` | Sí | Sí | Sí | Configuración consistente de la aplicación. |
| `DATABASE_URL`, `DATABASE_URL_SYNC` | Sí | Sí | Sí | API async; Alembic y tareas sync. |
| `REDIS_URL` | Sí | Sí | Sí | Broker/backend y scheduler Celery. |
| `R2_*`, `OPENAI_API_KEY` | Según endpoint | Sí | No | Carga, análisis, match y evaluación. |
| `META_WHATSAPP_*` | Webhook | Sí | No | Consentimiento y callback. |
| `TWILIO_*`, `ELEVENLABS_*` | Webhook | Sí | No | Llamadas, transcript y callback. |
| `PUBLIC_BASE_URL` | Sí | Sí | No | URL HTTPS de API para formar y verificar webhooks. |
| Límites: `CV_BATCH_LIMIT`, `MAX_CONCURRENT_CALLS`, timeouts | Sí | Sí | No | Reglas y control de carga. |

El worker ejecuta todos los tipos de tarea registrados hoy, por lo que necesita credenciales de
todas las integraciones que se activen. Beat no llama proveedores, pero requiere configuración de
DB/Redis porque carga el mismo módulo de settings y publica tareas.

## PostgreSQL desde una base vacía

El repositorio **sí contiene el esquema**: `alembic/versions/` parte de una migración inicial y
`alembic upgrade head` crea las tablas, índices y la tabla `alembic_version` en una base vacía. No
usa `Base.metadata.create_all()` en el arranque, así que no hay un segundo mecanismo que pueda
dejar el esquema a medias.

Sin embargo, Alembic presupone dos elementos que el proveedor debe entregar antes de la primera
migración:

1. Una base PostgreSQL vacía, un usuario con permiso DDL y conectividad privada desde API, worker
   y Beat.
2. La extensión `pgvector` instalada en esa base. Las migraciones crean columnas `VECTOR(1536)`
   para embeddings de CV y profiling, pero no ejecutan `CREATE EXTENSION vector`.

En un PostgreSQL autogestionado o cuyo proveedor permita extensiones, el administrador debe
preparar la base una sola vez:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

En un servicio administrado, elige un plan/imagen que ya incluya `pgvector` o habilítala por el
mecanismo del proveedor. Si la cuenta de aplicación no puede instalar extensiones, esa operación
debe realizarla un administrador antes del despliegue; no se debe conceder ese privilegio a la API
para el runtime normal.

### URLs y orden de inicialización

| Variable | Consumidor | Formato esperado |
| --- | --- | --- |
| `DATABASE_URL` | API FastAPI/SQLAlchemy async | `postgresql+asyncpg://...` |
| `DATABASE_URL_SYNC` | Alembic y tareas Celery | `postgresql://...` |

Ejecuta las migraciones desde el directorio `Backend/`, una vez por versión desplegada y antes de
levantar réplicas de API/worker:

```bash
.venv/bin/alembic current
.venv/bin/alembic upgrade head
.venv/bin/alembic current
```

En CI/CD, el pre-deploy de API es el único lugar autorizado para `upgrade head`; worker y Beat
esperan a que termine. Si el proveedor permite dos despliegues simultáneos, protege esa etapa con
un único job de release para evitar que dos procesos de Alembic compitan.

### Verificación de una inicialización limpia

Con una conexión administrativa o de despliegue, comprueba tanto la revisión como la extensión:

```sql
SELECT version_num FROM alembic_version;
SELECT extname FROM pg_extension WHERE extname = 'vector';
```

La suite de integración `tests/integration/test_runtime_dependencies.py` comprueba precisamente
esa combinación junto con `PING` de Redis cuando se ejecuta con `RUN_INTEGRATION_TESTS=1`. El
endpoint `/ready` valida conectividad de PostgreSQL y Redis, pero no sustituye esa comprobación de
`pgvector` tras crear una base nueva.

### Persistencia, backups y datos de prueba

- PostgreSQL requiere volumen persistente o un servicio administrado con backups/PITR. No mezcles
  su almacenamiento con el contenedor de API.
- Haz backup verificable antes de aplicar una migración irreversible y ensaya restauración en un
  entorno aislado.
- `scripts/seed_qa_data.py` inserta datos sintéticos y exige `QA_SEED_ADMIN_PASSWORD`; es solo
  para QA/staging. No es parte de la inicialización de producción.
- Las migraciones son append-only. Añade una nueva revisión para cada cambio de esquema; no
  reescribas una ya aplicada.

## Receta portable

1. Provisiona PostgreSQL persistente, habilita `pgvector` y verifica una restauración de backup;
   provisiona Redis persistente en la misma región que API/worker.
2. Configura las dos URLs de PostgreSQL y ejecuta `alembic upgrade head` una sola vez contra la
   base vacía.
3. Crea la API desde `Backend/Dockerfile`; fija `APP_ENV=production` y configura `/ready`.
4. Crea worker y Beat desde la misma imagen con los comandos anteriores; una réplica de Beat.
5. Añade variables por rol, dominios públicos para frontend y API, y red privada entre servicios.
6. Configura `PUBLIC_BASE_URL` con el dominio HTTPS de API y registra webhooks Meta/Twilio/ElevenLabs.
7. Despliega frontend con su `API_BASE_URL` privada y valida extremo a extremo una operación por
   proveedor antes de declarar esa integración disponible.

En Railway, usa referencias privadas entre servicios (`${{api.RAILWAY_PRIVATE_DOMAIN}}` y el
puerto de la API) para el BFF. El navegador y los proveedores externos deben usar dominios públicos
HTTPS; nunca `localhost` ni un dominio privado.

## Matriz de diagnóstico

| Funcionalidad o síntoma | Servicio responsable primero | Dependencias a comprobar |
| --- | --- | --- |
| UI, rutas, SSR, cookies BFF o `/dl/*` | Frontend | `API_BASE_URL` privada y API. |
| Login, permisos, REST, `/health` o `/ready` | API | PostgreSQL, Redis y variables de aplicación. |
| CV queda en `CV_PROCESSING` | Worker | Redis, R2, OpenAI y memoria disponible. |
| Match queda en `MATCH_PROCESSING` | Worker | Redis, OpenAI, JD/CV normalizados y límites de proveedor. |
| WhatsApp no sale o no hay consentimiento | Worker y API | Meta, plantilla, firma del webhook y `PUBLIC_BASE_URL`. |
| Llamada no inicia, no termina o no hay evaluación | Worker y API | Twilio, ElevenLabs, webhooks y `MAX_CONCURRENT_CALLS`. |
| Corridas `CALLING`/`ANSWERED` estancadas | Beat, después worker/API | Logs de watchdog, Redis y lifecycle. |
| Datos, migraciones o búsqueda vectorial fallan | API y PostgreSQL | `/ready`, migración y extensión `pgvector`. |
| Tareas nunca se consumen | Worker y Redis | `REDIS_URL`, conexión al broker y comando del worker. |

## Verificación y observabilidad

Después de cada despliegue, verifica en este orden:

```bash
# Público
curl -fsS https://<api>/health
curl -fsS https://<api>/ready
curl -fsSI https://<frontend>/

# Railway: acota siempre el servicio y el tiempo de consulta
railway service list --json
railway logs --service <api> --since 1h --lines 200 --json
railway logs --service <worker> --since 1h --lines 200 --json
railway logs --service <beat> --since 1h --lines 200 --json
railway metrics --service <worker> --since 1h --cpu --memory --json
```

Valida después una carga/análisis de CV, un match y, solo con autorización y credenciales, un
consentimiento/llamada de prueba. Build exitoso, healthcheck, proveedor configurado y flujo real
son evidencias distintas; registra cuál se comprobó sin incluir secretos ni datos de candidatos.
