import asyncio
from sqlalchemy import text
from src.infrastructure.db.database import get_db

async def fix():
    async for db in get_db():
        await db.execute(text("UPDATE alembic_version SET version_num = 'aa6557c28990';"))
        await db.commit()

asyncio.run(fix())
