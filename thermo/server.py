"""FastAPI app: static UI, REST endpoints and the SSE stream."""
from __future__ import annotations

import asyncio
import json
import queue
import secrets
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StrictBool, model_validator

from thermo import settings as settings_mod
from thermo.alerts import AlertEngine, Threshold
from thermo.buffers import UsageBuffers
from thermo.cooling import Cooling, SmartCooling, SmartRules
from thermo.model import finite
from thermo.sampler import Sampler
from thermo.settings import Settings
from thermo.store import Store

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
RANGES = {"1h": 3600, "6h": 6 * 3600, "24h": 24 * 3600}
HEARTBEAT_S = 15
Temp = Field(ge=30, le=110)


@dataclass
class AppState:
    sampler: Sampler
    store: Store
    buffers: UsageBuffers
    cooling: Cooling
    smart: SmartCooling
    alerts: AlertEngine
    settings: Settings
    settings_path: Path
    token: str
    is_admin: bool
    lhm_error: str | None
    machine: dict
    request_quit: Callable[[], None]


class SettingsIn(BaseModel):
    theme: Literal["system", "light", "dark"] | None = None
    cpu_limit_c: float | None = Field(default=None, ge=30, le=110)
    port: int | None = Field(default=None, ge=1024, le=65535)


class ThresholdIn(BaseModel):
    key: str = Field(min_length=1, max_length=200)
    enabled: StrictBool
    limit_c: float = Temp


class SmartIn(BaseModel):
    enabled: StrictBool
    up_c: float = Temp
    up_s: float = Field(ge=5, le=3600)
    down_c: float = Temp
    down_s: float = Field(ge=5, le=3600)

    @model_validator(mode="after")
    def _order(self):
        if self.down_c >= self.up_c:
            raise ValueError("down_c must be lower than up_c")
        return self


class ModeIn(BaseModel):
    mode: Literal["quiet", "balanced", "performance"]


