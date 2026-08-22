import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from app.schemas import IssueLabeledPayload, TaskMetrics, TaskRecord, TaskState

SCHEMA = """
CREATE TABLE IF NOT EXISTS deliveries (
    delivery_id TEXT PRIMARY KEY,
    received_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    delivery_id TEXT NOT NULL UNIQUE REFERENCES deliveries(delivery_id),
    repository_id INTEGER NOT NULL,
    repository TEXT NOT NULL,
    issue_id INTEGER NOT NULL,
    issue_number INTEGER NOT NULL,
    issue_title TEXT NOT NULL,
    issue_body TEXT NOT NULL,
    actor TEXT NOT NULL,
    state TEXT NOT NULL,
    session_id TEXT UNIQUE,
    session_url TEXT,
    pr_url TEXT,
    pr_state TEXT,
    acus_consumed TEXT NOT NULL DEFAULT '0',
    devin_status TEXT,
    devin_status_detail TEXT,
    structured_output TEXT,
    error_code TEXT,
    error_detail TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE(repository_id, issue_id)
);
CREATE TABLE IF NOT EXISTS task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    previous_state TEXT,
    new_state TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL
);
"""


class TaskStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def register(self, delivery_id: str, payload: IssueLabeledPayload) -> tuple[TaskRecord, bool]:
        now = _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            task = self._find_duplicate(connection, delivery_id, payload)
            if task:
                return task, False
            task_id = str(uuid4())
            connection.execute("INSERT INTO deliveries VALUES (?, ?)", (delivery_id, now))
            connection.execute(
                """INSERT INTO tasks (
                id, delivery_id, repository_id, repository, issue_id, issue_number,
                issue_title, issue_body, actor, state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task_id,
                    delivery_id,
                    payload.repository.id,
                    payload.repository.full_name,
                    payload.issue.id,
                    payload.issue.number,
                    payload.issue.title,
                    payload.issue.body or "",
                    payload.sender.login,
                    TaskState.QUEUED,
                    now,
                    now,
                ),
            )
            self._record_event(connection, task_id, None, TaskState.QUEUED, "webhook accepted")
            return self._get(connection, task_id), True

    def _find_duplicate(
        self,
        connection: sqlite3.Connection,
        delivery_id: str,
        payload: IssueLabeledPayload,
    ) -> TaskRecord | None:
        row = connection.execute(
            """SELECT tasks.* FROM tasks LEFT JOIN deliveries USING (delivery_id)
            WHERE deliveries.delivery_id = ? OR (repository_id = ? AND issue_id = ?)
            LIMIT 1""",
            (delivery_id, payload.repository.id, payload.issue.id),
        ).fetchone()
        return _to_task(row) if row else None

    def claim_queued(self, max_active_sessions: int = 1) -> TaskRecord | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            active_count = connection.execute(
                "SELECT COUNT(*) FROM tasks WHERE state IN (?, ?, ?)",
                (TaskState.CREATING, TaskState.RUNNING, TaskState.NEEDS_ATTENTION),
            ).fetchone()[0]
            if active_count >= max_active_sessions:
                return None
            row = connection.execute(
                "SELECT * FROM tasks WHERE state = ? ORDER BY created_at LIMIT 1",
                (TaskState.QUEUED,),
            ).fetchone()
            if not row:
                return None
            task = _to_task(row)
            self._transition(connection, task, TaskState.CREATING, "claimed by reconciler")
            return self._get(connection, task.id)

    def attach_session(self, task_id: str, session_id: str, session_url: str) -> None:
        with self._connect() as connection:
            task = self._get(connection, task_id)
            connection.execute(
                """UPDATE tasks SET session_id = ?, session_url = ?,
                error_code = NULL, error_detail = NULL WHERE id = ?""",
                (session_id, session_url, task_id),
            )
            self._transition(connection, task, TaskState.RUNNING, "Devin session created")

    def prepare_create_retry(self, task_id: str) -> TaskRecord:
        with self._connect() as connection:
            task = self._get(connection, task_id)
            self._transition(
                connection,
                task,
                TaskState.CREATING,
                "rate-limited session create retry claimed",
            )
            connection.execute(
                "UPDATE tasks SET error_code = NULL, error_detail = NULL WHERE id = ?",
                (task_id,),
            )
            return self._get(connection, task_id)

    def observe_session(
        self,
        task_id: str,
        *,
        state: TaskState,
        status: str,
        status_detail: str | None,
        acus: Decimal,
        pr_url: str | None,
        pr_state: str | None,
        structured_output: dict[str, object] | None,
        error_code: str | None = None,
        error_detail: str | None = None,
    ) -> None:
        completed_at = _now() if state in _terminal_states() else None
        with self._connect() as connection:
            task = self._get(connection, task_id)
            connection.execute(
                """UPDATE tasks SET devin_status = ?, devin_status_detail = ?,
                acus_consumed = ?, pr_url = ?, pr_state = ?, structured_output = ?,
                error_code = ?, error_detail = ?, completed_at = ? WHERE id = ?""",
                (
                    status,
                    status_detail,
                    str(acus),
                    pr_url,
                    pr_state,
                    json.dumps(structured_output) if structured_output else None,
                    error_code,
                    error_detail,
                    completed_at,
                    task_id,
                ),
            )
            self._transition(connection, task, state, status_detail or status)

    def mark_create_unknown(self, task_id: str, detail: str) -> None:
        self.mark_needs_attention(task_id, "session_create_unknown", detail)

    def mark_needs_attention(self, task_id: str, code: str, detail: str) -> None:
        with self._connect() as connection:
            task = self._get(connection, task_id)
            self._transition(connection, task, TaskState.NEEDS_ATTENTION, detail)
            connection.execute(
                "UPDATE tasks SET error_code = ?, error_detail = ? WHERE id = ?",
                (code, detail, task_id),
            )

    def mark_failed(self, task_id: str, code: str, detail: str) -> None:
        with self._connect() as connection:
            task = self._get(connection, task_id)
            self._transition(connection, task, TaskState.FAILED, detail)
            connection.execute(
                """UPDATE tasks SET error_code = ?, error_detail = ?, completed_at = ?
                WHERE id = ?""",
                (code, detail, _now(), task_id),
            )

    def record_error(self, task_id: str, code: str, detail: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """UPDATE tasks SET error_code = ?, error_detail = ?, updated_at = ?
                WHERE id = ?""",
                (code, detail, _now(), task_id),
            )

    def list_active(self) -> list[TaskRecord]:
        active = (TaskState.RUNNING, TaskState.CREATING, TaskState.NEEDS_ATTENTION)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM tasks WHERE state IN (?, ?, ?) ORDER BY created_at", active
            ).fetchall()
        return [_to_task(row) for row in rows]

    def list_tasks(self) -> list[TaskRecord]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM tasks ORDER BY created_at DESC").fetchall()
        return [_to_task(row) for row in rows]

    def get(self, task_id: str) -> TaskRecord | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _to_task(row) if row else None

    def metrics(self) -> TaskMetrics:
        tasks = self.list_tasks()
        counts = {state: sum(task.state == state for task in tasks) for state in TaskState}
        terminal = sum(task.state in _terminal_states() for task in tasks)
        pr_produced = sum(
            task.pr_url is not None and task.state in _terminal_states() for task in tasks
        )
        return TaskMetrics(
            total=len(tasks),
            queued=counts[TaskState.QUEUED],
            active=counts[TaskState.CREATING] + counts[TaskState.RUNNING],
            needs_attention=counts[TaskState.NEEDS_ATTENTION],
            blocked=counts[TaskState.BLOCKED],
            failed=counts[TaskState.FAILED],
            pr_produced=pr_produced,
            terminal=terminal,
            pr_yield=_ratio(pr_produced, terminal),
            total_acus=sum((task.acus_consumed for task in tasks), Decimal("0")),
            median_cycle_seconds=_median_cycle(tasks),
        )

    def _get(self, connection: sqlite3.Connection, task_id: str) -> TaskRecord:
        row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            raise LookupError(f"Task {task_id} does not exist")
        return _to_task(row)

    def _transition(
        self,
        connection: sqlite3.Connection,
        task: TaskRecord,
        state: TaskState,
        detail: str,
    ) -> None:
        now = _now()
        connection.execute(
            "UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", (state, now, task.id)
        )
        if task.state != state:
            self._record_event(connection, task.id, task.state, state, detail)

    def _record_event(
        self,
        connection: sqlite3.Connection,
        task_id: str,
        previous: TaskState | None,
        new: TaskState,
        detail: str,
    ) -> None:
        connection.execute(
            """INSERT INTO task_events
            (task_id, previous_state, new_state, detail, created_at)
            VALUES (?, ?, ?, ?, ?)""",
            (task_id, previous, new, detail, _now()),
        )


def _to_task(row: sqlite3.Row) -> TaskRecord:
    values = dict(row)
    values["structured_output"] = (
        json.loads(values["structured_output"]) if values["structured_output"] else None
    )
    return TaskRecord.model_validate(values)


def _terminal_states() -> set[TaskState]:
    return {
        TaskState.COMPLETED_WITH_PR,
        TaskState.COMPLETED_WITHOUT_PR,
        TaskState.BLOCKED,
        TaskState.FAILED,
    }


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _ratio(numerator: int, denominator: int) -> Decimal:
    if not denominator:
        return Decimal("0")
    return (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("0.01"))


def _median_cycle(tasks: list[TaskRecord]) -> Decimal | None:
    durations = sorted(
        Decimal(str((task.completed_at - task.created_at).total_seconds()))
        for task in tasks
        if task.completed_at
    )
    if not durations:
        return None
    middle = len(durations) // 2
    if len(durations) % 2:
        return durations[middle]
    return (durations[middle - 1] + durations[middle]) / Decimal("2")
