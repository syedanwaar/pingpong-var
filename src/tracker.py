"""Color-based ping-pong ball tracker."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np


@dataclass
class BallDetection:
    x: float
    y: float
    radius: float
    conf: float


class BallTracker:
    def __init__(self, hsv_lower: list[int], hsv_upper: list[int]) -> None:
        self.set_hsv(hsv_lower, hsv_upper)
        self.last: Optional[BallDetection] = None
        # Simple velocity for bounce heuristic
        self._prev: Optional[BallDetection] = None
        self.vy = 0.0

    def set_hsv(self, lower: list[int], upper: list[int]) -> None:
        self.hsv_lower = np.array(lower, dtype=np.uint8)
        self.hsv_upper = np.array(upper, dtype=np.uint8)

    def detect(self, frame: np.ndarray) -> Optional[BallDetection]:
        blur = cv2.GaussianBlur(frame, (7, 7), 0)
        hsv = cv2.cvtColor(blur, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, self.hsv_lower, self.hsv_upper)
        mask = cv2.erode(mask, None, iterations=2)
        mask = cv2.dilate(mask, None, iterations=2)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best: Optional[BallDetection] = None
        best_score = 0.0

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 20 or area > 8000:
                continue
            (x, y), radius = cv2.minEnclosingCircle(cnt)
            if radius < 3 or radius > 60:
                continue
            circle_area = np.pi * radius * radius
            circularity = float(area / circle_area) if circle_area > 0 else 0.0
            if circularity < 0.45:
                continue
            score = circularity * min(area, 2000)
            if score > best_score:
                best_score = score
                best = BallDetection(float(x), float(y), float(radius), circularity)

        if best is not None:
            if self._prev is not None:
                self.vy = best.y - self._prev.y
            self._prev = best
            self.last = best
        else:
            # decay memory slightly so UI knows we lost track
            if self.last is not None:
                self.last = BallDetection(
                    self.last.x, self.last.y, self.last.radius, max(0.0, self.last.conf - 0.15)
                )
        return best

    def bounce_candidate(self) -> bool:
        """True when vertical velocity flips upward after going down (table contact approx)."""
        if self._prev is None or self.last is None:
            return False
        return self.vy < -1.5  # upward after impact (image y grows downward)
