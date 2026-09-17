from harnesslab.models import TaskCategory, TaskDefinition
from harnesslab.validators import evaluate_task


def _task() -> TaskDefinition:
    return TaskDefinition(
        id="test.answer",
        category=TaskCategory.STRUCTURED_OUTPUT,
        instruction="Return the answer.",
        input={},
        expected={"answer": 42},
        validators=[{"kind": "exact_match"}],
    )


def test_exact_match_accepts_identical_output() -> None:
    result = evaluate_task(_task(), {"answer": 42})

    assert result.passed is True
    assert result.score == 1.0


def test_agent_stopping_is_not_task_success() -> None:
    result = evaluate_task(_task(), {"answer": 41})

    assert result.passed is False
    assert result.score == 0.0
    assert result.checks[0].evidence["actual"] == {"answer": 41}
