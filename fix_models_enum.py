import re

with open('src/infrastructure/db/models.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace(
    '    CV_MATCH = "CV_MATCH"',
    '    CV_MATCH = "CV_MATCH"\n    JD_ENHANCEMENT = "JD_ENHANCEMENT"'
)

with open('src/infrastructure/db/models.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated models.py")
