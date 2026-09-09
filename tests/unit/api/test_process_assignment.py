import uuid

import pytest

from src.api.v1.processes import _can_assign_process_to_user
from src.infrastructure.db.models import User, UserRole, UserStatus


def _user(*, role: UserRole, status: UserStatus = UserStatus.ACTIVE) -> User:
    user_id = uuid.uuid4()
    return User(
        id=user_id,
        name="QA",
        last_name=role.value,
        email=f"{user_id}@example.test",
        role=role.value,
        status=status.value,
    )


@pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.TA_LEADER])
def test_active_recruiter_can_be_assigned_by_authorized_roles(role: UserRole) -> None:
    assert _can_assign_process_to_user(_user(role=UserRole.RECRUITER), _user(role=role))


def test_ta_leader_can_assign_process_to_self() -> None:
    ta_leader = _user(role=UserRole.TA_LEADER)

    assert _can_assign_process_to_user(ta_leader, ta_leader)


def test_ta_leader_cannot_assign_process_to_another_ta_leader() -> None:
    assert not _can_assign_process_to_user(
        _user(role=UserRole.TA_LEADER),
        _user(role=UserRole.TA_LEADER),
    )


def test_inactive_recruiter_cannot_be_assigned() -> None:
    assert not _can_assign_process_to_user(
        _user(role=UserRole.RECRUITER, status=UserStatus.SUSPENDED),
        _user(role=UserRole.ADMIN),
    )
