import importlib
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1", reason="Requiere PostgreSQL local"
)


@pytest.mark.parametrize("invalid_first", [False, True])
def test_duplicate_deliveries_do_not_repeat_analysis_or_costs(invalid_first):
    module = importlib.import_module("src.infrastructure.workers.tasks.parse_cv")
    user_id, process_id, candidate_id, cv_id, pc_id = (uuid.uuid4() for _ in range(5))
    task_id = str(uuid.uuid4())
    params = dict(user=user_id, process=process_id, candidate=candidate_id, cv=cv_id, pc=pc_id,
                  email=f"test-{candidate_id}@example.test", task=task_id)
    with module._engine.begin() as conn:
        conn.execute(text("""INSERT INTO users
            (id,name,last_name,email,password_hash,role,status,password_change_required)
            VALUES (:user,'Test','User',:email,'hash','ADMIN','ACTIVE',false)"""), params)
        conn.execute(text("""INSERT INTO hiring_processes
            (id,name,job_title,area,seniority,status,budget_max_usd,recruiter_id)
            VALUES (:process,'Test','Role','Tech','Senior','DRAFT',50,:user)"""), params)
        conn.execute(text("""INSERT INTO candidates (id,name,last_name,email,cv_file_url)
            VALUES (:candidate,'Test','Candidate',:email,'test.pdf')"""), params)
        conn.execute(text("""INSERT INTO candidate_cv_versions (id,candidate_id,original_file_url)
            VALUES (:cv,:candidate,'test.pdf')"""), params)
        conn.execute(text("""INSERT INTO process_candidates
            (id,process_id,candidate_id,cv_version_id,status,cv_task_id,
             match_percentage,whatsapp_consent_status)
            VALUES (:pc,:process,:candidate,:cv,'CV_PROCESSING',:task,0,'PENDING')"""), params)

    client = MagicMock()
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        time.sleep(0.2)
        content = (
            "" if invalid_first and len(calls) == 1
            else '{"full_name":"Test Candidate","email":"test@example.test"}'
        )
        return SimpleNamespace(
            id=f"test-response-{len(calls)}-{pc_id}", usage=None,
            choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(
                content=content, refusal=None,
            ))],
        )

    client.chat.completions.create.side_effect = completion
    try:
        with (
            patch.object(module, "download_file_sync", return_value=b"synthetic"),
            patch.object(
                module, "_prepare_content", return_value=[{"type": "text", "text": "test"}]
            ),
            patch.object(module, "_get_openai", return_value=client),
            patch.object(module, "_get_embedding", side_effect=RuntimeError("sin embedding")),
            patch.object(module, "render_normalized_cv", return_value=b"pdf"),
            patch.object(module, "upload_file_sync"),
            patch("src.application.ai.process_prompt_resolver.get_effective_prompt_sync",
                  return_value=SimpleNamespace(system_prompt_text="test")),
            patch("src.infrastructure.cache.redis_client.get_active_ai_model_sync",
                  return_value="gpt-5.6-luna"),
        ):
            def execute():
                return module.parse_cv.apply(
                    args=(str(candidate_id), str(pc_id), str(process_id)),
                    task_id=task_id, throw=False,
                ).result

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: execute(), range(2)))

        assert len(calls) == (3 if invalid_first else 2)
        assert sum("skipped" in result for result in results) == 1
        with module._engine.connect() as conn:
            row = conn.execute(
                text("SELECT status,cv_task_id FROM process_candidates WHERE id=:pc"), params
            ).one()
            costs = conn.execute(text("SELECT count(*) FROM cost_logs WHERE process_id=:process"),
                                 params).scalar_one()
        assert tuple(row) == ("MATCH_PENDING", None)
        assert costs == (4 if invalid_first else 3)
    finally:
        with module._engine.begin() as conn:
            conn.execute(text("DELETE FROM cost_logs WHERE process_id=:process"), params)
            conn.execute(text("DELETE FROM hiring_processes WHERE id=:process"), params)
            conn.execute(text("DELETE FROM candidates WHERE id=:candidate"), params)
            conn.execute(text("DELETE FROM users WHERE id=:user"), params)
