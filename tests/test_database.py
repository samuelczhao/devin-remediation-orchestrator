from pathlib import Path

from app.database import TaskStore
from app.schemas import TaskState
from tests.factories import issue_payload


def create_store(path: Path) -> TaskStore:
    store = TaskStore(path)
    store.initialize()
    return store


def test_same_delivery_creates_one_task(tmp_path: Path) -> None:
    store = create_store(tmp_path / "tasks.db")
    first, first_created = store.register("delivery-1", issue_payload())
    second, second_created = store.register("delivery-1", issue_payload())
    assert first_created is True
    assert second_created is False
    assert first.id == second.id
    assert len(store.list_tasks()) == 1


def test_relabeling_same_issue_does_not_spend_again(tmp_path: Path) -> None:
    store = create_store(tmp_path / "tasks.db")
    first, _ = store.register("delivery-1", issue_payload())
    second, created = store.register("delivery-2", issue_payload())
    assert created is False
    assert first.id == second.id


def test_claim_is_atomic_and_transitions_state(tmp_path: Path) -> None:
    store = create_store(tmp_path / "tasks.db")
    store.register("delivery-1", issue_payload())
    claimed = store.claim_queued()
    assert claimed is not None
    assert claimed.state == TaskState.CREATING
    assert store.claim_queued() is None


def test_needs_attention_session_is_reconciled_after_restart(tmp_path: Path) -> None:
    store = create_store(tmp_path / "tasks.db")
    task, _ = store.register("delivery-1", issue_payload())
    claimed = store.claim_queued()
    assert claimed is not None
    store.attach_session(task.id, "devin-test", "https://app.devin.ai/sessions/devin-test")
    store.observe_session(
        task.id,
        state=TaskState.NEEDS_ATTENTION,
        status="running",
        status_detail="waiting_for_approval",
        acus=claimed.acus_consumed,
        pr_url=None,
        pr_state=None,
        structured_output=None,
    )
    assert [active.id for active in store.list_active()] == [task.id]


def test_claim_respects_global_active_session_limit(tmp_path: Path) -> None:
    store = create_store(tmp_path / "tasks.db")
    first, _ = store.register("delivery-1", issue_payload(issue_id=1, issue_number=1))
    store.register("delivery-2", issue_payload(issue_id=2, issue_number=2))
    assert store.claim_queued(max_active_sessions=1) is not None
    store.attach_session(first.id, "devin-1", "https://app.devin.ai/sessions/devin-1")
    assert store.claim_queued(max_active_sessions=1) is None


def test_attaching_recovered_session_clears_ambiguous_error(tmp_path: Path) -> None:
    store = create_store(tmp_path / "tasks.db")
    task, _ = store.register("delivery-1", issue_payload())
    assert store.claim_queued() is not None
    store.mark_create_unknown(task.id, "outcome unknown")
    store.attach_session(task.id, "devin-1", "https://app.devin.ai/sessions/devin-1")
    recovered = store.get(task.id)
    assert recovered is not None
    assert recovered.error_code is None
    assert recovered.error_detail is None
