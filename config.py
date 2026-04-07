"""
config.py — Configuration centralisée.
Toutes les variables d'environnement sont lues ici, une seule fois.
"""

import os

def _require(key: str) -> str:
    val = os.getenv(key, "")
    if not val:
        raise EnvironmentError(f"Variable manquante : {key}")
    return val

def _optional(key: str, default: str = "") -> str:
    val = os.getenv(key, default)
    return val if val else default


class Config:
    DISCORD_WEBHOOK : str = _require("DISCORD_WEBHOOK")
    ROLE_ID         : str = _optional("ROLE_ID")
    ALERT_WEBHOOK   : str = _optional("ALERT_WEBHOOK")  # Salon séparé pour les alertes techniques

    GITHUB_REPO     : str = _optional("GITHUB_REPOSITORY")
    STATE_FILE      : str = "state.json"

    @property
    def alert_webhook(self) -> str:
        return self.ALERT_WEBHOOK or self.DISCORD_WEBHOOK


cfg = Config()
