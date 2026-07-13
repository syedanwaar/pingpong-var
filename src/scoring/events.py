"""Match event types and payloads (source of truth for scoring)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4


class MatchEventType(str, Enum):
    POINT_AWARDED = "point_awarded"
    REVIEW_REQUESTED = "review_requested"
    REVIEW_UPHELD = "review_upheld"
    REVIEW_OVERTURNED = "review_overturned"
    POINT_VOIDED = "point_voided"
    MATCH_STARTED = "match_started"
    MATCH_COMPLETED = "match_completed"


def new_id() -> str:
    return uuid4().hex


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class MatchEvent:
    """Immutable scoring/review event stored in ordered history."""

    event_type: MatchEventType
    event_id: str = field(default_factory=new_id)
    timestamp: str = field(default_factory=utc_now_iso)
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MatchEvent:
        return cls(
            event_id=str(data["event_id"]),
            event_type=MatchEventType(data["event_type"]),
            timestamp=str(data.get("timestamp", utc_now_iso())),
            payload=dict(data.get("payload") or {}),
        )


def match_started_event(
    match_id: str,
    config: dict[str, Any],
    timestamp: Optional[str] = None,
) -> MatchEvent:
    return MatchEvent(
        event_type=MatchEventType.MATCH_STARTED,
        timestamp=timestamp or utc_now_iso(),
        payload={"match_id": match_id, "config": config},
    )


def point_awarded_event(
    *,
    point_id: str,
    player: str,
    server_before_point: str,
    game_number: int,
    source: str = "manual",
    clip_path: Optional[str] = None,
    clip_id: Optional[str] = None,
    buffer_start_ts: Optional[float] = None,
    buffer_end_ts: Optional[float] = None,
    camera_id: Optional[str] = None,
    reason: str = "",
    timestamp: Optional[str] = None,
) -> MatchEvent:
    return MatchEvent(
        event_type=MatchEventType.POINT_AWARDED,
        timestamp=timestamp or utc_now_iso(),
        payload={
            "point_id": point_id,
            "player": player,
            "server_before_point": server_before_point,
            "game_number": game_number,
            "source": source,
            "review_status": "not_reviewed",
            "clip_path": clip_path,
            "clip_id": clip_id,
            "buffer_start_ts": buffer_start_ts,
            "buffer_end_ts": buffer_end_ts,
            "camera_id": camera_id,
            "reason": reason,
        },
    )


def review_requested_event(point_id: str, timestamp: Optional[str] = None) -> MatchEvent:
    return MatchEvent(
        event_type=MatchEventType.REVIEW_REQUESTED,
        timestamp=timestamp or utc_now_iso(),
        payload={"point_id": point_id},
    )


def review_upheld_event(point_id: str, timestamp: Optional[str] = None) -> MatchEvent:
    return MatchEvent(
        event_type=MatchEventType.REVIEW_UPHELD,
        timestamp=timestamp or utc_now_iso(),
        payload={"point_id": point_id},
    )


def review_overturned_event(
    point_id: str,
    new_player: str,
    timestamp: Optional[str] = None,
) -> MatchEvent:
    return MatchEvent(
        event_type=MatchEventType.REVIEW_OVERTURNED,
        timestamp=timestamp or utc_now_iso(),
        payload={"point_id": point_id, "new_player": new_player},
    )


def point_voided_event(point_id: str, timestamp: Optional[str] = None) -> MatchEvent:
    return MatchEvent(
        event_type=MatchEventType.POINT_VOIDED,
        timestamp=timestamp or utc_now_iso(),
        payload={"point_id": point_id},
    )


def match_completed_event(
    winner: str,
    timestamp: Optional[str] = None,
) -> MatchEvent:
    return MatchEvent(
        event_type=MatchEventType.MATCH_COMPLETED,
        timestamp=timestamp or utc_now_iso(),
        payload={"winner": winner},
    )
