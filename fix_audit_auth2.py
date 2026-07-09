import re

with open('src/api/v1/auth.py', 'r', encoding='utf-8') as f:
    content = f.read()

target = '''async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)) -> dict:
    return await LoginUseCase(UserRepository(db)).execute(body.email, body.password)'''

replacement = '''async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)) -> dict:
    result = await LoginUseCase(UserRepository(db)).execute(body.email, body.password)
    from src.infrastructure.db.audit import record_audit
    user = await UserRepository(db).find_by_email(body.email)
    if user:
        record_audit(db, user.id, "USER_LOGIN", "User", user.id)
        await db.commit()
    return result'''

if target in content:
    content = content.replace(target, replacement)
    with open('src/api/v1/auth.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Added audit to auth.py")
else:
    print("Target not found in auth.py")
