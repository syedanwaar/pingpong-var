"""Backward-compatible facade over MatchService."""

from __future__ import annotations

from typing import Any

from src.scoring.service import MatchService


class Scoreboard:
    """
    Legacy Scoreboard API used by older code paths.

    Prefer ``MatchService`` for new code.
    """

    def __init__(
        self,
        player_a: str = "Player A",
        player_b: str = "Player B",
        points_to_win: int = 11,
        must_win_by: int = 2,
        service: MatchService | None = None,
    ) -> None:
        self.service = service or MatchService()
        self.points_to_win = points_to_win
        self.must_win_by = must_win_by
        self._names = (player_a, player_b)

    @property
    def player_a(self) -> str:
        return self.service.state().player_a.name

    @player_a.setter
    def player_a(self, value: str) -> None:
        self._names = (value, self._names[1])

    @property
    def player_b(self) -> str:
        return self.service.state().player_b.name

    @player_b.setter
    def player_b(self, value: str) -> None:
        self._names = (self._names[0], value)

    def point(self, side: str, reason: str = "") -> dict[str, Any]:
        self.service.award_point(side, source="manual", reason=reason, attach_replay=False)
        return {"type": "point", "side": side.upper(), "reason": reason, "score": self.snapshot()}

    def undo(self) -> dict[str, Any] | None:
        before = len(self.service.events)
        self.service.undo()
        after = len(self.service.events)
        if after >= before:
            return None
        return {"undone": True, "score": self.snapshot()}

    def reset_game(self) -> None:
        # Not supported as a pure event; undo points of current game instead.
        st = self.service.state()
        while st.player_a.points or st.player_b.points:
            self.service.undo()
            st = self.service.state()

    def reset_match(self) -> None:
        self.service.new_match()

    def snapshot(self) -> dict[str, Any]:
        return self.service.snapshot()
