# 🚀 Estado Actual del Proyecto: RIWI MATCH (Backend)

Este documento resume el progreso actual del desarrollo, detallando exactamente qué piezas ya están operativas en producción (o listas para ello), cuáles están funcionando bajo simulación (mock), y cuáles son las integraciones que aún están pendientes por desarrollar o configurar.

---

## ✅ 1. Lo que ya hace y FUNCIONA completamente

Estas piezas de la arquitectura ya están programadas, estructuradas y listas para operar con datos reales:

1. **Subida y Deduplicación de CVs (`use_cases.py`):**
   - El sistema carga hasta 50 CVs en lote, procesándolos de manera asíncrona.
   - Antes de enviar a parsear, calcula el hash `SHA-256` del archivo para identificar si un CV exacto ya fue subido, ahorrando costos de IA e impidiendo procesamientos duplicados.
2. **Parseo de CVs y Vectorización (`parse_cv.py`):**
   - Usa `gpt-4o` (incluyendo su capacidad de *Vision* para imágenes) para extraer información estructurada (habilidades, experiencia, años, educación).
   - Calcula y almacena en Supabase un **embedding vectorial** de OpenAI (`text-embedding-3-small`) usando `pgvector`, lo que permitirá futuras búsquedas semánticas.
3. **Motor de Match (CV vs JD) (`run_match.py`):**
   - Analiza la experiencia, habilidades, senioridad, y dominio contra la *Job Description*.
   - Retorna un porcentaje de afinidad ponderado, fortalezas, y carencias ("gaps"), clasificando al candidato (`HIGH`, `MEDIUM`, `LOW`, `NOT_RECOMMENDED`).
   - El costo de tokens y dinero se guarda automáticamente en la tabla de trazabilidad (`CostLog`).
4. **Agente de WhatsApp y Webhooks (`whatsapp_message_usecase.py`):**
   - Integración nativa con la API de Meta Business y seguridad HMAC verificada.
   - Lee el intent del candidato ("sí, acepto", "no estoy interesado" desde botones o texto libre).
   - Usa un agente conversacional (`gpt-4o`) configurado con reglas estrictas para responder dudas frecuentes (disponibilidad, legalidad, proceso) de forma cálida y profesional.
   - Si el candidato acepta, **dispara automáticamente** la orquestación del *Voice Profiling*.

---

## 🏗️ 2. Lo que "medio funciona" (Integración Estructural / Mocks)

Estas piezas tienen toda la arquitectura construida (Webhooks, Tareas en Celery y Lógica de Base de Datos), pero actualmente **simulan** la conexión externa para facilitar el desarrollo local:

1. **Orquestación de Llamadas Salientes (`profiling.py`):**
   - **Flujo:** La base de datos y la máquina de estados ya hacen la transición del candidato a `PROFILING_CALLING`.
   - **Simulación:** El archivo `twilio_client.py` actualmente tiene un "mock" que imprime en consola que está realizando la llamada en lugar de hacer el POST real a Twilio.
2. **Webhooks de Profiling (`webhooks.py`):**
   - **Twilio AMD (Answering Machine Detection):** El webhook `/api/v1/webhooks/twilio/amd` ya existe y tiene la lógica para colgar si es buzón o conectar a ElevenLabs si es humano, pero requiere exponer tu servidor local con `ngrok` para que Twilio pueda golpearlo realmente.
   - **ElevenLabs Transcripción:** El webhook `/elevenlabs` ya sabe qué hacer cuando recibe la transcripción (encolar la evaluación de la IA), pero el cliente `elevenlabs_client.py` hoy retorna una transcripción *quemada/simulada* en código.
3. **Evaluación Post-Profiling (`evaluate_profiling_transcription`):**
   - El Celery task que toma el texto de la entrevista, lo cruza contra el cuestionario (`QuestionSet`) y le pide a OpenAI que genere el `AdvancementProbability` (`HIGH`/`MEDIUM`/`LOW`). Está listo, pero se alimenta de la transcripción simulada.

---

## ⏳ 3. Integraciones y Tareas Faltantes

Para que el backend alcance el 100% de la funcionalidad descrita en la arquitectura, quedan pendientes las siguientes tareas:

### Trabajo para tu compañero (Twilio & ElevenLabs)
1. **Conectar el cliente real de Twilio:** Reemplazar el `logger.info` en `twilio_client.py` por la llamada real `httpx.post` a la API de Twilio usando `TWILIO_ACCOUNT_SID`.
2. **Conectar el Agente de ElevenLabs:** Twilio requiere conectarse vía WebSocket a ElevenLabs. Hay que asegurar que el Agent ID esté bien configurado en la plataforma de Eleven y expuesto en el `.env`.

### Tareas de Backend Pendientes
1. **El "Circuit Breaker" de Costos (Regla RB-010):** Actualmente guardamos el costo (CostLog), pero falta agregar una validación que sume los costos por `HiringProcess` e impida encolar nuevas tareas a OpenAI si se superó el `budget_max_usd`.
2. **Azure Document Intelligence (OCR Fuerte):** Hoy le enviamos imágenes a GPT-4o. Si la calidad del CV es muy mala o es un PDF muy largo, deberíamos implementar el cliente de Azure OCR como plan B (las credenciales ya están en el `.env`).
3. **Estructurador Inteligente de Job Descriptions:** El endpoint `POST /processes/{process_id}/job-description` que toma texto libre de una vacante y lo rompe usando IA en "Must-haves", "Nice-to-haves" y "Deal-breakers" (actualmente el motor de Match asume que la BD ya tiene esta estructura).
4. **Orquestador Temporal (Cron / Temporizador):** Mencionaste "por defecto a las 24 horas los que aceptaron". Hoy la llamada de Twilio se dispara *inmediatamente* tras el "sí, acepto". Se requerirá configurar Celery Beat o usar la bandera `countdown` de Celery para hacer el retraso de 24 horas en producción.
5. **Conectar todo al Frontend (Next.js):** El UI debe consumir estos endpoints (autenticación JWT, creación de procesos, paneles de ranking de match).
