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


def _bool(key: str, default: bool = False) -> bool:
    return os.getenv(key, str(default)).lower() in ("true", "1", "yes")


class Config:
    DISCORD_WEBHOOK : str = _require("DISCORD_WEBHOOK")
    ROLE_ID         : str = _optional("ROLE_ID")
    ALERT_WEBHOOK   : str = _optional("ALERT_WEBHOOK")  # Salon séparé pour les alertes techniques

    GITHUB_REPO     : str = _optional("GITHUB_REPOSITORY")
    STATE_FILE      : str = "state.json"

    # Auto-claim Epic (optionnel) — voir reference_autoclaim_endpoint
    AUTO_CLAIM         : bool = _bool("AUTO_CLAIM", False)
    EPIC_REFRESH_TOKEN : str  = _optional("EPIC_REFRESH_TOKEN")
    GH_PAT             : str  = _optional("GH_PAT")  # PAT pour updater EPIC_REFRESH_TOKEN après rotation

    @property
    def alert_webhook(self) -> str:
        return self.ALERT_WEBHOOK or self.DISCORD_WEBHOOK

    @property
    def can_claim(self) -> bool:
        """Vrai si toutes les conditions sont réunies pour tenter l'auto-claim."""
        return self.AUTO_CLAIM and bool(self.EPIC_REFRESH_TOKEN) and bool(self.GH_PAT) and bool(self.GITHUB_REPO)


cfg = Config()
