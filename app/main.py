import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
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

    app = FastAPI(title="Devin Remediation Control Plane", lifespan=lifespan)
    app.state.store = store
    app.state.orchestrator = orchestrator
    templates = Jinja2Templates(directory=APP_ROOT / "templates")
    app.mount("/static", StaticFiles(directory=APP_ROOT / "static"), name="static")

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
        data["worker_last_successful_run"] = orchestrator.last_successful_run
        data["worker_last_error"] = orchestrator.last_error
        return JSONResponse(jsonable_encoder(data))

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready() -> JSONResponse:
        ready_now = orchestrator.last_successful_run is not None
        return JSONResponse(
            {
                "status": "ready" if ready_now else "starting",
                "mode": config.app_mode,
            },
            status_code=200 if ready_now else 503,
        )

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request) -> Response:
        task_views = [
            {**task.model_dump(), "issue_url": canonical_issue_url(config, task.issue_number)}
            for task in store.list_tasks()
        ]
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "mode": config.app_mode,
                "metrics": store.metrics(),
                "tasks": task_views,
                "worker_last_run": orchestrator.last_successful_run,
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


app = create_app()
