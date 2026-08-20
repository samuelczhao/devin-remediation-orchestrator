from datetime import UTC, datetime

from app.config import Settings
from app.prompt import MAX_ISSUE_CONTEXT_CHARS, build_prompt
from app.schemas import TaskRecord, TaskState


def task_with_body(body: str) -> TaskRecord:
    now = datetime.now(UTC)
    return TaskRecord(
        id="task-1",
        delivery_id="delivery-1",
        repository_id=1_340_946_845,
        repository="samuelczhao/superset",
        issue_id=1,
        issue_number=1,
        issue_title="Export bug\x00",
        issue_body=body,
        actor="samuelczhao",
        state=TaskState.QUEUED,
        created_at=now,
        updated_at=now,
    )


def test_prompt_scopes_authority_and_sanitizes_issue_context() -> None:
    prompt = build_prompt(task_with_body("A" * 15_000 + "\x01"), Settings())
    assert "Work only in samuelczhao/superset" in prompt
    assert "never merge or deploy" in prompt
    assert "\x00" not in prompt
    assert "\x01" not in prompt
    assert "A" * MAX_ISSUE_CONTEXT_CHARS in prompt
    assert "A" * (MAX_ISSUE_CONTEXT_CHARS + 1) not in prompt
