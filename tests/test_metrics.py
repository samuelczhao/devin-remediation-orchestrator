from decimal import Decimal
from pathlib import Path

from app.database import TaskStore
from app.schemas import TaskState
from tests.factories import issue_payload


def test_metrics_distinguish_pr_output_from_failure(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    store.initialize()
    first, _ = store.register("delivery-1", issue_payload(issue_id=1, issue_number=1))
    second, _ = store.register("delivery-2", issue_payload(issue_id=2, issue_number=2))
    store.observe_session(
        first.id,
        state=TaskState.COMPLETED_WITH_PR,
        status="exit",
        status_detail="finished",
        acus=Decimal("1.25"),
        pr_url="https://github.com/samuelczhao/superset/pull/1",
        pr_state="open",
        structured_output={"result": "pr_opened"},
    )
    store.mark_failed(second.id, "test_failure", "failed")
    metrics = store.metrics()
    assert metrics.pr_produced == 1
    assert metrics.failed == 1
    assert metrics.pr_yield == Decimal("0.50")
    assert metrics.total_acus == Decimal("1.25")
