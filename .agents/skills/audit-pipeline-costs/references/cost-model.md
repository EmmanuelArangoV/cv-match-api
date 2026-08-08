# Modelo de costos auditable

## Alcance E2E

El pipeline puede producir estas operaciones en `CostLog`:

| Operación | Proveedor esperado | Evidencia principal |
|---|---|---|
| `CV_STORAGE` | Cloudflare R2 | bytes y operaciones A/B |
| `CV_EXTRACTION` | OpenAI | response ID, modelo y tokens |
| `CV_EMBEDDING` | OpenAI | response ID, modelo y tokens |
| `CV_MATCH` | OpenAI | response ID, modelo y tokens |
| `JD_ENHANCEMENT` | OpenAI | response ID, modelo y tokens |
| `WHATSAPP_MESSAGE` | Meta | message ID y categoría |
| `WHATSAPP_AI` | OpenAI | response ID, modelo y tokens |
| `TWILIO_CALL` | Twilio | CallSid, duración, AMD y stream |
| `VOICE_CALL` | ElevenLabs | conversation ID y costo fiat reportado |
| `ANSWER_EVALUATION` | OpenAI | response ID, modelo y tokens |

`VOICE_TRANSCRIPTION` solo debe existir si hay un cargo separado verificable; no dividas
artificialmente un costo ya incluido por ElevenLabs.

## Contrato de persistencia

- `estimated_cost` conserva su nombre histórico, pero `cost_source` determina si es tarifa,
  proveedor o legado.
- `external_reference` implementa idempotencia. Usa prefijos estables cuando una misma referencia
  genera varias operaciones, por ejemplo `twilio:{CallSid}` y `elevenlabs:{conversation_id}`.
- `cost_breakdown` debe poder explicar el importe sin consultar logs efímeros.
- `process_id` es obligatorio cuando el gasto pertenece a un proceso. `candidate_id` se registra
  cuando la operación es atribuible a una persona.
- Los callbacks tardíos pueden completar costos después del estado funcional de la llamada.

## OpenAI y GPT-5.6 Luna

Tarifas verificadas el 2026-08-08 en la documentación oficial de `gpt-5.6-luna`:

- entrada: USD 0.20 por millón de tokens;
- entrada cacheada: USD 0.02 por millón;
- escritura de caché: USD 0.25 por millón;
- salida: USD 1.20 por millón.

Fuente: <https://developers.openai.com/api/docs/models/gpt-5.6-luna>

Estas cifras son una foto fechada, no una garantía futura. Al modificarlas:

1. verifica la página exacta del modelo;
2. actualiza `src/infrastructure/costs.py`, URL y fecha;
3. agrega una prueba numérica con entrada normal, cache read, cache write y salida;
4. ejecuta un smoke real de salida JSON;
5. activa el modelo mediante migración/configuración solo después.

Los tokens de razonamiento están incluidos en los tokens de salida reportados: se guardan para
observabilidad pero no se suman otra vez. `reasoning_effort="low"` reduce latencia/costo para este
flujo estructurado y se centraliza en `src/infrastructure/ai/model_compat.py`.

## Proveedores de voz y mensajería

- ElevenLabs: prioriza `cost_fiat`; conserva créditos y desglose de LLM como diagnóstico.
- Twilio: usa el precio del Call Resource cuando esté disponible; suma AMD y Media Streams solo si
  fueron usados y no vienen incluidos en ese importe.
- AMD asíncrono cambia latencia y agrega el cargo de AMD, pero no debe duplicar el costo al recibir
  callbacks repetidos.
- Meta: registra una plantilla solo cuando el proveedor devuelve un ID aceptado/entregado según el
  contrato elegido.
- R2: el cálculo actual es bruto y declara `free_tier_applied=false`.

## Conciliación y limpieza

Una conciliación completa incluye:

1. inventario anterior;
2. IDs del proceso, candidato, profiling run y referencias externas de QA;
3. suma por operación/proveedor/modelo/fuente;
4. búsqueda de duplicados y filas sin desglose;
5. comparación con dashboards/APIs de proveedor cuando existan;
6. borrado acotado de `CostLog` antes de borrar proceso/candidato;
7. borrado de objetos R2 y claves Redis identificadas;
8. auditoría posterior que demuestre cero residuos del marcador de QA.

Las filas históricas con `legacy_estimate`, referencias nulas o relaciones nulas se reportan por
separado. No son prueba de que la telemetría nueva falló.
