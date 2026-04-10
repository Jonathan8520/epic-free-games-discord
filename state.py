"""
state.py — Gestion de l'état persistant.

Structure de state.json :
{
  "games": {
    "<game_id>": {
      "title": "...",
      "url":   "...",
      "notified_at": "ISO8601",
      "value":       "19.99 €" | null
    }
  },
  "last_check": "ISO8601"
}
"""

import json
import os
from datetime import datetime, timezone
from logger import log


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class State:
    def __init__(self, path: str):
        self.path = path
        self._data: dict = self._load()

    def _load(self) -> dict:
        if os.path.exists(self.path):
            try:
                with open(self.path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                log.warning(f"state.json corrompu, réinitialisation ({e})")
        return {
            "games": {},
            "last_check": None,
        }

    def save(self):
        self._data["last_check"] = _now()
        with open(self.path, "w") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)
        log.debug("state.json sauvegardé.")

    def is_notified(self, game_id: str) -> bool:
        return game_id in self._data["games"]

    def mark_notified(self, game: dict):
        self._data["games"][game["id"]] = {
            "title"      : game["title"],
            "url"        : game.get("url", ""),
            "notified_at": _now(),
            "value"      : game.get("original_price"),
        }

    def remove(self, game_id: str):
        self._data["games"].pop(game_id, None)
