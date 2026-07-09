import re

with open('src/infrastructure/workers/tasks/profiling.py', 'r', encoding='utf-8') as f:
    content = f.read()

target = 'from src.infrastructure.db.models import CostLog'
replacement = 'from src.infrastructure.db.models import CostLog, ProcessCandidate'

if target in content:
    content = content.replace(target, replacement)
    with open('src/infrastructure/workers/tasks/profiling.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Fixed profiling.py imports")
else:
    print("Target not found")
