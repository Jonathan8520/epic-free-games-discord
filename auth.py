"""
auth.py — Gestion automatique des tokens Epic Games via OAuth refresh.

Le bot stocke un refresh token du **client launcher Epic** (généré une fois
via bootstrap.py), qui dure ~1 an. À chaque run, on l'échange contre un
access_token (bearer) frais utilisé pour réclamer les jeux.

Note : on n'utilise PAS le refresh token web (REFRESH_EPIC_EG1) car il est
lié au client "dieselweb" dont le secret n'est pas public. Le client launcher
Epic est documenté et utilisé par tous les outils open-source (legendary, etc).
"""

import base64
import requests
from logger import log

# Endpoint OAuth Epic Games
TOKEN_URL = "https://account-public-service-prod.ol.epicgames.com/account/api/oauth/token"

# Client launcher Epic (publiquement documenté)
EPIC_CLIENT_ID     = "34a02cf8f4414e29b15921876da36f9a"
EPIC_CLIENT_SECRET = "daafbccc737745039dffe53d94fc76cf"


def _basic_auth() -> str:
    raw = f"{EPIC_CLIENT_ID}:{EPIC_CLIENT_SECRET}".encode()
    return base64.b64encode(raw).decode()


def exchange_code_for_tokens(authorization_code: str) -> dict:
    """
    Échange un authorization code (one-shot) contre des tokens launcher.
    Utilisé une seule fois par bootstrap.py pour obtenir un refresh token persistant.

    Lève requests.HTTPError en cas d'erreur.
    Retourne le dict complet de la réponse Epic (contient access_token, refresh_token, etc).
    """
    resp = requests.post(
        TOKEN_URL,
        headers={
            "Authorization": f"Basic {_basic_auth()}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "authorization_code",
            "code": authorization_code,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


class Auth:
    """Gère le refresh automatique du bearer token Epic via le client launcher."""

    def __init__(self):
        self._access_token: str = ""
        self._account_id: str = ""

    @property
    def bearer_token(self) -> str:
        return self._access_token

    @property
    def account_id(self) -> str:
        return self._account_id

    def refresh(self, refresh_token: str) -> bool:
        """
        Échange le refresh token (launcher) contre un access token frais.
        Retourne True si le refresh a réussi.
        """
        if not refresh_token:
            log.warning("[AUTH] Pas de refresh token configuré.")
            return False

        try:
            resp = requests.post(
                TOKEN_URL,
                headers={
                    "Authorization": f"Basic {_basic_auth()}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                timeout=15,
            )

            if resp.status_code in (400, 401, 403):
                error_code = ""
                try:
                    error_code = resp.json().get("errorCode", "")
                except Exception:
                    pass
                log.warning(f"[AUTH] Refresh token rejeté (HTTP {resp.status_code}, {error_code}).")
                return False

            resp.raise_for_status()
            data = resp.json()
            self._access_token = data["access_token"]
            self._account_id = data.get("account_id", "")

            expires_in = data.get("expires_in", 0)
            log.info(f"[AUTH] Bearer token obtenu (expire dans {expires_in // 60} min).")
            return True

        except requests.RequestException as e:
            log.error(f"[AUTH] Erreur réseau lors du refresh : {e}")
            return False


# Singleton utilisé par claimer.py et library.py
auth = Auth()
