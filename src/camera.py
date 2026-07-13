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

    def open(self) -> bool:
        sources: list[tuple[str, str | int]] = []
        if self.prefer_phone:
            sources.append(("phone", self.camera_url))
            sources.append(("webcam", self.camera_index))
        else:
            sources.append(("webcam", self.camera_index))
            sources.append(("phone", self.camera_url))

        for label, src in sources:
            cap = cv2.VideoCapture(src)
            if not cap.isOpened():
                cap.release()
                continue
            ok, frame = cap.read()
            if not ok or frame is None:
                cap.release()
                continue
            self._cap = cap
            self.source_label = label
            self.last_error = ""
            self._frame = self._resize(frame)
            logger.info("Camera opened via %s (%s)", label, src)
            return True

        self.last_error = "Could not open phone stream or local webcam"
        logger.error(self.last_error)
        return False

    def start(self) -> None:
        if self._running:
            return
        if self._cap is None and not self.open():
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
        while self._running and self._cap is not None:
            ok, frame = self._cap.read()
            if not ok or frame is None:
                failures += 1
                if failures > 30:
                    logger.warning("Camera read failing; attempting reopen")
                    self._cap.release()
                    self._cap = None
                    if not self.open():
                        time.sleep(1.0)
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
