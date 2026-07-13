"""Typed match state and configuration models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional


class MatchStatus(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class PhysicalEnd(str, Enum):
    LEFT = "left"
    RIGHT = "right"


class ReviewStatus(str, Enum):
    NOT_REVIEWED = "not_reviewed"
    REVIEW_PENDING = "review_pending"
    UPHELD = "upheld"
    OVERTURNED = "overturned"
    VOIDED = "voided"


@dataclass(frozen=True)
class MatchConfig:
    """Immutable match setup used to reduce events."""

    player_a_name: str = "Player A"
    player_b_name: str = "Player B"
    best_of: int = 5
    first_server: str = "A"
    points_to_win_game: int = 11
    must_win_by: int = 2

    def __post_init__(self) -> None:
        if self.best_of not in (3, 5, 7):
            raise ValueError("best_of must be 3, 5, or 7")
        if self.first_server not in ("A", "B"):
            raise ValueError("first_server must be A or B")

    @property
    def games_required_to_win(self) -> int:
        return self.best_of // 2 + 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MatchConfig:
        return cls(
            player_a_name=str(data.get("player_a_name", "Player A")),
            player_b_name=str(data.get("player_b_name", "Player B")),
            best_of=int(data.get("best_of", 5)),
            first_server=str(data.get("first_server", "A")),
            points_to_win_game=int(data.get("points_to_win_game", 11)),
            must_win_by=int(data.get("must_win_by", 2)),
        )


@dataclass
class PlayerState:
    name: str
    points: int = 0
    games: int = 0
    physical_end: PhysicalEnd = PhysicalEnd.LEFT

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "points": self.points,
            "games": self.games,
            "physical_end": self.physical_end.value,
        }


@dataclass
class GameResult:
    game_number: int
    winner: str
    score_a: int
    score_b: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TimelineEntry:
    """One scoring point as shown in the UI timeline."""

    point_id: str
    point_number: int
    game_number: int
    awarded_to: str
    effective_to: Optional[str]
    score_after: str
    server_before: str
    timestamp: str
    source: str
    review_status: str
    final_decision: str
    replay_available: bool
    clip_path: Optional[str] = None
    clip_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MatchState:
    """Derived match state; always recomputed from event history."""

    player_a: PlayerState
    player_b: PlayerState
    best_of: int
    games_required_to_win: int
    current_game: int
    current_server: str
    starting_server_for_current_game: str
    match_status: MatchStatus
    winner: Optional[str] = None
    deciding_game_end_switched: bool = False
    game_results: list[GameResult] = field(default_factory=list)
    timeline: list[TimelineEntry] = field(default_factory=list)
    points_to_win_game: int = 11
    must_win_by: int = 2
    match_id: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    pending_review_point_id: Optional[str] = None

    def player(self, side: str) -> PlayerState:
        return self.player_a if side == "A" else self.player_b

    def other(self, side: str) -> str:
        return "B" if side == "A" else "A"

    def is_deciding_game(self) -> bool:
        return (
            self.match_status == MatchStatus.IN_PROGRESS
            and self.player_a.games + self.player_b.games == self.best_of - 1
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "player_a": self.player_a.to_dict(),
            "player_b": self.player_b.to_dict(),
            "best_of": self.best_of,
            "games_required_to_win": self.games_required_to_win,
            "current_game": self.current_game,
            "current_server": self.current_server,
            "starting_server_for_current_game": self.starting_server_for_current_game,
            "match_status": self.match_status.value,
            "winner": self.winner,
            "deciding_game_end_switched": self.deciding_game_end_switched,
            "game_results": [g.to_dict() for g in self.game_results],
            "timeline": [t.to_dict() for t in self.timeline],
            "points_to_win_game": self.points_to_win_game,
            "must_win_by": self.must_win_by,
            "match_id": self.match_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "pending_review_point_id": self.pending_review_point_id,
            "is_deciding_game": self.is_deciding_game(),
        }

    def legacy_score_dict(self) -> dict[str, Any]:
        """Backward-compatible snapshot for older UI / HUD code."""
        return {
            "player_a": self.player_a.name,
            "player_b": self.player_b.name,
            "a": self.player_a.points,
            "b": self.player_b.points,
            "games_a": self.player_a.games,
            "games_b": self.player_b.games,
            "serving": self.current_server,
            "points_to_win": self.points_to_win_game,
            "must_win_by": self.must_win_by,
            "best_of": self.best_of,
            "current_game": self.current_game,
            "match_status": self.match_status.value,
            "winner": self.winner,
            "end_a": self.player_a.physical_end.value,
            "end_b": self.player_b.physical_end.value,
        }


@dataclass
class MatchSummary:
    winner: Optional[str]
    winner_name: Optional[str]
    games_a: int
    games_b: int
    game_scores: list[dict[str, Any]]
    duration_seconds: Optional[float]
    total_points: int
    reviewed_points: int
    overturned_calls: int
    timeline: list[dict[str, Any]]
    clip_ids: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
