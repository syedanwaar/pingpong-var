"""Pure event reducer: MatchState is always derived from history."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from src.scoring.events import MatchEvent, MatchEventType
from src.scoring.models import (
    GameResult,
    MatchConfig,
    MatchState,
    MatchStatus,
    PhysicalEnd,
    PlayerState,
    ReviewStatus,
    TimelineEntry,
)
from src.scoring.rules import (
    game_winner,
    is_deciding_game,
    opposite,
    server_for_score,
)


@dataclass
class _EffectivePoint:
    point_id: str
    original_player: str
    effective_player: Optional[str]
    active: bool
    review_status: ReviewStatus
    server_before: str
    source: str
    timestamp: str
    clip_path: Optional[str]
    clip_id: Optional[str]
    award_order: int


def _empty_state(config: MatchConfig) -> MatchState:
    return MatchState(
        player_a=PlayerState(name=config.player_a_name, physical_end=PhysicalEnd.LEFT),
        player_b=PlayerState(name=config.player_b_name, physical_end=PhysicalEnd.RIGHT),
        best_of=config.best_of,
        games_required_to_win=config.games_required_to_win,
        current_game=1,
        current_server=config.first_server,
        starting_server_for_current_game=config.first_server,
        match_status=MatchStatus.NOT_STARTED,
        points_to_win_game=config.points_to_win_game,
        must_win_by=config.must_win_by,
    )


def _switch_ends(state: MatchState) -> None:
    state.player_a.physical_end, state.player_b.physical_end = (
        state.player_b.physical_end,
        state.player_a.physical_end,
    )


def _resolve_effective_points(events: Iterable[MatchEvent]) -> dict[str, _EffectivePoint]:
    points: dict[str, _EffectivePoint] = {}
    order = 0
    for event in events:
        p = event.payload
        if event.event_type == MatchEventType.POINT_AWARDED:
            pid = str(p["point_id"])
            points[pid] = _EffectivePoint(
                point_id=pid,
                original_player=str(p["player"]),
                effective_player=str(p["player"]),
                active=True,
                review_status=ReviewStatus.NOT_REVIEWED,
                server_before=str(p["server_before_point"]),
                source=str(p.get("source", "manual")),
                timestamp=event.timestamp,
                clip_path=p.get("clip_path"),
                clip_id=p.get("clip_id"),
                award_order=order,
            )
            order += 1
        elif event.event_type == MatchEventType.REVIEW_REQUESTED:
            pid = str(p["point_id"])
            if pid in points and points[pid].review_status == ReviewStatus.NOT_REVIEWED:
                points[pid].review_status = ReviewStatus.REVIEW_PENDING
        elif event.event_type == MatchEventType.REVIEW_UPHELD:
            pid = str(p["point_id"])
            if pid in points:
                points[pid].review_status = ReviewStatus.UPHELD
                points[pid].active = True
                points[pid].effective_player = points[pid].original_player
        elif event.event_type == MatchEventType.REVIEW_OVERTURNED:
            pid = str(p["point_id"])
            if pid in points:
                points[pid].review_status = ReviewStatus.OVERTURNED
                points[pid].active = True
                points[pid].effective_player = str(p["new_player"])
        elif event.event_type == MatchEventType.POINT_VOIDED:
            pid = str(p["point_id"])
            if pid in points:
                points[pid].review_status = ReviewStatus.VOIDED
                points[pid].active = False
                points[pid].effective_player = None
    return points


def reduce_match_state(
    events: list[MatchEvent],
    initial_config: MatchConfig | None = None,
) -> MatchState:
    """
    Deterministically rebuild match state from an ordered event list.

    Does not mutate ``events`` and does not append events. Game wins and match
    completion are derived from active points (no duplicate game-win events).
    """
    events = list(events)
    config = initial_config or MatchConfig()
    state = _empty_state(config)
    started = False

    for event in events:
        if event.event_type == MatchEventType.MATCH_STARTED:
            config = MatchConfig.from_dict(event.payload.get("config") or {})
            state = _empty_state(config)
            state.match_id = event.payload.get("match_id")
            state.started_at = event.timestamp
            state.match_status = MatchStatus.IN_PROGRESS
            started = True

    if not started:
        if initial_config is not None:
            state = _empty_state(initial_config)
            state.match_status = MatchStatus.IN_PROGRESS
            config = initial_config
        elif not any(e.event_type == MatchEventType.POINT_AWARDED for e in events):
            return state

    effective = _resolve_effective_points(events)
    ordered = sorted(effective.values(), key=lambda x: x.award_order)

    points_in_game = {"A": 0, "B": 0}
    point_number_in_game = 0
    pending_review: Optional[str] = None

    for ep in ordered:
        if not ep.active or ep.effective_player is None:
            state.timeline.append(
                TimelineEntry(
                    point_id=ep.point_id,
                    point_number=point_number_in_game,
                    game_number=state.current_game,
                    awarded_to=ep.original_player,
                    effective_to=None,
                    score_after=f"{points_in_game['A']}–{points_in_game['B']}",
                    server_before=ep.server_before,
                    timestamp=ep.timestamp,
                    source=ep.source,
                    review_status=ep.review_status.value,
                    final_decision="voided",
                    replay_available=bool(ep.clip_id or ep.clip_path),
                    clip_path=ep.clip_path,
                    clip_id=ep.clip_id,
                )
            )
            if ep.review_status == ReviewStatus.REVIEW_PENDING:
                pending_review = ep.point_id
            continue

        if state.match_status == MatchStatus.COMPLETED:
            continue

        server_before = server_for_score(
            points_in_game["A"],
            points_in_game["B"],
            state.starting_server_for_current_game,
            config.points_to_win_game,
        )
        winner_side = ep.effective_player
        points_in_game[winner_side] += 1
        point_number_in_game += 1

        if (
            is_deciding_game(state.player_a.games, state.player_b.games, config.best_of)
            and not state.deciding_game_end_switched
            and max(points_in_game["A"], points_in_game["B"]) == 5
        ):
            _switch_ends(state)
            state.deciding_game_end_switched = True

        state.player_a.points = points_in_game["A"]
        state.player_b.points = points_in_game["B"]
        state.current_server = server_for_score(
            points_in_game["A"],
            points_in_game["B"],
            state.starting_server_for_current_game,
            config.points_to_win_game,
        )

        if ep.review_status == ReviewStatus.OVERTURNED:
            final_label = f"overturned → {winner_side}"
        elif ep.review_status == ReviewStatus.UPHELD:
            final_label = f"upheld → {winner_side}"
        else:
            final_label = f"{winner_side} point"

        state.timeline.append(
            TimelineEntry(
                point_id=ep.point_id,
                point_number=point_number_in_game,
                game_number=state.current_game,
                awarded_to=ep.original_player,
                effective_to=winner_side,
                score_after=f"{points_in_game['A']}–{points_in_game['B']}",
                server_before=server_before,
                timestamp=ep.timestamp,
                source=ep.source,
                review_status=ep.review_status.value,
                final_decision=final_label,
                replay_available=bool(ep.clip_id or ep.clip_path),
                clip_path=ep.clip_path,
                clip_id=ep.clip_id,
            )
        )
        if ep.review_status == ReviewStatus.REVIEW_PENDING:
            pending_review = ep.point_id

        gw = game_winner(
            points_in_game["A"],
            points_in_game["B"],
            config.points_to_win_game,
            config.must_win_by,
        )
        if gw is None:
            continue

        state.game_results.append(
            GameResult(
                game_number=state.current_game,
                winner=gw,
                score_a=points_in_game["A"],
                score_b=points_in_game["B"],
            )
        )
        if gw == "A":
            state.player_a.games += 1
        else:
            state.player_b.games += 1

        if (
            state.player_a.games >= config.games_required_to_win
            or state.player_b.games >= config.games_required_to_win
        ):
            state.match_status = MatchStatus.COMPLETED
            state.winner = (
                "A" if state.player_a.games >= config.games_required_to_win else "B"
            )
        else:
            _switch_ends(state)
            state.starting_server_for_current_game = opposite(
                state.starting_server_for_current_game
            )
            state.current_game += 1
            state.deciding_game_end_switched = False
            points_in_game = {"A": 0, "B": 0}
            point_number_in_game = 0
            state.player_a.points = 0
            state.player_b.points = 0
            state.current_server = state.starting_server_for_current_game

    state.pending_review_point_id = pending_review

    for event in events:
        if event.event_type == MatchEventType.MATCH_COMPLETED:
            state.match_status = MatchStatus.COMPLETED
            state.winner = event.payload.get("winner") or state.winner
            state.ended_at = event.timestamp

    if state.match_status == MatchStatus.IN_PROGRESS:
        state.current_server = server_for_score(
            state.player_a.points,
            state.player_b.points,
            state.starting_server_for_current_game,
            config.points_to_win_game,
        )

    return state
