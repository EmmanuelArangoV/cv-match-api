import re

with open('src/infrastructure/workers/tasks/profiling.py', 'r', encoding='utf-8') as f:
    content = f.read()

target = '''            prompt = (
                f"{PROFILING_EVALUATION_PROMPT}\\n\\n=== QUESTION SET ===\\n"
                f"{json.dumps(questions_data, indent=2)}\\n\\n=== TRANSCRIPT ===\\n{transcript}\\n"
            )

            client = _get_openai()
            response = client.chat.completions.create(
                model="gpt-4o",'''

replacement = '''            from src.infrastructure.cache.redis_client import get_active_ai_prompt_sync, get_active_ai_model_sync
            sys_prompt = get_active_ai_prompt_sync(db, "VOICE_PROFILING", PROFILING_EVALUATION_PROMPT)
            model = get_active_ai_model_sync(db, "OPENAI", "gpt-4o")

            prompt = (
                f"{sys_prompt}\\n\\n=== QUESTION SET ===\\n"
                f"{json.dumps(questions_data, indent=2)}\\n\\n=== TRANSCRIPT ===\\n{transcript}\\n"
            )

            client = _get_openai()
            response = client.chat.completions.create(
                model=model,'''

if target in content:
    content = content.replace(target, replacement)
    with open('src/infrastructure/workers/tasks/profiling.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Updated profiling.py")
else:
    print("Target not found for profiling")
