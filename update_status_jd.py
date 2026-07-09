import re

with open('C:\\Users\\E2112\\.gemini\\antigravity\\brain\\d2428d8e-011a-47f1-b8cc-3420c8bab916\\STATUS_RESUMEN.md', 'r', encoding='utf-8') as f:
    content = f.read()

content += '''

### Novedades Recientes
- **AI JD Enhancement**: Nuevo endpoint POST /api/v1/ai-tools/enhance-jd que permite a los reclutadores enviar un borrador de Job Description y recibir una versión estructurada, atractiva y profesional potenciada por OpenAI.
'''

with open('C:\\Users\\E2112\\.gemini\\antigravity\\brain\\d2428d8e-011a-47f1-b8cc-3420c8bab916\\STATUS_RESUMEN.md', 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated STATUS_RESUMEN.md")
