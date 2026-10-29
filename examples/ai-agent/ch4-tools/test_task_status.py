import pytest
from jsonschema import ValidationError
from task_status import Principal, get_task_status

ALICE = Principal(frozenset({"task-42"}))


@pytest.mark.parametrize("arguments", [
    {},
    {"task_id": 42},
    {"task_id": "task-42", "detail": "debug"},
    {"task_id": "task-42", "log_limit": 51},
    {"task_id": "task-42", "log_limit": -1},
    {"task_id": "task-42", "log_limit": True},
    {"task_id": "task-42", "principal": "administrator"},
])
def test_invalid_input(arguments):
    with pytest.raises(ValidationError):
        get_task_status(arguments, ALICE)


def test_valid_input_still_requires_authorization():
    with pytest.raises(PermissionError):
        get_task_status({"task_id": "task-99"}, ALICE)


def test_authorized_input():
    assert get_task_status({"task_id": "task-42", "log_limit": 0}, ALICE) == {
        "task_id": "task-42", "status": "RUNNING", "detail": "summary", "log_limit": 0,
    }
