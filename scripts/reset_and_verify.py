"""
Reset DB (deja solo recruiter@riwi.io) y verifica Redis, R2 y Celery.
"""
import asyncio
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import bcrypt
from sqlalchemy import text
from src.infrastructure.db.database import AsyncSessionFactory
from src.infrastructure.db.models import User, UserRole, UserStatus


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


# ── 1. Reset DB ────────────────────────────────────────────────────────────────

async def reset_db():
    print("\n=== 1. RESET BASE DE DATOS ===")
    tables = [
        "whatsapp_conversations",
        "operation_logs",
        "candidates",
        "hiring_processes",
    ]
    # Cada tabla en su propia transaccion para que un fallo no bloquee el resto
    for table in tables:
        try:
            async with AsyncSessionFactory() as db:
                result = await db.execute(text(f"DELETE FROM {table}"))
                await db.commit()
                print(f"  OK {table}: {result.rowcount} filas eliminadas")
        except Exception as e:
            print(f"  SKIP {table}: no existe o error ({type(e).__name__})")

    async with AsyncSessionFactory() as db:
        result = await db.execute(
            text("DELETE FROM users WHERE email != 'recruiter@riwi.io'")
        )
        await db.commit()
        print(f"  OK users (no-recruiter): {result.rowcount} eliminados")

    print("  -> DB limpia")


# ── 2. Crear/verificar recruiter ───────────────────────────────────────────────

async def ensure_recruiter():
    print("\n=== 2. RECRUITER ===")
    EMAIL    = "recruiter@riwi.io"
    PASSWORD = "riwi2026"

    async with AsyncSessionFactory() as db:
        result = await db.execute(
            text("SELECT id, email FROM users WHERE email = :e"), {"e": EMAIL}
        )
        row = result.fetchone()
        if row:
            print(f"  OK Ya existe: {EMAIL}")
        else:
            user = User(
                name="Recruiter",
                last_name="RIWI",
                email=EMAIL,
                password_hash=hash_password(PASSWORD),
                role=UserRole.RECRUITER.value,
                status=UserStatus.ACTIVE.value,
            )
            db.add(user)
            await db.commit()
            print(f"  OK Creado: {EMAIL}")

    print(f"  Email:    {EMAIL}")
    print(f"  Password: {PASSWORD}")


# ── 3. Verificar Redis ─────────────────────────────────────────────────────────

async def check_redis():
    print("\n=== 3. REDIS (Upstash) ===")
    import redis.asyncio as aioredis
    from src.config import Settings
    settings = Settings()
    try:
        r = aioredis.from_url(settings.redis_url, decode_responses=True, ssl_cert_reqs=None)
        await r.set("ping_test", "pong", ex=10)
        val = await r.get("ping_test")
        assert val == "pong"
        await r.aclose()
        print(f"  OK Redis OK — URL: {settings.redis_url[:40]}...")
    except Exception as e:
        print(f"  FAIL Redis FAIL: {e}")


# ── 4. Verificar R2 ────────────────────────────────────────────────────────────

def check_r2():
    print("\n=== 4. CLOUDFLARE R2 ===")
    import boto3
    from src.config import Settings
    settings = Settings()
    try:
        s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
        )
        # Subir objeto de prueba
        s3.put_object(Bucket=settings.r2_bucket_name, Key="_health/ping.txt", Body=b"ok")
        # Leerlo
        obj = s3.get_object(Bucket=settings.r2_bucket_name, Key="_health/ping.txt")
        assert obj["Body"].read() == b"ok"
        # Borrarlo
        s3.delete_object(Bucket=settings.r2_bucket_name, Key="_health/ping.txt")
        print(f"  OK R2 OK — bucket: {settings.r2_bucket_name}")
    except Exception as e:
        print(f"  FAIL R2 FAIL: {e}")


# ── 5. Verificar Celery ────────────────────────────────────────────────────────

def check_celery():
    print("\n=== 5. CELERY ===")
    try:
        from src.infrastructure.workers.celery_app import celery_app
        inspect = celery_app.control.inspect(timeout=4)
        active  = inspect.active()
        ping    = inspect.ping()
        if ping:
            workers = list(ping.keys())
            print(f"  OK Workers activos: {workers}")
            for w, tasks in (active or {}).items():
                print(f"    {w}: {len(tasks)} tarea(s) en curso")
        else:
            print("  FAIL No hay workers Celery corriendo")
            print("    → Inícialo con:  .venv\\Scripts\\celery -A src.infrastructure.celery_app worker -l info -P solo")
    except Exception as e:
        print(f"  FAIL Celery FAIL: {e}")


# ── 6. Verificar migraciones ───────────────────────────────────────────────────

async def check_migrations():
    print("\n=== 6. MIGRACIONES ===")
    async with AsyncSessionFactory() as db:
        try:
            # Verificar columna normalized_cv_url en candidates
            result = await db.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='candidates' AND column_name='normalized_cv_url'"
            ))
            row = result.fetchone()
            if row:
                print("  OK candidates.normalized_cv_url existe")
            else:
                print("  FAIL candidates.normalized_cv_url NO existe — corre: alembic upgrade head")

            # Contar tablas principales
            for tbl in ["users", "hiring_processes", "candidates"]:
                r = await db.execute(text(f"SELECT COUNT(*) FROM {tbl}"))
                count = r.scalar()
                print(f"  OK {tbl}: {count} filas")
        except Exception as e:
            print(f"  FAIL Error schema: {e}")


# ── Main ───────────────────────────────────────────────────────────────────────

async def main():
    await reset_db()
    await ensure_recruiter()
    await check_redis()
    check_r2()
    check_celery()
    await check_migrations()
    print("\nDONE Reset y verificación completados.")
    print("\n>> Para iniciar el backend:")
    print("   Terminal 1: .venv\\Scripts\\uvicorn src.api.main:app --reload --port 8000")
    print("   Terminal 2: .venv\\Scripts\\celery -A src.infrastructure.celery_app worker -l info -P solo")


if __name__ == "__main__":
    asyncio.run(main())
