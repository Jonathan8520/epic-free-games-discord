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
  "api_down":   true,          # présent seulement pendant une panne de l'API Epic
  "updated_at": "ISO8601"      # dernière modification du fichier
}

Le fichier n'est réécrit que s'il a changé : le workflow tourne toutes les
20 min, inutile de pousser un commit sur la branche datas à chaque run.
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
        self._dirty = False
        self._data: dict = self._load()

    def _load(self) -> dict:
        if os.path.exists(self.path):
            try:
                with open(self.path) as f:
                    data = json.load(f)
                data.setdefault("games", {})
                return data
            except (json.JSONDecodeError, IOError) as e:
                log.warning(f"state.json corrompu, réinitialisation ({e})")
        self._dirty = True
        return {"games": {}}

    def save(self):
        if not self._dirty:
            log.debug("state.json inchangé, rien à écrire.")
            return
        self._data.pop("last_check", None)  # ancien champ du scheduler supprimé
        self._data["updated_at"] = _now()
        with open(self.path, "w") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)
        self._dirty = False
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
        self._dirty = True

    def remove(self, game_id: str):
        if self._data["games"].pop(game_id, None) is not None:
            self._dirty = True

    def set_api_down(self, down: bool) -> bool:
        """Mémorise si l'API Epic est en panne. Retourne True seulement au
        moment où elle tombe, pour n'envoyer qu'une alerte par panne au lieu
        d'une toutes les 20 min."""
        was_down = bool(self._data.get("api_down"))
        if down != was_down:
            if down:
                self._data["api_down"] = True
            else:
                self._data.pop("api_down", None)
            self._dirty = True
        return down and not was_down
