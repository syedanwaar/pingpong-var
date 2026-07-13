"""Table calibration + in/out calls."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import cv2
import numpy as np


class Call(str, Enum):
    IN = "IN"
    OUT = "OUT"
    UNKNOWN = "UNKNOWN"


@dataclass
class TableGeometry:
    # Four corners in image coords: TL, TR, BR, BL
    corners: list[list[float]] = field(default_factory=list)
    # Net midline as two points (optional)
    net: list[list[float]] = field(default_factory=list)

    def ready(self) -> bool:
        return len(self.corners) == 4

    def as_np(self) -> np.ndarray:
        return np.array(self.corners, dtype=np.float32)

    def contains(self, x: float, y: float) -> bool:
        if not self.ready():
            return False
        # pointPolygonTest: + inside, 0 edge, - outside
        return cv2.pointPolygonTest(self.as_np(), (x, y), False) >= 0


@dataclass
class RefereeDecision:
    call: Call
    x: float
    y: float
    reason: str


class Referee:
    def __init__(self) -> None:
        self.table = TableGeometry()
        self.last_decision: Optional[RefereeDecision] = None

    def set_corners(self, corners: list[list[float]]) -> None:
        if len(corners) != 4:
            raise ValueError("Need exactly 4 corners: TL, TR, BR, BL")
        self.table.corners = [[float(p[0]), float(p[1])] for p in corners]

    def set_net(self, net: list[list[float]]) -> None:
        self.table.net = [[float(p[0]), float(p[1])] for p in net]

    def call_bounce(self, x: float, y: float) -> RefereeDecision:
        if not self.table.ready():
            decision = RefereeDecision(Call.UNKNOWN, x, y, "Table not calibrated")
        elif self.table.contains(x, y):
            decision = RefereeDecision(Call.IN, x, y, "Bounce inside table polygon")
        else:
            decision = RefereeDecision(Call.OUT, x, y, "Bounce outside table polygon")
        self.last_decision = decision
        return decision

    def draw_overlay(self, frame: np.ndarray) -> np.ndarray:
        out = frame.copy()
        if self.table.ready():
            pts = self.table.as_np().astype(np.int32).reshape((-1, 1, 2))
            cv2.polylines(out, [pts], True, (0, 220, 0), 2)
            overlay = out.copy()
            cv2.fillPoly(overlay, [pts], (0, 180, 0))
            cv2.addWeighted(overlay, 0.12, out, 0.88, 0, out)
        if len(self.table.net) == 2:
            a, b = self.table.net
            cv2.line(
                out,
                (int(a[0]), int(a[1])),
                (int(b[0]), int(b[1])),
                (255, 255, 0),
                2,
            )
        if self.last_decision is not None:
            color = {
                Call.IN: (0, 255, 0),
                Call.OUT: (0, 0, 255),
                Call.UNKNOWN: (0, 200, 255),
            }[self.last_decision.call]
            cv2.circle(
                out,
                (int(self.last_decision.x), int(self.last_decision.y)),
                10,
                color,
                2,
            )
            cv2.putText(
                out,
                self.last_decision.call.value,
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.2,
                color,
                3,
                cv2.LINE_AA,
            )
        return out
