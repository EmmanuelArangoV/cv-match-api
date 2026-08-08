---
name: audit-pipeline-costs
description: Audita, implementa y valida la trazabilidad de costos del pipeline de RIWI MATCH Backend, incluyendo OpenAI, R2, Meta, Twilio y ElevenLabs. Usar al cambiar modelos o tarifas, revisar CostLog, conciliar una E2E, investigar duplicados o costos faltantes, comparar modelos, o dejar una demo limpia después de pruebas reales.
---

# Auditar costos del pipeline

## Objetivo

Obtener un costo E2E reproducible y explicable sin confundir estimaciones de tarifa con importes
reportados por proveedores. Mantener cada gasto idempotente, atribuible a proceso/candidato y con
evidencia suficiente en `cost_breakdown`.

## Flujo obligatorio

1. Lee `references/cost-model.md` antes de cambiar cálculos, modelos o persistencia.
2. Revisa `src/infrastructure/costs.py`, el modelo `CostLog` y la migración vigente. El código es
   la fuente operativa; la referencia explica el contrato.
3. Si una tarifa puede haber cambiado, consulta primero la página oficial del proveedor y guarda
   URL y fecha de verificación. Nunca reutilices silenciosamente la tarifa de otro modelo.
4. Antes de activar un modelo OpenAI, valida acceso, parámetros compatibles, salida JSON y tarifa
   registrada. Para GPT-5.6 usa las opciones centralizadas en `ai/model_compat.py`.
5. Ejecuta pruebas unitarias de cálculo, extracción de uso, idempotencia y cada call site afectado.
6. Ejecuta `scripts/audit_costs.py` antes y después de una E2E. Filtra por `--process-id` para
   conciliar una corrida concreta.
7. En una E2E real registra, como aplique: almacenamiento, extracción, embedding, match, WhatsApp,
   Twilio, ElevenLabs y evaluación post-call. Espera webhooks tardíos antes de cerrar el total.
8. Limpia primero los `CostLog` de QA y después las entidades/R2/cache creadas para la prueba.
   Verifica por marcador e IDs exactos; no hagas borrados amplios.

## Comandos

Desde `Backend/`:

```bash
.venv/bin/python .agents/skills/audit-pipeline-costs/scripts/audit_costs.py
.venv/bin/python .agents/skills/audit-pipeline-costs/scripts/audit_costs.py \
  --process-id UUID --json
.venv/bin/pytest -q tests/unit/infrastructure/test_costs.py
.venv/bin/ruff check src tests .agents/skills/audit-pipeline-costs/scripts
```

## Criterios de aceptación

- Cada fila nueva tiene `provider`, `currency`, `cost_source` y `cost_breakdown` coherentes.
- Toda operación con ID de proveedor usa `external_reference` único.
- OpenAI guarda modelo, entrada, entrada cacheada, salida y detalles de razonamiento/cache cuando
  el SDK los expone.
- Los importes reportados por Twilio/ElevenLabs prevalecen sobre estimaciones; la procedencia queda
  explícita.
- R2 se presenta como costo bruto de tarifa si no se aplica la capa gratuita al cálculo.
- Reintentos y webhooks duplicados no duplican gasto.
- El total por proceso coincide con la suma de operaciones y con lo mostrado por la API/UI.
- Una prueba se reporta como E2E real solo si recorrió proveedores y webhooks reales; en otro caso
  se nombra exactamente como unit, integración o mock.

## Límites

- No imprimas variables de entorno ni secretos.
- No borres filas históricas `legacy_estimate` para hacer que una auditoría parezca limpia.
- No cambies el modelo conversacional de ElevenLabs al migrar los workloads OpenAI: son controles
  distintos.
- No actives ni despliegues una migración antes de que pruebas y auditoría local estén verdes.
