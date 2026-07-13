"""FastAPI web app for Ping Pong VAR."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from src.config import load_config, save_config
from src.engine import VAREngine
from src.scoring.models import MatchStatus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pingpong-var")

app = FastAPI(title="Ping Pong VAR")
engine = VAREngine()

STATIC = Path(__file__).parent / "static"
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


class CornersBody(BaseModel):
    corners: list[list[float]] = Field(..., min_length=4, max_length=4)


class NetBody(BaseModel):
    net: list[list[float]] = Field(..., min_length=2, max_length=2)


class PointBody(BaseModel):
    side: str
    reason: str = ""
    source: str = "manual"


class NamesBody(BaseModel):
    player_a: str
    player_b: str


class HsvBody(BaseModel):
    lower: list[int]
    upper: list[int]


class ManualCallBody(BaseModel):
    x: float
    y: float


class CameraBody(BaseModel):
    camera_url: str
    prefer_phone: bool = True


class StartMatchBody(BaseModel):
    player_a: str = "Player A"
    player_b: str = "Player B"
    best_of: int = 5
    first_server: str = "A"  # A | B | random


class ReviewBody(BaseModel):
    decision: str  # uphold | overturn | void
    point_id: Optional[str] = None


@app.on_event("startup")
def _startup() -> None:
    engine.start()


@app.on_event("shutdown")
def _shutdown() -> None:
    engine.stop()


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> Any:
    return TEMPLATES.TemplateResponse(request, "index.html")


@app.get("/api/status")
def status() -> dict:
    snap = engine.match.snapshot()
    match = snap.get("match") or {}
    return {
        **engine.status,
        "score": snap,
        "match": match,
        "summary": snap.get("summary"),
        "timeline": match.get("timeline") or [],
        "table_ready": engine.referee.table.ready(),
        "auto_call": engine.auto_call,
        "pending_point_side": engine.pending_point_side,
        "camera_error": engine.camera.last_error,
        "config": {
            "camera_url": engine.cfg.get("camera_url"),
            "prefer_phone": engine.cfg.get("prefer_phone"),
            "match": engine.cfg.get("match") or {},
            "review": engine.cfg.get("review") or {},
        },
    }


@app.get("/api/stream")
def stream() -> StreamingResponse:
    def gen():
        import time

        while True:
            jpeg = engine.get_jpeg()
            if jpeg:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
                )
            time.sleep(0.04)

    return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.post("/api/match/start")
def start_match(body: StartMatchBody) -> dict:
    allowed = (engine.cfg.get("match") or {}).get("allowed_formats") or [3, 5, 7]
    if body.best_of not in allowed:
        raise HTTPException(400, f"best_of must be one of {allowed}")
    try:
        st = engine.match.start_match(
            player_a=body.player_a,
            player_b=body.player_b,
            best_of=body.best_of,
            first_server=body.first_server,
            points_to_win_game=engine.points_to_win_game,
            must_win_by=engine.must_win_by,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "match": st.to_dict()}


@app.post("/api/match/new")
def new_match() -> dict:
    st = engine.match.new_match()
    return {"ok": True, "match": st.to_dict()}


@app.get("/api/match/summary")
def match_summary() -> dict:
    return engine.match.summary().to_dict()


@app.get("/api/matches")
def list_matches() -> dict:
    if engine.match.persistence is None:
        return {"matches": []}
    return {"matches": engine.match.persistence.list_matches()}


@app.post("/api/table/corners")
def set_corners(body: CornersBody) -> dict:
    engine.referee.set_corners(body.corners)
    return {"ok": True, "corners": engine.referee.table.corners}


@app.post("/api/table/clear")
def clear_table() -> dict:
    engine.referee.table.corners = []
    engine.referee.table.net = []
    engine.referee.last_decision = None
    return {"ok": True}


@app.post("/api/table/net")
def set_net(body: NetBody) -> dict:
    engine.referee.set_net(body.net)
    return {"ok": True, "net": engine.referee.table.net}


@app.post("/api/call/manual")
def manual_call(body: ManualCallBody) -> dict:
    return engine.manual_call(body.x, body.y)


@app.post("/api/score/point")
def score_point(body: PointBody) -> dict:
    try:
        st = engine.match.award_point(
            body.side, source=body.source or "manual", reason=body.reason, attach_replay=True
        )
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    engine.pending_point_side = None
    return {"ok": True, "match": st.to_dict(), "score": engine.match.snapshot()}


@app.post("/api/score/undo")
def score_undo() -> dict:
    st = engine.match.undo()
    return {"ok": True, "match": st.to_dict(), "score": engine.match.snapshot()}


@app.post("/api/score/reset-match")
def reset_match() -> dict:
    st = engine.match.new_match()
    return {"ok": True, "match": st.to_dict(), "score": engine.match.snapshot()}


@app.post("/api/score/names")
def set_names(body: NamesBody) -> dict:
    # Names apply on next start_match; keep endpoint for compatibility.
    return {
        "ok": True,
        "hint": "Use /api/match/start to set names for a new match",
        "player_a": body.player_a,
        "player_b": body.player_b,
    }


@app.post("/api/review/request")
def review_request(point_id: Optional[str] = None) -> dict:
    try:
        st = engine.match.request_review(point_id)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    entry = next((t for t in st.timeline if t.point_id == st.pending_review_point_id), None)
    clip_url = None
    message = None
    if entry and entry.clip_id:
        clip_url = f"/api/replay/{entry.clip_id}"
    else:
        message = "Replay clip unavailable. Manual decision required."
    return {
        "ok": True,
        "match": st.to_dict(),
        "point_id": st.pending_review_point_id,
        "clip_url": clip_url,
        "message": message,
        "entry": entry.to_dict() if entry else None,
    }


@app.post("/api/review/resolve")
def review_resolve(body: ReviewBody) -> dict:
    try:
        st = engine.match.resolve_review(body.decision, body.point_id)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "ok": True,
        "match": st.to_dict(),
        "summary": engine.match.summary().to_dict()
        if st.match_status == MatchStatus.COMPLETED
        else None,
    }


@app.post("/api/auto-call")
def set_auto_call(enabled: bool = True) -> dict:
    engine.auto_call = enabled
    return {"ok": True, "auto_call": engine.auto_call}


@app.post("/api/hsv")
def set_hsv(body: HsvBody) -> dict:
    engine.tracker.set_hsv(body.lower, body.upper)
    engine.cfg["ball_hsv_lower"] = body.lower
    engine.cfg["ball_hsv_upper"] = body.upper
    save_config(engine.cfg)
    return {"ok": True}


@app.post("/api/camera")
def set_camera(body: CameraBody) -> dict:
    engine.cfg["camera_url"] = body.camera_url
    engine.cfg["prefer_phone"] = body.prefer_phone
    save_config(engine.cfg)
    engine.camera.stop()
    engine.camera.camera_url = body.camera_url
    engine.camera.prefer_phone = body.prefer_phone
    ok = engine.camera.open()
    engine.camera.start()
    return {"ok": ok, "source": engine.camera.source_label, "error": engine.camera.last_error}


@app.post("/api/replay/save")
def save_replay(label: str = "challenge") -> dict:
    clip = engine.replay.save_clip(label=label)
    if not clip:
        raise HTTPException(400, "No frames in buffer yet")
    return {"id": clip.id, "url": f"/api/replay/{clip.id}", "label": clip.label}


@app.get("/api/replays")
def list_replays() -> dict:
    return {"clips": engine.replay.list_clips()}


@app.get("/api/replay/{clip_id}")
def get_replay(clip_id: str) -> FileResponse:
    path = engine.replay.get_path(clip_id)
    if path is None or not path.exists():
        raise HTTPException(404, "Replay not found")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


def create_app() -> FastAPI:
    return app
