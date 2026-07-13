"""Pure table-tennis rule helpers (no event I/O)."""

from __future__ import annotations


def opposite(side: str) -> str:
    return "B" if side == "A" else "A"


def games_required_to_win(best_of: int) -> int:
    return best_of // 2 + 1


def server_for_score(
    points_a: int,
    points_b: int,
    starting_server: str,
    points_to_win: int = 11,
) -> str:
    """Return who serves the next point given the current game score."""
    total = points_a + points_b
    other = opposite(starting_server)
    deuce_threshold = points_to_win - 1
    if points_a >= deuce_threshold and points_b >= deuce_threshold:
        # From 10-10 onward, serve alternates every point.
        # Continuity: at 10-10 the starting server has the next point.
        offset = total - 2 * deuce_threshold
        return starting_server if offset % 2 == 0 else other
    return starting_server if (total // 2) % 2 == 0 else other


def game_winner(
    points_a: int,
    points_b: int,
    points_to_win: int = 11,
    must_win_by: int = 2,
) -> str | None:
    if points_a >= points_to_win and points_a - points_b >= must_win_by:
        return "A"
    if points_b >= points_to_win and points_b - points_a >= must_win_by:
        return "B"
    return None


def is_deciding_game(games_a: int, games_b: int, best_of: int) -> bool:
    return games_a + games_b == best_of - 1
