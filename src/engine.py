"""Live pipeline: camera -> track -> referee -> score -> replay."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

import cv2
import numpy as np

from src.camera import Camera
from src.config import REPLAY_DIR, load_config
from src.referee import Call, Referee
from src.replay import ReplayBuffer
from src.score import Scoreboard
from src.tracker import BallTracker

logger = logging.getLogger(__name__)


class VAREngine:
    def __init__(self) -> None:
        cfg = load_config()
        self.cfg = cfg
        self.camera = Camera(
            camera_url=cfg.get("camera_url", ""),
            camera_index=int(cfg.get("camera_index", 0)),
            prefer_phone=bool(cfg.get("prefer_phone", True)),
            process_width=int(cfg.get("process_width", 960)),
        )
        self.tracker = BallTracker(
            cfg.get("ball_hsv_lower", [0, 0, 180]),
            cfg.get("ball_hsv_upper", [180, 50, 255]),
        )
        self.referee = Referee()
        self.score = Scoreboard(
            points_to_win=int(cfg.get("points_to_win", 11)),
            must_win_by=int(cfg.get("must_win_by", 2)),
        )
        self.replay = ReplayBuffer(
            seconds=float(cfg.get("replay_seconds", 8)),
            fps=int(cfg.get("replay_fps", 20)),
            out_dir=REPLAY_DIR,
        )
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._frame_jpeg: Optional[bytes] = None
        self._lock = threading.Lock()
        self.auto_call = True
        self.pending_point_side: Optional[str] = None  # suggested after OUT
        self.status: dict[str, Any] = {"state": "idle"}
        self._bounce_cooldown_until = 0.0
        self.trail: list[tuple[int, int]] = []

    def start(self) -> None:
        if self._running:
            return
        self.camera.start()
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self.status = {"state": "running", "source": self.camera.source_label}

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self.camera.stop()
        self.status = {"state": "stopped"}

    def _loop(self) -> None:
        while self._running:
            frame = self.camera.read()
            if frame is None:
                # placeholder so MJPEG still works before camera connects
                placeholder = np.zeros((480, 860, 3), dtype=np.uint8)
                msg = self.camera.last_error or "Waiting for camera..."
                cv2.putText(
                    placeholder,
                    msg,
                    (40, 240),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (200, 200, 200),
                    2,
                    cv2.LINE_AA,
                )
                self._set_jpeg(placeholder)
                time.sleep(0.2)
                continue

            det = self.tracker.detect(frame)
            annotated = self.referee.draw_overlay(frame)

            if det is not None:
                cx, cy = int(det.x), int(det.y)
                self.trail.append((cx, cy))
                self.trail = self.trail[-40:]
                cv2.circle(annotated, (cx, cy), int(det.radius), (0, 165, 255), 2)
                cv2.circle(annotated, (cx, cy), 3, (255, 255, 255), -1)

                now = time.time()
                if (
                    self.auto_call
                    and self.tracker.bounce_candidate()
                    and now >= self._bounce_cooldown_until
                ):
                    decision = self.referee.call_bounce(det.x, det.y)
                    self._bounce_cooldown_until = now + 0.45
                    clip = self.replay.save_clip(label=f"bounce-{decision.call.value}")
                    if decision.call == Call.OUT:
                        # suggest point to server's opponent is complex; leave manual/suggested B default
                        self.pending_point_side = "A"
                    self.status = {
                        "state": "running",
                        "source": self.camera.source_label,
                        "last_call": decision.call.value,
                        "reason": decision.reason,
                        "replay_id": clip.id if clip else None,
                    }

            for i in range(1, len(self.trail)):
                cv2.line(annotated, self.trail[i - 1], self.trail[i], (0, 140, 255), 2)

            # HUD
            s = self.score.snapshot()
            hud = f"{s['player_a']} {s['a']}  |  {s['b']} {s['player_b']}   serve:{s['serving']}"
            cv2.putText(
                annotated,
                hud,
                (20, annotated.shape[0] - 20),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )

            self.replay.push(annotated)
            self._set_jpeg(annotated)
            time.sleep(0.01)

    def _set_jpeg(self, frame: np.ndarray) -> None:
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
        if not ok:
            return
        with self._lock:
            self._frame_jpeg = buf.tobytes()

    def get_jpeg(self) -> Optional[bytes]:
        with self._lock:
            return self._frame_jpeg

    def manual_call(self, x: float, y: float) -> dict:
        decision = self.referee.call_bounce(x, y)
        clip = self.replay.save_clip(label=f"manual-{decision.call.value}")
        return {
            "call": decision.call.value,
            "reason": decision.reason,
            "replay_id": clip.id if clip else None,
        }
