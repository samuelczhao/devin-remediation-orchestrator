from app.schemas import IssueLabeledPayload


def issue_payload_data(
    *,
    issue_id: int = 2001,
    issue_number: int = 12,
    repository_id: int = 1_340_946_845,
    repository: str = "samuelczhao/superset",
    label: str = "devin:ready",
    actor_id: int = 30_126_000,
    actor: str = "samuelczhao",
    action: str = "labeled",
    pull_request: dict[str, str] | None = None,
    title: str = "Consolidate duplicated export normalization",
) -> dict[str, object]:
    return {
        "action": action,
        "issue": {
            "id": issue_id,
            "number": issue_number,
            "title": title,
            "body": "Refactor the duplicated logic and add focused tests.",
            "pull_request": pull_request,
        },
        "label": {"name": label},
        "repository": {"id": repository_id, "full_name": repository},
        "sender": {"id": actor_id, "login": actor},
    }


def issue_payload(
    *,
    issue_id: int = 2001,
    issue_number: int = 12,
    repository_id: int = 1001,
) -> IssueLabeledPayload:
    return IssueLabeledPayload.model_validate(
        issue_payload_data(
            issue_id=issue_id,
            issue_number=issue_number,
            repository_id=repository_id,
        )
    )
