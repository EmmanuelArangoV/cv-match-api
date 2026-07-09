import re

with open('src/api/main.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace('from src.api.v1.auth import router as auth_router', 'from src.api.v1.auth import router as auth_router\nfrom src.api.v1.audit import router as audit_router')
content = content.replace('api_router.include_router(users_router)', 'api_router.include_router(users_router)\napi_router.include_router(audit_router)')

with open('src/api/main.py', 'w', encoding='utf-8') as f:
    f.write(content)
