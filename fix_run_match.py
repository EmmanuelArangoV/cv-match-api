import re

with open('src/infrastructure/workers/tasks/run_match.py', 'r', encoding='utf-8') as f:
    content = f.read()

target = '''        messages = build_match_messages(
            normalized_cv=normalized_cv,
            jd_text=jd_text,
            weights=weights,
        )
        response = client.chat.completions.create(
            model="gpt-4o",'''

replacement = '''        from src.infrastructure.cache.redis_client import get_active_ai_prompt_sync, get_active_ai_model_sync
        
        # We assume the system_prompt and user_template can be stored together or we just fetch the system one.
        # But for CV_MATCH, prompt might be system prompt. If there's no user template config, we rely on default.
        # It's better to fetch CV_MATCH_SYSTEM and CV_MATCH_USER if needed. We'll just fetch CV_MATCH.
        system_prompt = get_active_ai_prompt_sync(db, "CV_MATCH", None)
        model = get_active_ai_model_sync(db, "OPENAI", "gpt-4o")

        messages = build_match_messages(
            normalized_cv=normalized_cv,
            jd_text=jd_text,
            weights=weights,
            system_prompt=system_prompt,
        )
        response = client.chat.completions.create(
            model=model,'''

if target in content:
    content = content.replace(target, replacement)
    with open('src/infrastructure/workers/tasks/run_match.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Updated run_match.py")
else:
    print("Target not found for run_match")
