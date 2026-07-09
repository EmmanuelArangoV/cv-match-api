import re

with open('src/infrastructure/ai/prompts.py', 'r', encoding='utf-8') as f:
    content = f.read()

target = '''def build_match_messages(
    normalized_cv: dict,
    jd_text: str,
    weights: dict,
) -> list[dict]:'''

replacement = '''def build_match_messages(
    normalized_cv: dict,
    jd_text: str,
    weights: dict,
    system_prompt: str = None,
    user_template: str = None,
) -> list[dict]:'''

target2 = '''    user_content = _MATCH_USER_TEMPLATE.format('''

replacement2 = '''    template = user_template or _MATCH_USER_TEMPLATE
    user_content = template.format('''

target3 = '''    return [
        {"role": "system", "content": _MATCH_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]'''

replacement3 = '''    return [
        {"role": "system", "content": system_prompt or _MATCH_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]'''

if target in content:
    content = content.replace(target, replacement)
if target2 in content:
    content = content.replace(target2, replacement2)
if target3 in content:
    content = content.replace(target3, replacement3)

with open('src/infrastructure/ai/prompts.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated prompts.py for dynamic match prompts")
