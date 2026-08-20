from app.schemas import IssueLabeledPayload


def issue_payload(
    *,
    issue_id: int = 2001,
    issue_number: int = 12,
    repository_id: int = 1001,
) -> IssueLabeledPayload:
    return IssueLabeledPayload.model_validate(
        {
            "action": "labeled",
            "issue": {
                "id": issue_id,
                "number": issue_number,
                "title": "Consolidate duplicated export normalization",
                "body": "Refactor the duplicated logic and add focused tests.",
            },
            "label": {"name": "devin:ready"},
            "repository": {
                "id": repository_id,
                "full_name": "samuelczhao/superset",
            },
            "sender": {"id": 30_126_000, "login": "samuelczhao"},
        }
    )
