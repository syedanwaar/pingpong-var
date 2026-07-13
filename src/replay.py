"""Circular frame buffer + on-demand replay clip export."""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Deque, Optional

import cv2
import numpy as np


@dataclass
class ReplayClip:
    id: str
    path: str
    created_at: float
    label: str
    frames: int


class ReplayBuffer:
    def __init__(self, seconds: float = 8.0, fps: int = 20, out_dir: Path | None = None) -> None:
        self.seconds = seconds
        self.fps = fps
        self.maxlen = max(1, int(seconds * fps))
        self._frames: Deque[np.ndarray] = deque(maxlen=self.maxlen)
        self._lock = threading.Lock()
        self.out_dir = out_dir or Path("data/replays")
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.clips: list[ReplayClip] = []
        self._last_push = 0.0
        self._interval = 1.0 / fps

    def push(self, frame: np.ndarray) -> None:
        now = time.time()
        if now - self._last_push < self._interval:
            return
        self._last_push = now
        with self._lock:
            self._frames.append(frame.copy())

    def save_clip(self, label: str = "challenge") -> Optional[ReplayClip]:
        with self._lock:
            if not self._frames:
                return None
            frames = list(self._frames)

        h, w = frames[0].shape[:2]
        clip_id = uuid.uuid4().hex[:10]
        path = self.out_dir / f"replay_{clip_id}.mp4"
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(path), fourcc, self.fps, (w, h))
        for f in frames:
            writer.write(f)
        writer.release()

        clip = ReplayClip(
            id=clip_id,
            path=str(path),
            created_at=time.time(),
            label=label,
            frames=len(frames),
        )
        self.clips.insert(0, clip)
        self.clips = self.clips[:30]
        return clip

    def list_clips(self) -> list[dict]:
        return [
            {
                "id": c.id,
                "path": c.path,
                "created_at": c.created_at,
                "label": c.label,
                "frames": c.frames,
                "url": f"/api/replay/{c.id}",
            }
            for c in self.clips
        ]

    def get_path(self, clip_id: str) -> Optional[Path]:
        for c in self.clips:
            if c.id == clip_id:
                return Path(c.path)
        return None
