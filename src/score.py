"""Match score tracking (standard table tennis rules subset)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Scoreboard:
    player_a: str = "Player A"
    player_b: str = "Player B"
    a: int = 0
    b: int = 0
    games_a: int = 0
    games_b: int = 0
    points_to_win: int = 11
    must_win_by: int = 2
    history: list[dict] = field(default_factory=list)
    serving: str = "A"  # A or B

    def point(self, side: str, reason: str = "") -> dict:
        side = side.upper()
        if side == "A":
            self.a += 1
        elif side == "B":
            self.b += 1
        else:
            raise ValueError("side must be A or B")

        event = {
            "type": "point",
            "side": side,
            "reason": reason,
            "score": self.snapshot(),
        }
        self.history.append(event)
        self._maybe_rotate_serve()
        self._maybe_game()
        return event

    def undo(self) -> dict | None:
        if not self.history:
            return None
        last = self.history.pop()
        # rebuild from remaining history
        self.a = self.b = self.games_a = self.games_b = 0
        self.serving = "A"
        kept = list(self.history)
        self.history.clear()
        for ev in kept:
            if ev["type"] == "point":
                self.point(ev["side"], ev.get("reason", ""))
        return last

    def reset_game(self) -> None:
        self.a = self.b = 0
        self.serving = "A"
        self.history.append({"type": "reset_game", "score": self.snapshot()})

    def reset_match(self) -> None:
        self.a = self.b = 0
        self.games_a = self.games_b = 0
        self.serving = "A"
        self.history.clear()

    def _maybe_rotate_serve(self) -> None:
        total = self.a + self.b
        # deuce: alternate every point
        if self.a >= self.points_to_win - 1 and self.b >= self.points_to_win - 1:
            self.serving = "B" if self.serving == "A" else "A"
            return
        if total > 0 and total % 2 == 0:
            self.serving = "B" if self.serving == "A" else "A"

    def _maybe_game(self) -> None:
        if self.a >= self.points_to_win and self.a - self.b >= self.must_win_by:
            self.games_a += 1
            self.a = self.b = 0
            self.history.append({"type": "game", "winner": "A", "score": self.snapshot()})
        elif self.b >= self.points_to_win and self.b - self.a >= self.must_win_by:
            self.games_b += 1
            self.a = self.b = 0
            self.history.append({"type": "game", "winner": "B", "score": self.snapshot()})

    def snapshot(self) -> dict:
        return {
            "player_a": self.player_a,
            "player_b": self.player_b,
            "a": self.a,
            "b": self.b,
            "games_a": self.games_a,
            "games_b": self.games_b,
            "serving": self.serving,
            "points_to_win": self.points_to_win,
            "must_win_by": self.must_win_by,
        }
