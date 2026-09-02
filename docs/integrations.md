---
sidebar_position: 5
---

# Dependencias e integraciones

`.env.example` es el inventario de configuración. Las credenciales nunca deben documentarse ni
registrarse en logs.

| Grupo | Dependencias | Uso |
| --- | --- | --- |
| Base | PostgreSQL + pgvector, Redis | Persistencia, broker y resultados de Celery. |
| IA y archivos | OpenAI, Cloudflare R2 | Extracción, match, evaluación y objetos. |
| Voz | Twilio, ElevenLabs | Llamada saliente, conversación, audio y transcript. |
| Consentimiento | Meta WhatsApp Business | Plantillas, mensajes y webhook. |

## Validación por proveedor

- R2: comprobar carga/lectura controlada y URL firmada o stream protegido.
- OpenAI: ejecutar una operación autorizada y conciliar su `CostLog`.
- Meta, Twilio y ElevenLabs: verificar HTTPS público, secreto de firma y callback idempotente.
- PostgreSQL/Redis: usar `/ready` y las pruebas de integración con servicios reales.

La disponibilidad de una variable no demuestra que su proveedor esté funcional. Los resultados
deben registrarse por ambiente, fecha y tipo de prueba.
