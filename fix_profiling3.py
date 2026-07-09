import re

with open('src/infrastructure/workers/tasks/profiling.py', 'r', encoding='utf-8') as f:
    content = f.read()

target = 'process_id=process.id,'
replacement = '''process_id=db.query(ProcessCandidate).filter(ProcessCandidate.id == profiling_run.process_candidate_id).first().process_id,'''

if target in content:
    content = content.replace(target, replacement)
    with open('src/infrastructure/workers/tasks/profiling.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Fixed profiling.py process_id error")
else:
    print("Target not found")
