"""
auth.py — OAuth Epic Games via le client launcher public.

Flux :
1. Bootstrap (une seule fois) : `python bootstrap.py <authorizationCode>` → refresh_token (~1 an)
2. Run : on échange le refresh_token contre un access_token (~8h) utilisé pour le claim API.

⚠️ Epic invalide le refresh_token à chaque usage et en émet un nouveau dans la réponse.
   `refresh()` expose ce nouveau token via `new_refresh_token` ; le caller doit le persister
   (cf gh_secrets.update_epic_refresh_token).
"""

import base64
import requests
from logger import log

TOKEN_URL = "https://account-public-service-prod.ol.epicgames.com/account/api/oauth/token"

# Client launcher Epic — publiquement documenté (legendary, etc.)
EPIC_CLIENT_ID     = "34a02cf8f4414e29b15921876da36f9a"
EPIC_CLIENT_SECRET = "daafbccc737745039dffe53d94fc76cf"


def _basic_auth() -> str:
    raw = f"{EPIC_CLIENT_ID}:{EPIC_CLIENT_SECRET}".encode()
    return base64.b64encode(raw).decode()


def exchange_code_for_tokens(authorization_code: str) -> dict:
    """One-shot bootstrap : échange un authorization code contre les tokens initiaux."""
    resp = requests.post(
        TOKEN_URL,
        headers={
            "Authorization": f"Basic {_basic_auth()}",
            "Content-Type" : "application/x-www-form-urlencoded",
        },
        data={"grant_type": "authorization_code", "code": authorization_code},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


class Auth:
    """Échange un refresh_token contre un access_token frais à chaque run."""

    def __init__(self):
        self._access_token: str       = ""
        self._account_id: str         = ""
        self._new_refresh_token: str  = ""

    @property
    def access_token(self) -> str:
        return self._access_token

    @property
    def account_id(self) -> str:
        return self._account_id

    @property
    def new_refresh_token(self) -> str:
        """Nouveau refresh_token retourné par Epic (l'ancien est mort). À persister."""
        return self._new_refresh_token

    def refresh(self, refresh_token: str) -> bool:
        if not refresh_token:
            log.warning("[AUTH] Pas de refresh token fourni.")
            return False

        try:
            resp = requests.post(
                TOKEN_URL,
                headers={
                    "Authorization": f"Basic {_basic_auth()}",
                    "Content-Type" : "application/x-www-form-urlencoded",
                },
                data={"grant_type": "refresh_token", "refresh_token": refresh_token},
                timeout=15,
            )

            if resp.status_code in (400, 401, 403):
                err = ""
                try:
                    err = resp.json().get("errorCode", "")
                except Exception:
                    pass
                log.error(f"[AUTH] Refresh token rejeté (HTTP {resp.status_code}, {err}).")
                return False

            resp.raise_for_status()
            data = resp.json()

            self._access_token      = data["access_token"]
            self._account_id        = data.get("account_id", "")
            self._new_refresh_token = data.get("refresh_token", "")

            expires_in = data.get("expires_in", 0)
            log.info(f"[AUTH] Access token OK (expire dans {expires_in // 60} min).")
            return True

        except requests.RequestException as e:
            log.error(f"[AUTH] Erreur réseau : {e}")
            return False


auth = Auth()
