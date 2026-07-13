"""Android phone / local webcam capture."""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class Camera:
    def __init__(
        self,
        camera_url: str,
        camera_index: int = 0,
        prefer_phone: bool = True,
        process_width: int = 960,
    ) -> None:
        self.camera_url = camera_url
        self.camera_index = camera_index
        self.prefer_phone = prefer_phone
        self.process_width = process_width
        self._cap: Optional[cv2.VideoCapture] = None
        self._frame: Optional[np.ndarray] = None
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self.source_label = "none"
        self.last_error = ""

    def _try_open_one(self, label: str, src: str | int, timeout: float) -> bool:
        """Open one source with a timeout so dead phone URLs don't hang the server."""
        box: dict = {"cap": None, "frame": None, "ok": False}

        def worker() -> None:
            try:
                cap = cv2.VideoCapture(src)
                if not cap.isOpened():
                    cap.release()
                    return
                ok, frame = cap.read()
                if not ok or frame is None:
                    cap.release()
                    return
                box["cap"] = cap
                box["frame"] = frame
                box["ok"] = True
            except Exception as exc:  # noqa: BLE001
                logger.warning("Camera open error (%s): %s", label, exc)

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        t.join(timeout=timeout)
        if t.is_alive() or not box["ok"]:
            # Abandoned worker may still hold a socket briefly; don't block startup.
            cap = box.get("cap")
            if cap is not None:
                try:
                    cap.release()
                except Exception:  # noqa: BLE001
                    pass
            return False

        self._cap = box["cap"]
        self.source_label = label
        self.last_error = ""
        self._frame = self._resize(box["frame"])
        logger.info("Camera opened via %s (%s)", label, src)
        return True

    def open(self, phone_timeout: float = 2.5, webcam_timeout: float = 3.0) -> bool:
        sources: list[tuple[str, str | int, float]] = []
        phone = ("phone", self.camera_url, phone_timeout)
        webcam = ("webcam", self.camera_index, webcam_timeout)

        if self.prefer_phone and self.camera_url:
            sources.extend([phone, webcam])
        else:
            sources.append(webcam)
            if self.camera_url:
                sources.append(phone)

        for label, src, timeout in sources:
            if self._try_open_one(label, src, timeout):
                return True

        self.last_error = "Could not open phone stream or local webcam"
        self.source_label = "none"
        logger.error(self.last_error)
        return False

    def start(self) -> None:
        """Start capture loop without blocking app startup on a dead camera URL."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def _loop(self) -> None:
        failures = 0
        # First open happens here so FastAPI can bind the port immediately.
        if self._cap is None:
            self.open()

        while self._running:
            if self._cap is None:
                self.last_error = self.last_error or "Waiting for camera..."
                time.sleep(1.0)
                self.open()
                continue

            ok, frame = self._cap.read()
            if not ok or frame is None:
                failures += 1
                if failures > 30:
                    logger.warning("Camera read failing; attempting reopen")
                    self._cap.release()
                    self._cap = None
                    failures = 0
                else:
                    time.sleep(0.05)
                continue
            failures = 0
            with self._lock:
                self._frame = self._resize(frame)

    def _resize(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        if w <= self.process_width:
            return frame
        scale = self.process_width / w
        return cv2.resize(frame, (self.process_width, int(h * scale)))

    def read(self) -> Optional[np.ndarray]:
        with self._lock:
            if self._frame is None:
                return None
            return self._frame.copy()
