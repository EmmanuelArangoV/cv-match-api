# 🚀 Estado Actual del Proyecto: RIWI MATCH (Backend)

> Actualizado el **2026-07-08** tras una auditoría código-vs-documentación. La versión anterior de
> este documento describía la integración de voz como mock: **ya no es así** — la integración es
> real desde los commits `c5f24bd`, `04dded4` y `ca48351`. El plan detallado para cerrar lo que
> falta está en **`PLAN_MVP_100.md`**, en la raíz del monorepo (repo padre `RiwiMatch`, no dentro
> de este submódulo).

---

## ✅ 1. Lo que funciona completo y con integraciones reales

1. **Auth (JWT + roles):** login, refresh con rotación, logout, roles ADMIN/RECRUITER/TA_LEADER,
   estados ACTIVE/SUSPENDED, filtro por recruiter en procesos.
2. **Procesos + JD:** CRUD de creación/listado/detalle, JD por texto o archivo (PDF/DOCX/TXT),
   parseo de JD con IA (must-have / nice-to-have / deal-breakers), JD versionada inmutable,
   pesos de match configurables por proceso (`match_weights_override`).
3. **Carga y parseo de CVs:** hasta 50 por lote, deduplicación por SHA-256, upload a R2, extracción
   con `gpt-4o` (incluida Vision para imágenes), embedding `text-embedding-3-small` en pgvector,
   PDF normalizado, CostLog por extracción.
4. **Motor de match:** pesos por 6 categorías, clasificación HIGH/MEDIUM/LOW/NOT_RECOMMENDED,
   fortalezas/gaps/breakdown explicado, ranking, override humano con notas, CostLog por match.
5. **WhatsApp (Meta Business, real):** plantilla de consentimiento, firma HMAC verificada, agente
   conversacional con IA para dudas frecuentes, estados de consentimiento
   PENDING/ACCEPTED/REJECTED/TIMEOUT, disparo automático del profiling al aceptar.
6. **Llamadas de voz (Twilio + ElevenLabs, real — NO mock):** SDKs oficiales (`twilio>=9.0.0`,
   `elevenlabs>=2.56.0`), AMD síncrono (si contesta un buzón se cuelga sin invocar a ElevenLabs),
   `register_call` real, webhooks con firma verificada (Twilio y ElevenLabs), status-callback para
   llamadas que nunca conectan, watchdog `check_stale_profiling_calls` vía Celery Beat, evaluación
   post-llamada con `AdvancementProbability` (RB-006/007), RB-005 y RB-010 validados antes de
   llamar, CostLog de voz, use cases en `src/application/profiling/`.
7. **Question sets:** CRUD completo de sets y preguntas (tipos, pesos, keywords, criticidad,
   criterios de evaluación), configuración de voz por defecto y override por proceso.
8. **Configuración de IA (endpoints):** CRUD de modelos con exclusión mutua de activo, prompts
   append-only, global_business_settings (`src/api/v1/ai_config.py`).
9. **Métricas de costos:** dashboard agregado (total, por proceso, por usuario, por operación,
   diario) en `src/api/v1/metrics.py`.

---

## 🏗️ 2. Lo que existe pero está incompleto (parcial)

1. **CostLog:** cubre CV, match y voz; falta registrar WhatsApp y la evaluación post-profiling.
2. **Circuit breaker RB-010:** se aplica antes de las llamadas de voz, pero no antes de
   `run_match` ni `parse_cv`.
3. **Configuración de IA dinámica:** los endpoints existen, pero los workers usan `"gpt-4o"`
   hardcodeado en vez de leer el modelo/prompt activo.
4. **RB-005 (máx. 4 llamadas simultáneas):** se valida **por proceso**; el documento maestro lo
   define **global**.
5. **Consentimiento verbal en llamada:** la columna `call_consent_status` existe pero ningún flujo
   la escribe.
6. **Versionamiento de question sets:** el campo `version` existe, pero editar un set usado muta la
   versión actual en vez de crear una nueva.
7. **Métricas por proceso / vista Líder TA:** solo existe el dashboard de costos global.
8. **Vista detalle de candidato:** falta exponer estado de profiling, respuestas capturadas
   (`ProfilingAnswer`) y transcripción completa.

---

## ⏳ 3. Lo que falta por completo

1. **CRUD de usuarios por API** — solo existen `scripts/create_admin.py` / `create_recruiter.py`.
2. **`resolve_whatsapp_timeout`** — el consentimiento `PENDING` no pasa a `TIMEOUT` a las 24 h por
   sí solo (única pieza del contrato de voz sin implementar).
3. **Audit logs** — la tabla `AuditLog` existe pero ningún endpoint escribe en ella (criterio de
   aceptación 15 del MVP, el único faltante).
4. **Alertas de presupuesto (80/90/100%)** — RB-010 bloquea al 100% (solo en voz), sin alertas
   proactivas.
5. **Feedback loop** — marcar análisis de IA como correcto/parcial/incorrecto.
6. **Editar / cerrar / archivar proceso por API** — las transiciones existen en la máquina de
   estados pero no hay endpoints.
7. **Endpoints de export/reportes (CSV)**.
8. **Post-MVP (decidido, no olvidado):** RLS, SSE, Azure Document Intelligence (OCR plan B) —
   justificación en `PLAN_MVP_100.md` §6.

---

## 🧪 4. Tests

**22 tests unitarios**, todos del dominio de voz/profiling (máquina de estados del candidato,
watchdog, resolver de config de voz, firmas de Twilio/ElevenLabs). Sin cobertura de auth, procesos,
CVs, match, WhatsApp ni métricas. Objetivo del plan: 60+ tests (ver `PLAN_MVP_100.md` §5).
