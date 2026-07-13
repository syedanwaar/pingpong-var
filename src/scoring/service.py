"""Match service: append events, reduce state, reviews, persistence."""

from __future__ import annotations

import logging
import random
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from src.scoring.events import (
    MatchEvent,
    MatchEventType,
    match_completed_event,
    match_started_event,
    new_id,
    point_awarded_event,
    point_voided_event,
    review_overturned_event,
    review_requested_event,
    review_upheld_event,
)
from src.scoring.models import MatchConfig, MatchState, MatchStatus, MatchSummary, ReviewStatus
from src.scoring.persistence import MatchPersistence
from src.scoring.reducer import reduce_match_state
from src.scoring.rules import opposite

logger = logging.getLogger(__name__)

ClipSaver = Callable[[str], Optional[dict[str, Any]]]


class MatchService:
    """Orchestrates event history for a single live match."""

    def __init__(
        self,
        persistence: MatchPersistence | None = None,
        clip_saver: ClipSaver | None = None,
        review_enabled: bool = True,
        review_latest_only: bool = True,
    ) -> None:
        self.persistence = persistence
        self.clip_saver = clip_saver
        self.review_enabled = review_enabled
        self.review_latest_only = review_latest_only
        self._events: list[MatchEvent] = []
        self._lock = threading.RLock()
        self._config: MatchConfig | None = None
        self._saved = False

    @property
    def events(self) -> list[MatchEvent]:
        with self._lock:
            return list(self._events)

    def state(self) -> MatchState:
        with self._lock:
            return reduce_match_state(self._events, self._config)

    def snapshot(self) -> dict[str, Any]:
        """Legacy-compatible score dict plus full match state."""
        st = self.state()
        data = st.legacy_score_dict()
        data["match"] = st.to_dict()
        data["summary"] = self.summary().to_dict() if st.match_status == MatchStatus.COMPLETED else None
        return data

    def start_match(
        self,
        player_a: str,
        player_b: str,
        best_of: int = 5,
        first_server: str | None = None,
        points_to_win_game: int = 11,
        must_win_by: int = 2,
    ) -> MatchState:
        if first_server is None or first_server == "random":
            first_server = random.choice(["A", "B"])
        config = MatchConfig(
            player_a_name=player_a.strip() or "Player A",
            player_b_name=player_b.strip() or "Player B",
            best_of=best_of,
            first_server=first_server,
            points_to_win_game=points_to_win_game,
            must_win_by=must_win_by,
        )
        match_id = new_id()
        with self._lock:
            self._events = [match_started_event(match_id, config.to_dict())]
            self._config = config
            self._saved = False
        logger.info(
            "Match started id=%s best_of=%s server=%s (%s vs %s)",
            match_id,
            best_of,
            first_server,
            config.player_a_name,
            config.player_b_name,
        )
        return self.state()

    def new_match(self) -> MatchState:
        """Fully reset to not-started without stale events."""
        with self._lock:
            self._events = []
            self._config = None
            self._saved = False
        logger.info("Match reset (new match)")
        return self.state()

    def award_point(
        self,
        player: str,
        *,
        source: str = "manual",
        reason: str = "",
        attach_replay: bool = True,
    ) -> MatchState:
        player = player.upper()
        if player not in ("A", "B"):
            raise ValueError("player must be A or B")

        with self._lock:
            st = reduce_match_state(self._events, self._config)
            if st.match_status == MatchStatus.NOT_STARTED:
                raise RuntimeError("Start a match before awarding points")
            if st.match_status == MatchStatus.COMPLETED:
                raise RuntimeError("Match is complete; undo or start a new match")
            if st.pending_review_point_id:
                raise RuntimeError("Resolve pending review before awarding another point")

            point_id = new_id()
            event = point_awarded_event(
                point_id=point_id,
                player=player,
                server_before_point=st.current_server,
                game_number=st.current_game,
                source=source,
                reason=reason,
                camera_id="primary",
            )
            self._events.append(event)
            st2 = reduce_match_state(self._events, self._config)
            if st2.match_status == MatchStatus.COMPLETED and st.match_status != MatchStatus.COMPLETED:
                self._events.append(match_completed_event(st2.winner or player))
                st2 = reduce_match_state(self._events, self._config)
                self._maybe_persist(st2)

        logger.info("Point awarded to %s source=%s point_id=%s", player, source, point_id)

        if attach_replay and self.clip_saver is not None:
            self._attach_clip_async(point_id, label=f"point-{player}")

        return self.state()

    def undo(self) -> MatchState:
        with self._lock:
            if not self._events:
                return reduce_match_state(self._events, self._config)
            # Never remove MATCH_STARTED via undo of empty scoring — pop last non-start if only start?
            if len(self._events) == 1 and self._events[0].event_type == MatchEventType.MATCH_STARTED:
                return reduce_match_state(self._events, self._config)

            last = self._events[-1]
            if last.event_type == MatchEventType.MATCH_COMPLETED:
                self._events.pop()
                last = self._events[-1] if self._events else None
            if last is None:
                return reduce_match_state(self._events, self._config)

            # Undo review decision or point (and its review_requested if present).
            if last.event_type in (
                MatchEventType.REVIEW_UPHELD,
                MatchEventType.REVIEW_OVERTURNED,
                MatchEventType.POINT_VOIDED,
                MatchEventType.REVIEW_REQUESTED,
                MatchEventType.POINT_AWARDED,
            ):
                self._events.pop()
                # If we undid a review resolution, also drop pending request if now dangling — already popped one.
                # If we undid POINT_AWARDED, also remove trailing MATCH_COMPLETED already handled.
            else:
                self._events.pop()

            self._saved = False
            st = reduce_match_state(self._events, self._config)
            logger.info("Undo applied; events=%d status=%s", len(self._events), st.match_status.value)
            return st

    def latest_reviewable_point_id(self) -> str | None:
        st = self.state()
        for entry in reversed(st.timeline):
            if entry.review_status in (
                ReviewStatus.NOT_REVIEWED.value,
                ReviewStatus.REVIEW_PENDING.value,
            ):
                return entry.point_id
        return None

    def request_review(self, point_id: str | None = None) -> MatchState:
        if not self.review_enabled:
            raise RuntimeError("Review is disabled")
        with self._lock:
            st = reduce_match_state(self._events, self._config)
            if point_id is None:
                point_id = self._latest_reviewable_locked(st)
            if point_id is None:
                raise RuntimeError("No reviewable point")
            if self.review_latest_only:
                latest = self._latest_reviewable_locked(st)
                if latest != point_id:
                    raise RuntimeError("Only the latest point can be reviewed")
            entry = next((t for t in st.timeline if t.point_id == point_id), None)
            if entry is None:
                raise RuntimeError("Point not found")
            if entry.review_status not in (
                ReviewStatus.NOT_REVIEWED.value,
                ReviewStatus.REVIEW_PENDING.value,
            ):
                raise RuntimeError("Point already reviewed")
            if entry.review_status == ReviewStatus.NOT_REVIEWED.value:
                self._events.append(review_requested_event(point_id))
            logger.info("Review requested for point %s", point_id)
            return reduce_match_state(self._events, self._config)

    def resolve_review(self, decision: str, point_id: str | None = None) -> MatchState:
        """
        decision: uphold | overturn | void
        """
        decision = decision.lower().strip()
        with self._lock:
            st = reduce_match_state(self._events, self._config)
            if point_id is None:
                point_id = st.pending_review_point_id or self._latest_reviewable_locked(st)
            if point_id is None:
                raise RuntimeError("No point to review")
            entry = next((t for t in st.timeline if t.point_id == point_id), None)
            if entry is None:
                raise RuntimeError("Point not found")
            if entry.review_status not in (
                ReviewStatus.NOT_REVIEWED.value,
                ReviewStatus.REVIEW_PENDING.value,
            ):
                raise RuntimeError("Point already reviewed")

            # Ensure pending marker exists for audit trail.
            if entry.review_status == ReviewStatus.NOT_REVIEWED.value:
                self._events.append(review_requested_event(point_id))

            if decision == "uphold":
                self._events.append(review_upheld_event(point_id))
            elif decision == "overturn":
                new_player = opposite(entry.awarded_to)
                self._events.append(review_overturned_event(point_id, new_player))
            elif decision == "void":
                self._events.append(point_voided_event(point_id))
            else:
                raise ValueError("decision must be uphold, overturn, or void")

            # Drop stale MATCH_COMPLETED; re-append if still complete after reduction.
            self._events = [
                e for e in self._events if e.event_type != MatchEventType.MATCH_COMPLETED
            ]
            st2 = reduce_match_state(self._events, self._config)
            if st2.match_status == MatchStatus.COMPLETED and st2.winner:
                self._events.append(match_completed_event(st2.winner))
                st2 = reduce_match_state(self._events, self._config)
                self._maybe_persist(st2)

            logger.info("Review %s for point %s", decision, point_id)
            return st2

    def summary(self) -> MatchSummary:
        st = self.state()
        events = self.events
        reviewed = overturned = 0
        clip_ids: list[str] = []
        seen_points: set[str] = set()
        for e in events:
            if e.event_type == MatchEventType.POINT_AWARDED:
                cid = e.payload.get("clip_id")
                if cid:
                    clip_ids.append(str(cid))
            if e.event_type in (
                MatchEventType.REVIEW_UPHELD,
                MatchEventType.REVIEW_OVERTURNED,
                MatchEventType.POINT_VOIDED,
            ):
                pid = str(e.payload.get("point_id"))
                if pid not in seen_points:
                    reviewed += 1
                    seen_points.add(pid)
                if e.event_type == MatchEventType.REVIEW_OVERTURNED:
                    overturned += 1

        duration = None
        if st.started_at and st.ended_at:
            try:
                start = datetime.fromisoformat(st.started_at)
                end = datetime.fromisoformat(st.ended_at)
                duration = (end - start).total_seconds()
            except ValueError:
                duration = None

        winner_name = None
        if st.winner == "A":
            winner_name = st.player_a.name
        elif st.winner == "B":
            winner_name = st.player_b.name

        total_points = sum(1 for t in st.timeline if t.effective_to is not None)

        return MatchSummary(
            winner=st.winner,
            winner_name=winner_name,
            games_a=st.player_a.games,
            games_b=st.player_b.games,
            game_scores=[g.to_dict() for g in st.game_results],
            duration_seconds=duration,
            total_points=total_points,
            reviewed_points=reviewed,
            overturned_calls=overturned,
            timeline=[t.to_dict() for t in st.timeline],
            clip_ids=clip_ids,
        )

    def _latest_reviewable_locked(self, st: MatchState) -> str | None:
        for entry in reversed(st.timeline):
            if entry.review_status in (
                ReviewStatus.NOT_REVIEWED.value,
                ReviewStatus.REVIEW_PENDING.value,
            ):
                return entry.point_id
        return None

    def _attach_clip_async(self, point_id: str, label: str) -> None:
        saver = self.clip_saver
        if saver is None:
            return

        def worker() -> None:
            try:
                meta = saver(label)
            except Exception:
                logger.exception("Clip save failed for point %s", point_id)
                return
            if not meta:
                logger.info("Replay clip unavailable for point %s", point_id)
                return
            with self._lock:
                for event in self._events:
                    if (
                        event.event_type == MatchEventType.POINT_AWARDED
                        and event.payload.get("point_id") == point_id
                    ):
                        event.payload["clip_id"] = meta.get("id")
                        event.payload["clip_path"] = meta.get("path")
                        event.payload["buffer_start_ts"] = meta.get("buffer_start_ts")
                        event.payload["buffer_end_ts"] = meta.get("buffer_end_ts")
                        break

        threading.Thread(target=worker, daemon=True).start()

    def _maybe_persist(self, st: MatchState) -> None:
        if self._saved or self.persistence is None:
            return
        if st.match_status != MatchStatus.COMPLETED:
            return
        self.persistence.save_match(st, list(self._events), self.summary())
        self._saved = True