def create_app(state: AppState, allowed_hosts: list[str] | None = None) -> FastAPI:
    app = FastAPI(title="Thermo", docs_url=None, redoc_url=None, openapi_url=None)
    # Only answer to localhost names, so a DNS-rebinding page can't read the token from "/".
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts or ["127.0.0.1", "localhost"])
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    def require_token(x_thermo_token: str | None = Header(default=None)) -> None:
        if not x_thermo_token or not secrets.compare_digest(x_thermo_token, state.token):
            raise HTTPException(403, "Missing or wrong X-Thermo-Token")

    def now() -> float:
        return state.sampler.latest.ts if state.sampler.latest else time.time()

    def save_settings() -> None:
        settings_mod.save(state.settings_path, state.settings)

    # --- page + stream --------------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    def index():
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(html.replace("{{TOKEN}}", state.token), headers={"Cache-Control": "no-store"})

    @app.get("/api/stream")
    async def stream(request: Request):
        q = state.sampler.subscribe()

        async def events():
            try:
                if state.sampler.latest:
                    yield _sse(state.sampler.latest.to_json())
                idle = 0.0
                while not await request.is_disconnected():
                    try:
                        snap = await asyncio.to_thread(q.get, True, 1.0)
                    except queue.Empty:
                        idle += 1.0
                        if idle >= HEARTBEAT_S:
                            idle = 0.0
                            yield ": ping\n\n"
                        continue
                    idle = 0.0
                    yield _sse(snap.to_json())
            finally:
                state.sampler.unsubscribe(q)

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    # --- read endpoints -------------------------------------------------------
    @app.get("/api/status")
    def status():
        latest = state.sampler.latest
        return {
            "is_admin": state.is_admin,
            "lhm_error": state.lhm_error,
            "store_error": state.sampler.store_error,
            "sensor_count": len(latest.readings) if latest else 0,
            "uptime_s": time.time() - state.sampler.started_at,
            "samples_saved": state.store.sample_count(),
            "paused": state.sampler.paused,
            "machine": state.machine,
            "cooling_available": state.cooling.available(),
        }

    @app.get("/api/sensors")
    def sensors():
        latest = state.sampler.latest
        rows = []
        for r in latest.readings if latest else []:
            lo, hi = state.sampler.minmax.get(r.id, (None, None))
            rows.append({**asdict(r), "value": finite(r.value), "min": lo, "max": hi})
        return rows

    @app.get("/api/usage")
    def usage(device: str, range: int = 60):  # noqa: A002 - query name from the spec
        if range not in (60, 300, 3600):
            raise HTTPException(422, "range must be 60, 300 or 3600")
        return state.buffers.series(device, range, now())

    @app.get("/api/history")
    def history(range: Literal["1h", "6h", "24h"] = "1h", sensors: str = "cpu,gpu0,gpu1,ssd"):  # noqa: A002
        ids = [s for s in sensors.split(",") if s][:20]
        return state.store.series(ids, since=now() - RANGES[range])

    @app.get("/api/history/hourly")
    def hourly(sensor: str = "cpu", hours: int = Query(7, ge=1, le=24)):
        return state.store.hourly(sensor, hours, now())

    @app.get("/api/history.csv")
    def history_csv():
        return Response(state.store.export_csv(since=now() - RANGES["24h"]), media_type="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="thermo-history.csv"'})

    @app.get("/api/settings")
    def get_settings():
        return asdict(state.settings)

    @app.get("/api/alerts/thresholds")
    def get_thresholds():
        return [asdict(t) for t in state.alerts.thresholds]

    @app.get("/api/alerts/log")
    def alert_log(limit: int = Query(10, ge=1, le=200)):
        return state.store.alerts(limit)

    @app.get("/api/cooling/mode")
    def get_mode():
        return {"mode": state.cooling.mode(), "available": state.cooling.available()}

    @app.get("/api/cooling/smart")
    def get_smart():
        return asdict(state.smart.rules)

    @app.get("/api/cooling/events")
    def cooling_events(since: float = 0):
        return state.store.cooling_events(since)

    # --- write endpoints (token required) ------------------------------------
    @app.put("/api/settings", dependencies=[Depends(require_token)])
    def put_settings(body: SettingsIn):
        for k, v in body.model_dump(exclude_none=True).items():
            setattr(state.settings, k, v)
        save_settings()
        return asdict(state.settings)

    @app.put("/api/alerts/thresholds", dependencies=[Depends(require_token)])
    def put_thresholds(body: list[ThresholdIn]):
        thresholds = [Threshold(t.key, t.enabled, t.limit_c) for t in body]
        state.alerts.set_thresholds(thresholds)
        state.settings.thresholds = thresholds
        save_settings()
        return [asdict(t) for t in thresholds]

    @app.put("/api/cooling/mode", dependencies=[Depends(require_token)])
    def put_mode(body: ModeIn):
        if not state.cooling.available():
            return JSONResponse({"error": "Cooling modes need the Balanced power plan."}, status_code=409)
        t = time.time()
        try:
            state.cooling.set_mode(body.mode, "app", t)
        except OSError as exc:
            return JSONResponse({"error": f"Windows error {exc.errno}"}, status_code=502)
        state.smart.on_manual_change(t)
        return {"mode": body.mode}

    @app.put("/api/cooling/smart", dependencies=[Depends(require_token)])
    def put_smart(body: SmartIn):
        rules = SmartRules(**body.model_dump())
        state.smart.set_rules(rules)
        state.settings.smart = rules
        save_settings()
        return asdict(rules)

    @app.post("/api/monitor/pause", dependencies=[Depends(require_token)])
    def pause():
        state.sampler.paused = True
        return {"paused": True}

    @app.post("/api/monitor/resume", dependencies=[Depends(require_token)])
    def resume():
        state.sampler.paused = False
        return {"paused": False}

    @app.post("/api/quit", dependencies=[Depends(require_token)])
    def quit_app():
        state.request_quit()
        return {"stopping": True}

    return app


def _sse(data: dict) -> str:
    return f"event: snapshot\ndata: {json.dumps(data, allow_nan=False)}\n\n"
