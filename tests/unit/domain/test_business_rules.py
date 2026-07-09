import pytest
from src.domain.hiring_process.rules import HiringProcessRules
from src.domain.shared.exceptions import BusinessRuleException

def test_rb_005_max_concurrent_calls():
    # active_calls < max_concurrent
    HiringProcessRules.enforce_max_concurrent_calls(3, 4)
    
    # active_calls == max_concurrent
    with pytest.raises(BusinessRuleException):
        HiringProcessRules.enforce_max_concurrent_calls(4, 4)

def test_rb_010_budget_limit():
    HiringProcessRules.require_budget_available(10.0, 100.0)
    
    with pytest.raises(BusinessRuleException):
        HiringProcessRules.require_budget_available(100.0, 100.0)

def test_rb_001_require_jd():
    HiringProcessRules.require_job_description(True)
    
    with pytest.raises(BusinessRuleException):
        HiringProcessRules.require_job_description(False)
