import re

with open('src/api/v1/auth.py', 'r', encoding='utf-8') as f:
    content = f.read()

target = '''    from src.infrastructure.auth.tokens import create_access_token

    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)'''

replacement = '''    from src.infrastructure.auth.tokens import create_access_token
    from src.infrastructure.db.audit import record_audit

    record_audit(
        session=db,
        user_id=user.id,
        action="USER_LOGIN",
        entity_type="User",
        entity_id=user.id,
        ip_address=None
    )

    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)'''

if target in content:
    content = content.replace(target, replacement)
    with open('src/api/v1/auth.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Added audit to auth.py")
else:
    print("Target not found in auth.py")
