import re

with open('C:\\Users\\E2112\\.gemini\\antigravity\\brain\\d2428d8e-011a-47f1-b8cc-3420c8bab916\\task.md', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace('- [ ] **F3.2, F3.3, F3.4: Costos y Presupuestos**', '- [x] **F3.2, F3.3, F3.4: Costos y Presupuestos**')
content = content.replace('  - [ ] Calcular consumed_budget en métricas de proceso.', '  - [x] Calcular consumed_budget en métricas de proceso.')
content = content.replace('  - [ ] Implementar RB-010 antes de parse_cv y match.', '  - [x] Implementar RB-010 antes de parse_cv y match.')
content = content.replace('  - [ ] Añadir inserts a CostLog para mensajes de WhatsApp.', '  - [x] Añadir inserts a CostLog para mensajes de WhatsApp.')
content = content.replace('  - [ ] Añadir inserts a CostLog para evaluación de profiling (uso de tokens OpenAI).', '  - [x] Añadir inserts a CostLog para evaluación de profiling (uso de tokens OpenAI).')

content = content.replace('- [ ] **F3.5: Gobernanza IA y Caché**', '- [x] **F3.5: Gobernanza IA y Caché**')
content = content.replace('  - [ ] Crear helpers en edis_client.py para la config de IA.', '  - [x] Crear helpers en edis_client.py para la config de IA.')
content = content.replace('  - [ ] Usar helpers de Redis en parse_cv.py, un_match.py, profiling.py.', '  - [x] Usar helpers de Redis en parse_cv.py, un_match.py, profiling.py.')
content = content.replace('  - [ ] Invalidar claves en Redis cuando se edita config de IA.', '  - [x] Invalidar claves en Redis cuando se edita config de IA.')

with open('C:\\Users\\E2112\\.gemini\\antigravity\\brain\\d2428d8e-011a-47f1-b8cc-3420c8bab916\\task.md', 'w', encoding='utf-8') as f:
    f.write(content)
print("Task tracker updated")
