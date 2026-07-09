import re

with open('src/infrastructure/workers/tasks/parse_cv.py', 'r', encoding='utf-8') as f:
    content = f.read()

target1 = '''def _call_openai(content_blocks: list[dict], client: OpenAI) -> tuple[dict, int, int]:
    \"\"\"Llama a gpt-4o con el prompt de extracciA3n + los bloques de contenido.\"\"\"
    content: list[dict] = [{"type": "text", "text": CV_EXTRACTION_PROMPT}]'''

replacement1 = '''def _call_openai(content_blocks: list[dict], client: OpenAI, prompt: str, model: str) -> tuple[dict, int, int]:
    content: list[dict] = [{"type": "text", "text": prompt}]'''

target1_alt = '''def _call_openai(content_blocks: list[dict], client: OpenAI) -> tuple[dict, int, int]:
    \"\"\"Llama a gpt-4o con el prompt de extracción + los bloques de contenido.\"\"\"
    content: list[dict] = [{"type": "text", "text": CV_EXTRACTION_PROMPT}]'''

if target1 in content:
    content = content.replace(target1, replacement1)
elif target1_alt in content:
    content = content.replace(target1_alt, replacement1)

target2 = '''            # Llamar a OpenAI
            openai_client = _get_openai()
            extracted, tokens_in, tokens_out = _call_openai(content_blocks, openai_client)'''

replacement2 = '''            # Llamar a OpenAI
            openai_client = _get_openai()
            from src.infrastructure.cache.redis_client import get_active_ai_prompt_sync, get_active_ai_model_sync
            prompt = get_active_ai_prompt_sync(db, "PROFILE_EXTRACT", CV_EXTRACTION_PROMPT)
            model = get_active_ai_model_sync(db, "OPENAI", "gpt-4o")
            extracted, tokens_in, tokens_out = _call_openai(content_blocks, openai_client, prompt, model)'''

if target2 in content:
    content = content.replace(target2, replacement2)

target3 = '''        response = client.chat.completions.create(
            model="gpt-4o",'''

replacement3 = '''        response = client.chat.completions.create(
            model=model,'''

if target3 in content:
    content = content.replace(target3, replacement3)

with open('src/infrastructure/workers/tasks/parse_cv.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated parse_cv.py")
