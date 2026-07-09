import re

with open('src/api/v1/ai_config.py', 'r', encoding='utf-8') as f:
    content = f.read()

target1 = '''    model.is_active = True
    await db.commit()'''

replacement1 = '''    model.is_active = True
    await db.commit()
    from src.infrastructure.cache.redis_client import redis_client
    await redis_client.delete(f"ai_model:active:{model.provider}")'''

target2 = '''    db.add(new_prompt)
    await db.commit()'''

replacement2 = '''    db.add(new_prompt)
    await db.commit()
    from src.infrastructure.cache.redis_client import redis_client
    if new_prompt.is_active:
        await redis_client.delete(f"ai_prompt:active:{new_prompt.task_type}")'''

if target1 in content:
    content = content.replace(target1, replacement1)
if target2 in content:
    content = content.replace(target2, replacement2)

with open('src/api/v1/ai_config.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated ai_config.py for invalidation")
