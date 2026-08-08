import sys
import os
import uuid
from datetime import datetime
from sqlalchemy import create_engine, select, delete
from sqlalchemy.orm import sessionmaker

# Add current directory to path
sys.path.insert(0, os.path.abspath("."))

from src.config import settings
from src.infrastructure.db.models import (
    Candidate,
    ProcessCandidate,
    ProfilingRun,
    ProfilingAnswer,
    HiringProcess,
    CandidateStatus,
    WhatsAppConsentStatus,
    ProfilingRunStatus,
)
from src.infrastructure.workers.tasks.whatsapp import send_whatsapp_consent

def reset_candidate():
    engine = create_engine(settings.database_url_sync)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        # Search candidate by phone digits
        all_c = db.execute(select(Candidate)).scalars().all()
        candidates = [c for c in all_c if c.phone and "3185926525" in "".join(filter(str.isdigit, c.phone))]
            
        print(f"Found {len(candidates)} candidate(s) for phone +573185926525")
        
        for candidate in candidates:
            print(f"Candidate: {candidate.name} {candidate.last_name} ({candidate.id}), phone: {candidate.phone}")
            pcs = db.execute(
                select(ProcessCandidate).where(ProcessCandidate.candidate_id == candidate.id)
            ).scalars().all()
            
            for pc in pcs:
                print(f"  Resetting ProcessCandidate: {pc.id}")
                
                # Get all ProfilingRuns for this pc
                runs = db.execute(
                    select(ProfilingRun).where(ProfilingRun.process_candidate_id == pc.id)
                ).scalars().all()
                
                run_ids = [r.id for r in runs]
                if run_ids:
                    # Delete ProfilingAnswers
                    ans_deleted = db.execute(
                        delete(ProfilingAnswer).where(ProfilingAnswer.profiling_run_id.in_(run_ids))
                    )
                    print(f"    Deleted {ans_deleted.rowcount} ProfilingAnswer(s)")
                    
                    # Delete ProfilingRuns
                    runs_deleted = db.execute(
                        delete(ProfilingRun).where(ProfilingRun.id.in_(run_ids))
                    )
                    print(f"    Deleted {runs_deleted.rowcount} ProfilingRun(s)")
                
                # Reset ProcessCandidate fields
                pc.status = CandidateStatus.MATCHED
                pc.whatsapp_consent_status = WhatsAppConsentStatus.PENDING
                pc.whatsapp_sent_at = None
                pc.whatsapp_responded_at = None
                pc.availability_preference = None
                pc.whatsapp_conversation = None
                
                # Fetch question set ID from HiringProcess
                hp = db.get(HiringProcess, pc.process_id)
                q_set_id = hp.question_set_id if hp else None
                
                # Create fresh ProfilingRun in PENDING status
                new_run = ProfilingRun(
                    id=uuid.uuid4(),
                    process_candidate_id=pc.id,
                    question_set_id=q_set_id,
                    status=ProfilingRunStatus.PENDING,
                )
                db.add(new_run)
                db.commit()
                db.refresh(new_run)
                print(f"  Created new ProfilingRun: {new_run.id} in PENDING status")
                
                # Execute send_whatsapp_consent
                print(f"  Executing send_whatsapp_consent for run {new_run.id}...")
                task_res = send_whatsapp_consent.apply(args=[str(new_run.id)])
                print(f"  WhatsApp task output: {task_res.result}")
                
                task_async = send_whatsapp_consent.delay(str(new_run.id))
                print(f"  Enqueued task_id to Celery: {task_async.id}")

if __name__ == "__main__":
    reset_candidate()
