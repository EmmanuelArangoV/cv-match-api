import pytest
import uuid
from src.domain.hiring_process.state_machine import HiringProcessStateMachine
from src.infrastructure.db.models import ProcessStatus
from src.domain.shared.exceptions import BusinessRuleException
from src.infrastructure.db.models import HiringProcess

def test_valid_transitions():
    process = HiringProcess(status=ProcessStatus.DRAFT.value)
    # The current code in update_process_status does:
    # HiringProcessStateMachine.transition(ProcessStatus(process.status), body.status)
    res = HiringProcessStateMachine.transition(ProcessStatus(process.status), ProcessStatus.CVS_UPLOADED)
    assert res == ProcessStatus.CVS_UPLOADED

def test_invalid_transition():
    process = HiringProcess(status=ProcessStatus.DRAFT.value)
    with pytest.raises(BusinessRuleException):
        HiringProcessStateMachine.transition(ProcessStatus(process.status), ProcessStatus.MATCH_DONE)

def test_closed_process_transition():
    process = HiringProcess(status=ProcessStatus.CLOSED.value)
    with pytest.raises(BusinessRuleException):
        HiringProcessStateMachine.transition(ProcessStatus(process.status), ProcessStatus.CVS_UPLOADED)
