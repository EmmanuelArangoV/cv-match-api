import re

with open('src/application/cv/use_cases.py', 'r', encoding='utf-8') as f:
    content = f.read()

target = '''        if not HiringProcessStateMachine.can_upload_cvs(ProcessStatus(process.status)):
            raise BusinessRuleException(
                f"El proceso en estado {process.status} no permite carga de CVs."
            )'''

replacement = '''        if not HiringProcessStateMachine.can_upload_cvs(ProcessStatus(process.status)):
            raise BusinessRuleException(
                f"El proceso en estado {process.status} no permite carga de CVs."
            )

        # RB-010: Check budget
        from sqlalchemy import select, func
        from src.infrastructure.db.models import CostLog
        cost_query = select(func.sum(CostLog.estimated_cost)).where(CostLog.process_id == process_id)
        cost_result = await self.db.execute(cost_query)
        total_cost = cost_result.scalar() or 0.0
        HiringProcessRules.require_budget_available(total_cost, float(process.budget_max_usd))'''

if target in content:
    content = content.replace(target, replacement)
    with open('src/application/cv/use_cases.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Replaced budget check in CV use cases")
else:
    print("Target not found")
