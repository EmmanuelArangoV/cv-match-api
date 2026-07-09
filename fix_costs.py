import re

with open('src/infrastructure/workers/tasks/whatsapp.py', 'r', encoding='utf-8') as f:
    content = f.read()

target = '''            pc.whatsapp_sent_at = datetime.now(UTC)
            db.commit()'''

replacement = '''            pc.whatsapp_sent_at = datetime.now(UTC)
            
            from src.infrastructure.db.models import CostLog
            cost_log = CostLog(
                process_id=process.id,
                process_candidate_id=pc.id,
                action="WHATSAPP_CONSENT",
                provider="META",
                estimated_cost=0.08, # aprox cost per template
            )
            db.add(cost_log)
            db.commit()'''

if target in content:
    content = content.replace(target, replacement)
    with open('src/infrastructure/workers/tasks/whatsapp.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Replaced whatsapp cost")

with open('src/infrastructure/workers/tasks/profiling.py', 'r', encoding='utf-8') as f:
    content = f.read()

target_prof = '''            result_data = json.loads(response.choices[0].message.content or "{}")

            # 4. Parsed Answers'''

replacement_prof = '''            result_data = json.loads(response.choices[0].message.content or "{}")

            from src.infrastructure.db.models import CostLog
            prompt_tokens = response.usage.prompt_tokens if response.usage else 0
            completion_tokens = response.usage.completion_tokens if response.usage else 0
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

            # 4. Parsed Answers'''

if target_prof in content:
    content = content.replace(target_prof, replacement_prof)
    with open('src/infrastructure/workers/tasks/profiling.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Replaced profiling cost")
else:
    print("Target not found for profiling")
