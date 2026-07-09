import re

with open('src/api/main.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace('from src.api.v1.reports import router as reports_router', 'from src.api.v1.reports import router as reports_router\nfrom src.api.v1.ai_tools import router as ai_tools_router')
content = content.replace('api_router.include_router(reports_router)', 'api_router.include_router(reports_router)\napi_router.include_router(ai_tools_router)')

with open('src/api/main.py', 'w', encoding='utf-8') as f:
    f.write(content)
