# =============================================================================
# MissionControl - Mail Server Manager
# Copyright (c) 2026 Your Net Tech
# Developed by Jose Rinaldi
# All rights reserved.
# Unauthorized use, reproduction, or distribution is strictly prohibited
# without written permission from Your Net Tech.
# =============================================================================

import asyncio
import os
import logging
from contextlib import asynccontextmanager
from typing import Dict, Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.database import init_db
from app.services.health_service import HealthService

FRONTEND_DIR = getattr(settings, 'FRONTEND_DIR', "/opt/missioncontrol/frontend")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting MissionControl API")
    try:
        await init_db()
        logger.info("Database tables initialized")
    except Exception as e:
        logger.warning(f"Database initialization skipped: {e}")

    health = HealthService()
    stop_event = asyncio.Event()

    async def health_monitor():
        logger.info("Health monitor started (interval: 5 minutes)")
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=300)
            except asyncio.TimeoutError:
                pass
            if stop_event.is_set():
                break
            try:
                report = await health.auto_repair()
                if report["actions_taken"] or report["errors"]:
                    logger.warning(f"Auto-repair: {len(report['actions_taken'])} actions, {len(report['errors'])} errors")
                    if report["actions_taken"]:
                        logger.info(f"Auto-repair actions: {report['actions_taken']}")
                    if report["errors"]:
                        logger.error(f"Auto-repair errors: {report['errors']}")
                else:
                    logger.debug("Health check OK - all services running")
            except Exception as e:
                logger.error(f"Health monitor error: {e}")

    async def metrics_collector():
        from app.core.database import async_session_factory
        from app.models.audit import AuditLog
        import psutil

        logger.info("Metrics collector started (interval: 5 minutes)")
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=300)
            except asyncio.TimeoutError:
                pass
            if stop_event.is_set():
                break
            try:
                cpu = psutil.cpu_percent(interval=0.5)
                mem = psutil.virtual_memory()
                disk = psutil.disk_usage("/")
                net = psutil.net_io_counters()
                details = {
                    "cpu_percent": cpu,
                    "memory_percent": mem.percent,
                    "disk_percent": disk.percent,
                    "network_sent_mb": round(net.bytes_sent / (1024**2), 2),
                    "network_recv_mb": round(net.bytes_recv / (1024**2), 2),
                }
                async with async_session_factory() as session:
                    log = AuditLog(
                        user_id=None,
                        action="system_metric",
                        resource="system",
                        details=details,
                        ip_address=None,
                        status="success",
                    )
                    session.add(log)
                    await session.commit()
                logger.debug(f"Metrics collected: CPU={cpu}% RAM={mem.percent}% Disk={disk.percent}%")
            except Exception as e:
                logger.error(f"Metrics collector error: {e}")

    health_task = asyncio.create_task(health_monitor())
    metrics_task = asyncio.create_task(metrics_collector())
    yield
    stop_event.set()
    health_task.cancel()
    metrics_task.cancel()
    try:
        await health_task
    except asyncio.CancelledError:
        pass
    try:
        await metrics_task
    except asyncio.CancelledError:
        pass
    logger.info("Shutting down MissionControl API")


app = FastAPI(
    title=settings.API_TITLE,
    version=settings.API_VERSION,
    lifespan=lifespan,
)

_default_origins = ["http://localhost"]
_loaded_origins = _default_origins
try:
    if os.path.exists("/opt/missioncontrol/general_settings.json"):
        with open("/opt/missioncontrol/general_settings.json") as _f:
            _gs = __import__("json").load(_f)
        _custom_origins = _gs.get("cors_origins")
        if _custom_origins and isinstance(_custom_origins, list):
            _loaded_origins = _custom_origins
except Exception:
    pass

app.add_middleware(
    CORSMiddleware,
    allow_origins=_loaded_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


@app.get("/", tags=["root"])
async def root() -> Dict[str, Any]:
    return {
        "name": settings.API_TITLE,
        "version": settings.API_VERSION,
        "status": "operational",
    }


from app.api import auth, users, domains, mailboxes, server, services, dns, metrics, roundcube, spam, audit, email_aliases, health, contacts, webmail, email_features

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(domains.router)
app.include_router(mailboxes.router)
app.include_router(server.router)
app.include_router(services.router)
app.include_router(dns.router)
app.include_router(metrics.router)
app.include_router(roundcube.router)
app.include_router(spam.router)
app.include_router(audit.router)
app.include_router(email_aliases.router)
app.include_router(health.router)
app.include_router(contacts.router)
app.include_router(webmail.router)
app.include_router(email_features.router)

# Serve frontend static files (after API routes so explicit routes take priority)
if os.path.isdir(FRONTEND_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIR, "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        if full_path.startswith("api/") or full_path.startswith("docs") or full_path.startswith("openapi.json"):
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        safe_path = os.path.normpath(os.path.join(FRONTEND_DIR, full_path))
        if not safe_path.startswith(os.path.normpath(FRONTEND_DIR)):
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        if os.path.isfile(safe_path):
            return FileResponse(safe_path)
        index_path = os.path.join(FRONTEND_DIR, "index.html")
        if os.path.isfile(index_path):
            return FileResponse(index_path)
        return JSONResponse(status_code=404, content={"detail": "Not found"})

    logger.info(f"Serving frontend from {FRONTEND_DIR}")
else:
    logger.warning(f"Frontend directory not found: {FRONTEND_DIR}")
