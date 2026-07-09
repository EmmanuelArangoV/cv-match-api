import re

with open('src/infrastructure/workers/tasks/profiling.py', 'r', encoding='utf-8') as f:
    content = f.read()

target_prof = '''            result_data = json.loads(response.choices[0].message.content or "{}")

            answers = result_data.get("answers", [])'''

replacement_prof = '''            result_data = json.loads(response.choices[0].message.content or "{}")

            from src.infrastructure.db.models import CostLog
            prompt_tokens = response.usage.prompt_tokens if getattr(response, 'usage', None) else 0
            completion_tokens = response.usage.completion_tokens if getattr(response, 'usage', None) else 0
            cost = (prompt_tokens * 0.005 / 1000) + (completion_tokens * 0.015 / 1000)
            cost_log = CostLog(
                process_id=process.id,
                process_candidate_id=profiling_run.process_candidate_id,
                action="PROFILING_EVALUATION",
                provider="OPENAI",
                estimated_cost=cost,
                details={"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}
            )
            db.add(cost_log)

            answers = result_data.get("answers", [])'''

if target_prof in content:
    content = content.replace(target_prof, replacement_prof)
    with open('src/infrastructure/workers/tasks/profiling.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Replaced profiling cost")
else:
    print("Target not found for profiling")
