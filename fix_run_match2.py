import re

with open('src/infrastructure/workers/tasks/run_match.py', 'r', encoding='utf-8') as f:
    content = f.read()

target = '''def _call_openai(
    normalized_cv: dict,
    jd_text: str,
    weights: dict,
    client: OpenAI,
) -> tuple[dict, int, int]:
    \"\"\"Llama a gpt-4o con el prompt de match y retorna (resultado_json, tokens_in, tokens_out).\"\"\"
    messages = build_match_messages(
        normalized_cv=normalized_cv,
        jd_text=jd_text,
        weights=weights,
    )
    response = client.chat.completions.create(
        model="gpt-4o",'''

replacement = '''def _call_openai(
    normalized_cv: dict,
    jd_text: str,
    weights: dict,
    client: OpenAI,
    prompt: str,
    model: str,
) -> tuple[dict, int, int]:
    messages = build_match_messages(
        normalized_cv=normalized_cv,
        jd_text=jd_text,
        weights=weights,
        system_prompt=prompt,
    )
    response = client.chat.completions.create(
        model=model,'''

target2 = '''            extracted, tokens_in, tokens_out = _call_openai(
                normalized_cv=pc.candidate.normalized_cv,
                jd_text=jd_text,
                weights=weights,
                client=openai_client,
            )'''

replacement2 = '''            from src.infrastructure.cache.redis_client import get_active_ai_prompt_sync, get_active_ai_model_sync
            prompt = get_active_ai_prompt_sync(db, "CV_MATCH", None)
            model = get_active_ai_model_sync(db, "OPENAI", "gpt-4o")

            extracted, tokens_in, tokens_out = _call_openai(
                normalized_cv=pc.candidate.normalized_cv,
                jd_text=jd_text,
                weights=weights,
                client=openai_client,
                prompt=prompt,
                model=model,
            )'''

if target in content:
    content = content.replace(target, replacement)
if target2 in content:
    content = content.replace(target2, replacement2)

with open('src/infrastructure/workers/tasks/run_match.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated run_match.py")
