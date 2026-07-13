"""JSON persistence for completed matches."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src.scoring.events import MatchEvent
from src.scoring.models import MatchState, MatchSummary

logger = logging.getLogger(__name__)


class MatchPersistence:
    """Lightweight JSON store under ``data/matches``."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    def save_match(
        self,
        state: MatchState,
        events: list[MatchEvent],
        summary: MatchSummary,
    ) -> Path:
        match_id = state.match_id or "unknown"
        path = self.directory / f"{match_id}.json"
        payload: dict[str, Any] = {
            "match_id": match_id,
            "player_a": state.player_a.name,
            "player_b": state.player_b.name,
            "best_of": state.best_of,
            "started_at": state.started_at,
            "ended_at": state.ended_at,
            "winner": state.winner,
            "state": state.to_dict(),
            "summary": summary.to_dict(),
            "events": [e.to_dict() for e in events],
            "game_results": [g.to_dict() for g in state.game_results],
            "clip_references": summary.clip_ids,
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info("Saved match record to %s", path)
        return path

    def list_matches(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for path in sorted(self.directory.glob("*.json"), reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                items.append(
                    {
                        "match_id": data.get("match_id"),
                        "player_a": data.get("player_a"),
                        "player_b": data.get("player_b"),
                        "winner": data.get("winner"),
                        "best_of": data.get("best_of"),
                        "started_at": data.get("started_at"),
                        "ended_at": data.get("ended_at"),
                        "path": str(path),
                    }
                )
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Skipping corrupt match file %s: %s", path, exc)
        return items

    def load_match(self, match_id: str) -> dict[str, Any] | None:
        path = self.directory / f"{match_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
