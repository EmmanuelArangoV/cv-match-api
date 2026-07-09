import re

with open('C:\\Users\\E2112\\.gemini\\antigravity\\brain\\d2428d8e-011a-47f1-b8cc-3420c8bab916\\STATUS_RESUMEN.md', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace('## Próximos Pasos (Fase 3: Costos y Gobernanza)', '## Fase 3 Completada (Costos y Gobernanza)\n\nSe ha implementado auditoría, dashboards para TA Leaders, exportación CSV, RB-010 circuit breaker de presupuestos, y caché en Redis de la configuración de IA.')

with open('C:\\Users\\E2112\\.gemini\\antigravity\\brain\\d2428d8e-011a-47f1-b8cc-3420c8bab916\\STATUS_RESUMEN.md', 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated STATUS_RESUMEN.md")
