import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.ai.prompts import JD_ENHANCEMENT_SYSTEM_PROMPT
from src.infrastructure.cache.redis_client import (
    get_active_ai_model_sync,
    get_active_ai_prompt_sync,
)
from src.infrastructure.db.models import CostLog
from src.infrastructure.workers.tasks.parse_cv import _get_openai


class EnhanceJDUseCase:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def execute(self, draft_text: str, user_id: uuid.UUID) -> str:
        # Puesto que las operaciones de Redis pueden ser síncronas/bloqueantes en este módulo
        # usaremos asyncio.to_thread para no bloquear el event loop principal de FastAPI.
        import asyncio
        
        def fetch_config():
            # Esta operación usa la sesión DB sincrónica o pasa un engine sincrónico
            # Dado que get_active_ai_prompt_sync necesita una sesión síncrona
            from src.infrastructure.workers.celery_app import _SyncSession
            with _SyncSession() as sync_db:
                sys_prompt = get_active_ai_prompt_sync(sync_db, "JD_ENHANCEMENT", JD_ENHANCEMENT_SYSTEM_PROMPT)
                model = get_active_ai_model_sync(sync_db, "OPENAI", "gpt-4o")
                return sys_prompt, model

        sys_prompt, model = await asyncio.to_thread(fetch_config)

        client = _get_openai()
        
        def call_llm():
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": f"Borrador original:\n{draft_text}"}
                ],
                temperature=0.7,
            )
            return response
            
        response = await asyncio.to_thread(call_llm)
        
        enhanced_text = response.choices[0].message.content or ""
        
        # Registrar el costo
        prompt_tokens = response.usage.prompt_tokens if getattr(response, 'usage', None) else 0
        completion_tokens = response.usage.completion_tokens if getattr(response, 'usage', None) else 0
        cost = (prompt_tokens * 0.005 / 1000) + (completion_tokens * 0.015 / 1000)
        
        cost_log = CostLog(
            process_id=None,
            action="JD_ENHANCEMENT",
            provider="OPENAI",
            estimated_cost=cost,
            details={"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "user_id": str(user_id)}
        )
        self.db.add(cost_log)
        await self.db.commit()

        return enhanced_text
