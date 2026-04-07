"""
state.py — Gestion complète de l'état persistant.

Structure de state.json :
{
  "games": {
    "<game_id>": {
      "title": "...",
      "status": "notified" | "claimed" | "failed" | "owned" | "eula_required" | "captcha",
      "notified_at": "ISO8601",
      "claimed_at":  "ISO8601" | null,
      "retries":     0,
      "last_error":  "..." | null,
      "value":       "19.99 €" | null
    }
  },
  "cookies_expired": false,
  "last_check": "ISO8601",
  "heartbeat_sent_week": "2024-W03" | null,
  "total_saved_eur": 0.0
}
"""

import json
import os
from datetime import datetime, timezone
from typing import Literal
from logger import log

GameStatus = Literal["notified", "claimed", "failed", "owned", "eula_required", "captcha"]

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _week() -> str:
    return datetime.now(timezone.utc).strftime("%Y-W%W")

def _parse_price(price_str: str | None) -> float:
    if not price_str:
        return 0.0
    cleaned = price_str.replace(",", ".").replace(" ", "")
    import re
    m = re.search(r"[\d.]+", cleaned)
    return float(m.group()) if m else 0.0


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
            "cookies_expired": False,
            "last_check": None,
            "heartbeat_sent_week": None,
            "total_saved_eur": 0.0,
        }

    def save(self):
        self._data["last_check"] = _now()
        with open(self.path, "w") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)
        log.debug("state.json sauvegardé.")

    # ── Jeux ────────────────────────────────────────────────

    def get_game(self, game_id: str) -> dict | None:
        return self._data["games"].get(game_id)

    def is_notified(self, game_id: str) -> bool:
        return game_id in self._data["games"]

    def is_claimed(self, game_id: str) -> bool:
        g = self.get_game(game_id)
        return g is not None and g["status"] in ("claimed", "owned")

    def needs_retry(self, game_id: str) -> bool:
        g = self.get_game(game_id)
        if g is None:
            return False
        return g["status"] in ("failed",) and g.get("retries", 0) < 3

    def pending_claim(self) -> list[dict]:
        """Retourne les jeux notifiés mais pas encore réclamés (y compris en échec à retenter)."""
        result = []
        for gid, g in self._data["games"].items():
            if g["status"] in ("notified", "failed") and g.get("retries", 0) < 3:
                result.append({**g, "id": gid})
        return result

    def mark_notified(self, game: dict):
        self._data["games"][game["id"]] = {
            "title"       : game["title"],
            "namespace"   : game.get("namespace", ""),
            "url"         : game.get("url", ""),
            "status"      : "notified",
            "notified_at" : _now(),
            "claimed_at"  : None,
            "retries"     : 0,
            "last_error"  : None,
            "value"       : game.get("original_price"),
        }

    def mark_claimed(self, game_id: str):
        g = self._data["games"].get(game_id, {})
        g["status"]     = "claimed"
        g["claimed_at"] = _now()
        g["last_error"] = None
        price = _parse_price(g.get("value"))
        self._data["total_saved_eur"] = round(
            self._data.get("total_saved_eur", 0.0) + price, 2
        )
        self._data["games"][game_id] = g

    def mark_owned(self, game_id: str):
        g = self._data["games"].get(game_id, {})
        g["status"]     = "owned"
        g["claimed_at"] = _now()
        self._data["games"][game_id] = g

    def mark_failed(self, game_id: str, error: str):
        g = self._data["games"].get(game_id, {})
        g["status"]     = "failed"
        g["retries"]    = g.get("retries", 0) + 1
        g["last_error"] = error
        self._data["games"][game_id] = g

    def mark_eula(self, game_id: str):
        g = self._data["games"].get(game_id, {})
        g["status"] = "eula_required"
        self._data["games"][game_id] = g

    def mark_captcha(self, game_id: str):
        g = self._data["games"].get(game_id, {})
        g["status"] = "captcha"
        self._data["games"][game_id] = g

    # ── Cookies ─────────────────────────────────────────────

    @property
    def cookies_expired(self) -> bool:
        return self._data.get("cookies_expired", False)

    def set_cookies_expired(self, val: bool):
        self._data["cookies_expired"] = val

    # ── Heartbeat ───────────────────────────────────────────

    def needs_heartbeat(self) -> bool:
        return self._data.get("heartbeat_sent_week") != _week()

    def mark_heartbeat(self):
        self._data["heartbeat_sent_week"] = _week()

    # ── Stats ───────────────────────────────────────────────

    def summary(self) -> dict:
        games      = self._data["games"]
        claimed    = [g for g in games.values() if g["status"] == "claimed"]
        failed     = [g for g in games.values() if g["status"] == "failed"]
        eula       = [g for g in games.values() if g["status"] == "eula_required"]
        captcha    = [g for g in games.values() if g["status"] == "captcha"]
        return {
            "total_claimed"  : len(claimed),
            "total_failed"   : len(failed),
            "total_eula"     : len(eula),
            "total_captcha"  : len(captcha),
            "total_saved_eur": self._data.get("total_saved_eur", 0.0),
            "last_check"     : self._data.get("last_check"),
        }
