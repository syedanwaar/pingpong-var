"""Automated tests for event-sourced table-tennis match scoring."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.scoring.events import MatchEventType, point_awarded_event
from src.scoring.models import MatchConfig, MatchStatus, PhysicalEnd
from src.scoring.persistence import MatchPersistence
from src.scoring.reducer import reduce_match_state
from src.scoring.rules import server_for_score
from src.scoring.service import MatchService


def _play_to(svc: MatchService, sequence: str) -> None:
    for ch in sequence:
        svc.award_point(ch, attach_replay=False)


def test_normal_11_7_game():
    svc = MatchService()
    svc.start_match("Aname", "Bname", best_of=3, first_server="A")
    _play_to(svc, "A" * 11 + "B" * 0)
    # Need exactly 11-7: 11 A and 7 B interleaved isn't needed for game end;
    # award 7 B then more A... actually 11-0 also wins. Spec wants 11-7.
    svc = MatchService()
    svc.start_match("Aname", "Bname", best_of=3, first_server="A")
    for _ in range(7):
        svc.award_point("A", attach_replay=False)
        svc.award_point("B", attach_replay=False)
    for _ in range(4):
        svc.award_point("A", attach_replay=False)
    st = svc.state()
    assert st.game_results[0].score_a == 11
    assert st.game_results[0].score_b == 7
    assert st.player_a.games == 1


def test_deuce_14_12():
    svc = MatchService()
    svc.start_match("A", "B", best_of=3, first_server="A")
    for _ in range(10):
        svc.award_point("A", attach_replay=False)
        svc.award_point("B", attach_replay=False)
    # 10-10 → 11-10 → 11-11 → 12-11 → 12-12 → 13-12 → 14-12
    svc.award_point("A", attach_replay=False)
    svc.award_point("B", attach_replay=False)
    svc.award_point("A", attach_replay=False)
    svc.award_point("B", attach_replay=False)
    svc.award_point("A", attach_replay=False)
    svc.award_point("A", attach_replay=False)
    st = svc.state()
    assert st.game_results[0].score_a == 14
    assert st.game_results[0].score_b == 12


def test_serve_changes_every_two_points():
    assert server_for_score(0, 0, "A") == "A"
    assert server_for_score(1, 0, "A") == "A"
    assert server_for_score(2, 0, "A") == "B"
    assert server_for_score(3, 1, "A") == "A"  # total 4 → next pair, starting server
    assert server_for_score(4, 2, "A") == "B"


def test_serve_changes_every_point_after_deuce():
    assert server_for_score(10, 10, "A") == "A"
    assert server_for_score(11, 10, "A") == "B"
    assert server_for_score(11, 11, "A") == "A"
    assert server_for_score(12, 11, "A") == "B"


def test_starting_server_alternates_between_games():
    svc = MatchService()
    svc.start_match("A", "B", best_of=5, first_server="A")
    for _ in range(11):
        svc.award_point("A", attach_replay=False)
    st = svc.state()
    assert st.current_game == 2
    assert st.starting_server_for_current_game == "B"
    assert st.current_server == "B"


def test_ends_switch_after_each_game():
    svc = MatchService()
    svc.start_match("A", "B", best_of=5, first_server="A")
    assert svc.state().player_a.physical_end == PhysicalEnd.LEFT
    for _ in range(11):
        svc.award_point("A", attach_replay=False)
    st = svc.state()
    assert st.player_a.physical_end == PhysicalEnd.RIGHT
    assert st.player_b.physical_end == PhysicalEnd.LEFT


def test_deciding_game_end_switch_at_5():
    svc = MatchService()
    svc.start_match("A", "B", best_of=3, first_server="A")
    # Split first two games → deciding game 3
    for _ in range(11):
        svc.award_point("A", attach_replay=False)
    for _ in range(11):
        svc.award_point("B", attach_replay=False)
    st = svc.state()
    assert st.current_game == 3
    assert st.is_deciding_game()
    end_a_before = st.player_a.physical_end
    for _ in range(5):
        svc.award_point("A", attach_replay=False)
    st = svc.state()
    assert st.deciding_game_end_switched is True
    assert st.player_a.physical_end != end_a_before


def test_best_of_3_completion():
    svc = MatchService()
    svc.start_match("A", "B", best_of=3, first_server="A")
    for _ in range(11):
        svc.award_point("A", attach_replay=False)
    for _ in range(11):
        svc.award_point("A", attach_replay=False)
    st = svc.state()
    assert st.match_status == MatchStatus.COMPLETED
    assert st.winner == "A"
    assert st.player_a.games == 2


def test_best_of_5_completion():
    svc = MatchService()
    svc.start_match("A", "B", best_of=5, first_server="A")
    for _ in range(3):
        for _ in range(11):
            svc.award_point("B", attach_replay=False)
    st = svc.state()
    assert st.winner == "B"
    assert st.player_b.games == 3


def test_best_of_7_completion():
    svc = MatchService()
    svc.start_match("A", "B", best_of=7, first_server="A")
    for _ in range(4):
        for _ in range(11):
            svc.award_point("A", attach_replay=False)
    st = svc.state()
    assert st.winner == "A"
    assert st.player_a.games == 4


def test_undo_normal_point():
    svc = MatchService()
    svc.start_match("A", "B", best_of=3, first_server="A")
    svc.award_point("A", attach_replay=False)
    svc.award_point("B", attach_replay=False)
    svc.undo()
    st = svc.state()
    assert st.player_a.points == 1
    assert st.player_b.points == 0


def test_undo_game_winning_point():
    svc = MatchService()
    svc.start_match("A", "B", best_of=5, first_server="A")
    for _ in range(11):
        svc.award_point("A", attach_replay=False)
    assert svc.state().player_a.games == 1
    svc.undo()
    st = svc.state()
    assert st.player_a.games == 0
    assert st.player_a.points == 10
    assert st.current_game == 1


def test_undo_match_winning_point():
    svc = MatchService()
    svc.start_match("A", "B", best_of=3, first_server="A")
    for _ in range(22):
        svc.award_point("A", attach_replay=False)
    assert svc.state().match_status == MatchStatus.COMPLETED
    svc.undo()
    st = svc.state()
    assert st.match_status == MatchStatus.IN_PROGRESS
    assert st.player_a.games == 1


def test_overturn_normal_point():
    svc = MatchService()
    svc.start_match("A", "B", best_of=3, first_server="A")
    svc.award_point("A", attach_replay=False)
    svc.request_review()
    svc.resolve_review("overturn")
    st = svc.state()
    assert st.player_a.points == 0
    assert st.player_b.points == 1
    assert st.timeline[0].review_status == "overturned"


def test_overturn_game_winning_point():
    svc = MatchService()
    svc.start_match("A", "B", best_of=5, first_server="A")
    for _ in range(11):
        svc.award_point("A", attach_replay=False)
    assert svc.state().player_a.games == 1
    svc.request_review()
    svc.resolve_review("overturn")
    st = svc.state()
    assert st.player_a.games == 0
    assert st.player_a.points == 10
    assert st.player_b.points == 1


def test_overturn_match_winning_point():
    svc = MatchService()
    svc.start_match("A", "B", best_of=3, first_server="A")
    for _ in range(22):
        svc.award_point("A", attach_replay=False)
    assert svc.state().match_status == MatchStatus.COMPLETED
    svc.request_review()
    svc.resolve_review("overturn")
    st = svc.state()
    assert st.match_status == MatchStatus.IN_PROGRESS
    assert st.player_a.games == 1


def test_void_point():
    svc = MatchService()
    svc.start_match("A", "B", best_of=3, first_server="A")
    svc.award_point("A", attach_replay=False)
    svc.request_review()
    svc.resolve_review("void")
    st = svc.state()
    assert st.player_a.points == 0
    assert st.timeline[0].review_status == "voided"


def test_uphold_point():
    svc = MatchService()
    svc.start_match("A", "B", best_of=3, first_server="A")
    svc.award_point("A", attach_replay=False)
    svc.request_review()
    svc.resolve_review("uphold")
    st = svc.state()
    assert st.player_a.points == 1
    assert st.timeline[0].review_status == "upheld"


def test_rebuild_does_not_duplicate_game_events():
    svc = MatchService()
    svc.start_match("A", "B", best_of=5, first_server="A")
    for _ in range(11):
        svc.award_point("A", attach_replay=False)
    events = svc.events
    st1 = reduce_match_state(events)
    st2 = reduce_match_state(events)
    assert len(st1.game_results) == len(st2.game_results) == 1
    assert sum(1 for e in events if e.event_type == MatchEventType.POINT_AWARDED) == 11


def test_no_points_after_match_completion():
    svc = MatchService()
    svc.start_match("A", "B", best_of=3, first_server="A")
    for _ in range(22):
        svc.award_point("A", attach_replay=False)
    with pytest.raises(RuntimeError, match="complete"):
        svc.award_point("A", attach_replay=False)


def test_new_match_resets_state():
    svc = MatchService()
    svc.start_match("A", "B", best_of=3, first_server="A")
    svc.award_point("A", attach_replay=False)
    svc.new_match()
    st = svc.state()
    assert st.match_status == MatchStatus.NOT_STARTED
    assert svc.events == []


def test_missing_replay_clip_does_not_crash_review(tmp_path: Path):
    def fail_clip(_label: str):
        return None

    svc = MatchService(clip_saver=fail_clip)
    svc.start_match("A", "B", best_of=3, first_server="A")
    svc.award_point("A", attach_replay=True)
    st = svc.request_review()
    assert st.pending_review_point_id is not None
    entry = st.timeline[-1]
    assert entry.replay_available is False
    svc.resolve_review("uphold")
    assert svc.state().player_a.points == 1


def test_persistence_saves_completed_match(tmp_path: Path):
    store = MatchPersistence(tmp_path)
    svc = MatchService(persistence=store)
    svc.start_match("Anwaar", "Opponent", best_of=3, first_server="A")
    for _ in range(22):
        svc.award_point("A", attach_replay=False)
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["winner"] == "A"
    assert data["player_a"] == "Anwaar"
    assert "events" in data
