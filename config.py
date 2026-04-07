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

def _bool(key: str, default: bool = True) -> bool:
    return os.getenv(key, str(default)).lower() in ("true", "1", "yes")

class Config:
    DISCORD_WEBHOOK   : str  = _require("DISCORD_WEBHOOK")
    ROLE_ID           : str  = _optional("ROLE_ID")
    ALERT_WEBHOOK     : str  = _optional("ALERT_WEBHOOK")  # Salon séparé pour les alertes techniques

    AUTO_CLAIM        : bool = _bool("AUTO_CLAIM", True)
    BEARER_TOKEN      : str  = _optional("EPIC_BEARER_TOKEN")
    SESSION_AP        : str  = _optional("EPIC_SESSION_AP")
    REFRESH_TOKEN     : str  = _optional("EPIC_REFRESH_TOKEN")

    CLAIM_RETRIES     : int  = int(_optional("CLAIM_RETRIES", "3"))
    CLAIM_RETRY_DELAY : int  = int(_optional("CLAIM_RETRY_DELAY", "30"))  # secondes

    GITHUB_REPO       : str  = _optional("GITHUB_REPOSITORY")
    STATE_FILE        : str  = "state.json"

    @property
    def secrets_url(self) -> str:
        if self.GITHUB_REPO:
            return f"https://github.com/{self.GITHUB_REPO}/settings/secrets/actions"
        return "https://github.com"

    @property
    def can_claim(self) -> bool:
        return self.AUTO_CLAIM and (bool(self.REFRESH_TOKEN) or (bool(self.BEARER_TOKEN) and bool(self.SESSION_AP)))

    @property
    def alert_webhook(self) -> str:
        return self.ALERT_WEBHOOK or self.DISCORD_WEBHOOK

cfg = Config()
