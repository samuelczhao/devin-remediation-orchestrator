import asyncio
import base64
import binascii
import contextlib
import hmac
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import Settings, get_settings
from app.database import TaskStore
from app.devin_client import DevinClient, FakeDevinClient, LiveDevinClient
from app.github_webhook import WebhookError, validate_webhook
from app.orchestrator import Orchestrator
from app.prompt import canonical_issue_url

logger = logging.getLogger(__name__)
APP_ROOT = Path(__file__).parent


def create_app(
    settings: Settings | None = None,
    client: DevinClient | None = None,
) -> FastAPI:
    config = settings or get_settings()
    store = TaskStore(config.database_path)
    devin = client or _client(config)
    orchestrator = Orchestrator(store, devin, config)
    stop = asyncio.Event()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        store.initialize()
        worker = asyncio.create_task(_reconciliation_loop(orchestrator, config, stop))
        yield
        stop.set()
        await worker
        await devin.aclose()

    app = FastAPI(
        title="Devin Remediation Control Plane",
        lifespan=lifespan,
        docs_url=None if config.app_mode == "live" else "/docs",
        redoc_url=None if config.app_mode == "live" else "/redoc",
        openapi_url=None if config.app_mode == "live" else "/openapi.json",
    )
    app.state.store = store
    app.state.orchestrator = orchestrator
    templates = Jinja2Templates(directory=APP_ROOT / "templates")
    app.mount("/static", StaticFiles(directory=APP_ROOT / "static"), name="static")

    @app.middleware("http")
    async def secure_operator_routes(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if _operator_route_requires_auth(request.url.path, config) and not _valid_operator_auth(
            request.headers.get("authorization"), config
        ):
            return Response(
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="control"'},
            )
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path == "/" or request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/webhooks/github")
    async def github_webhook(request: Request) -> JSONResponse:
        _check_content_length(request, config)
        raw_body = await _read_limited_body(request, config.max_webhook_bytes)
        try:
            decision = validate_webhook(raw_body, request.headers, config)
        except WebhookError as error:
            raise HTTPException(error.status_code, error.detail) from error
        if not decision.payload:
            return JSONResponse({"accepted": False, "reason": decision.reason}, status_code=202)
        task, created = store.register(decision.delivery_id, decision.payload)
        _log("webhook_accepted", task_id=task.id, issue_number=task.issue_number, created=created)
        return JSONResponse(
            {"accepted": True, "created": created, "task_id": task.id}, status_code=202
        )

    @app.get("/api/tasks")
    async def tasks() -> JSONResponse:
        return JSONResponse(jsonable_encoder(store.list_tasks()))

    @app.get("/api/metrics")
    async def metrics() -> JSONResponse:
        data = store.metrics().model_dump()
        data["worker_last_run_at"] = orchestrator.last_run_at
        data["worker_last_successful_run"] = orchestrator.last_successful_run
        data["worker_last_error"] = orchestrator.last_error
        return JSONResponse(jsonable_encoder(data))

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready() -> JSONResponse:
        ready_now = _worker_is_ready(orchestrator, config)
        return JSONResponse(
            {
                "status": "ready" if ready_now else "starting",
                "mode": config.app_mode,
            },
            status_code=200 if ready_now else 503,
        )

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request) -> Response:
        workflow_metrics = store.metrics()
        task_views = [
            {
                **task.model_dump(),
                "issue_url": canonical_issue_url(config, task.issue_number),
                "state_label": _state_label(task.state),
                "test_summary": _test_summary(task.structured_output),
                "updated_display": _format_timestamp(task.updated_at),
            }
            for task in store.list_tasks()
        ]
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "mode": config.app_mode,
                "metrics": workflow_metrics,
                "median_cycle": _format_duration(workflow_metrics.median_cycle_seconds),
                "tasks": task_views,
                "worker_last_error": orchestrator.last_error,
                "worker_last_attempt": _format_timestamp(orchestrator.last_run_at),
                "worker_last_run": _format_timestamp(orchestrator.last_successful_run),
            },
        )

    return app


async def _reconciliation_loop(
    orchestrator: Orchestrator,
    settings: Settings,
    stop: asyncio.Event,
) -> None:
    while not stop.is_set():
        await orchestrator.run_once()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=settings.poll_interval_seconds)


def _client(settings: Settings) -> DevinClient:
    if settings.app_mode == "live":
        return LiveDevinClient(settings)
    return FakeDevinClient(settings.github_repository)


def _check_content_length(request: Request, settings: Settings) -> None:
    value = request.headers.get("content-length")
    if value and value.isdigit() and int(value) > settings.max_webhook_bytes:
        raise HTTPException(413, "Payload is too large")


async def _read_limited_body(request: Request, limit: int) -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise HTTPException(413, "Payload is too large")
    return bytes(body)


def _log(event: str, **fields: object) -> None:
    logger.info(json.dumps({"event": event, **fields}, sort_keys=True, default=str))


def _operator_route_requires_auth(path: str, settings: Settings) -> bool:
    return settings.app_mode == "live" and (path == "/" or path.startswith("/api/"))


def _valid_operator_auth(value: str | None, settings: Settings) -> bool:
    if not value or not settings.control_plane_password:
        return False
    scheme, separator, encoded = value.partition(" ")
    if not separator or scheme.casefold() != "basic":
        return False
    try:
        decoded = base64.b64decode(encoded, validate=True).decode()
    except (binascii.Error, UnicodeDecodeError):
        return False
    username, separator, password = decoded.partition(":")
    if not separator:
        return False
    username_matches = hmac.compare_digest(username, settings.control_plane_username)
    password_matches = hmac.compare_digest(
        password,
        settings.control_plane_password.get_secret_value(),
    )
    return username_matches and password_matches


def _worker_is_ready(orchestrator: Orchestrator, settings: Settings) -> bool:
    if not orchestrator.last_run_at or orchestrator.last_error:
        return False
    age = (datetime.now(UTC) - orchestrator.last_run_at).total_seconds()
    return age <= settings.worker_stale_after_seconds


def _state_label(state: object) -> str:
    labels = {
        "completed_with_pr": "PR produced",
        "completed_without_pr": "No change needed",
        "needs_attention": "Needs attention",
    }
    return labels.get(str(state), str(state).replace("_", " ").title())


def _test_summary(output: dict[str, object] | None) -> str:
    tests = output.get("tests") if output else None
    if not isinstance(tests, list) or not tests:
        return "No Devin-reported tests"
    counts = {"passed": 0, "failed": 0, "not_run": 0}
    for test in tests:
        if isinstance(test, dict) and test.get("outcome") in counts:
            counts[str(test["outcome"])] += 1
    return f"{counts['passed']} passed · {counts['failed']} failed · {counts['not_run']} not run"


def _format_timestamp(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S UTC") if value else "starting"


def _format_duration(value: object) -> str:
    return f"{value:.1f}s" if value is not None else "—"


app = create_app()
