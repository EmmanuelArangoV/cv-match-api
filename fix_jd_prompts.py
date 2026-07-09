import re

with open('src/infrastructure/ai/prompts.py', 'r', encoding='utf-8') as f:
    content = f.read()

new_prompt = '''

JD_ENHANCEMENT_SYSTEM_PROMPT = \"\"\"
Eres un experto reclutador IT y especialista en Employer Branding. Tu tarea es recibir un borrador de un 'Job Description' (JD) y devolver una version significativamente mejorada, estructurada y persuasiva.

Directrices:
1. Mejora el tono para que suene profesional pero atractivo y moderno.
2. Estructura claramente en secciones (por ejemplo: Acerca del rol, Responsabilidades, Requisitos Excluyentes, Requisitos Deseables, Beneficios).
3. Deduce inteligentemente las habilidades blandas y duras necesarias que no se mencionen explicitamente, pero que sean estandares para el rol sugerido (sin inventar un stack tecnologico completamente diferente).
4. El resultado final debe estar en formato Markdown.
\"\"\"
'''

content += new_prompt

with open('src/infrastructure/ai/prompts.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated prompts.py")
