from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from pydantic import ValidationError

from app.config import Settings
from app.schemas import GitHubIssueEventEnvelope, IssueLabeledPayload
from app.security import verify_signature


@dataclass(frozen=True)
class WebhookDecision:
    delivery_id: str
    payload: IssueLabeledPayload | None
    reason: str


class WebhookError(RuntimeError):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def validate_webhook(
    raw_body: bytes,
    headers: Mapping[str, str],
    settings: Settings,
) -> WebhookDecision:
    if len(raw_body) > settings.max_webhook_bytes:
        raise WebhookError(413, "Payload is too large")
    _verify_hmac(raw_body, headers.get("x-hub-signature-256"), settings)
    delivery_id = _delivery_id(headers.get("x-github-delivery"))
    if headers.get("x-github-event") != "issues":
        return WebhookDecision(delivery_id, None, "ignored_event")
    envelope = _parse_envelope(raw_body)
    if envelope.action != "labeled":
        return WebhookDecision(delivery_id, None, "ignored_action")
    payload = _parse(raw_body)
    reason = _ignored_reason(payload, settings)
    if reason:
        return WebhookDecision(delivery_id, None, reason)
    _verify_trusted_source(payload, settings)
    return WebhookDecision(delivery_id, payload, "accepted")


def _verify_hmac(raw_body: bytes, signature: str | None, settings: Settings) -> None:
    secret = settings.github_webhook_secret.get_secret_value()
    if not verify_signature(raw_body, signature, secret):
        raise WebhookError(401, "Invalid webhook signature")


def _delivery_id(value: str | None) -> str:
    try:
        return str(UUID(value or ""))
    except ValueError as error:
        raise WebhookError(400, "Invalid GitHub delivery ID") from error


def _parse(raw_body: bytes) -> IssueLabeledPayload:
    try:
        return IssueLabeledPayload.model_validate_json(raw_body)
    except ValidationError as error:
        raise WebhookError(400, "Invalid issues webhook payload") from error


def _parse_envelope(raw_body: bytes) -> GitHubIssueEventEnvelope:
    try:
        return GitHubIssueEventEnvelope.model_validate_json(raw_body)
    except ValidationError as error:
        raise WebhookError(400, "Invalid issues webhook envelope") from error


def _ignored_reason(payload: IssueLabeledPayload, settings: Settings) -> str | None:
    if payload.action != "labeled":
        return "ignored_action"
    if payload.label.name != settings.trigger_label:
        return "ignored_label"
    if payload.issue.pull_request is not None:
        return "ignored_pull_request"
    return None


def _verify_trusted_source(payload: IssueLabeledPayload, settings: Settings) -> None:
    repository_matches = (
        payload.repository.id == settings.github_repository_id
        and payload.repository.full_name == settings.github_repository
    )
    actor_matches = (
        payload.sender.id == settings.github_allowed_actor_id
        and payload.sender.login == settings.github_allowed_actor
    )
    if not repository_matches or not actor_matches:
        raise WebhookError(403, "Webhook source is not allowlisted")
