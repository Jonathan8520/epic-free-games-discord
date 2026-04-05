"""
auth.py — Gestion automatique des tokens Epic Games via OAuth refresh.

Au lieu de stocker un bearer token éphémère (~8h), on stocke le refresh token
(~1 an) et on obtient un bearer frais à chaque run automatiquement.

Flow :
1. POST refresh_token → Epic OAuth endpoint
2. Récupère access_token (bearer) frais
3. Utilise ce bearer pour toutes les requêtes de ce run
"""

import base64
import requests
from logger import log

# Epic Games OAuth endpoint
TOKEN_URL = "https://account-public-service-prod.ol.epicgames.com/account/api/oauth/token"

# Client credentials du launcher Epic (publiquement documentés, utilisés par
# tous les outils open-source : legendary, heroic, etc.)
_CLIENTS = [
    # Launcher client
    ("34a02cf8f4414e29b15921876da36f9a", "daafbccc737745039dffe53d94fc76cf"),
    # iOS client (fallback)
    ("3446cd72694c4a4485d81b77adbb2141", "9209d4a5e25a457fb9b07489d313b41a"),
]


class Auth:
    """Gère le refresh automatique du bearer token Epic."""

    def __init__(self):
        self._access_token: str = ""
        self._account_id: str = ""
        self._refresh_token: str = ""

    @property
    def bearer_token(self) -> str:
        return self._access_token

    @property
    def account_id(self) -> str:
        return self._account_id

    def refresh(self, refresh_token: str) -> bool:
        """
        Échange le refresh token contre un access token frais.
        Essaie plusieurs clients Epic en cas d'échec.
        Retourne True si le refresh a réussi.
        """
        if not refresh_token:
            log.warning("[AUTH] Pas de refresh token configuré.")
            return False

        for client_id, client_secret in _CLIENTS:
            success = self._try_refresh(refresh_token, client_id, client_secret)
            if success:
                return True

        log.error("[AUTH] Échec du refresh avec tous les clients.")
        return False

    def _try_refresh(self, refresh_token: str, client_id: str, client_secret: str) -> bool:
        """Tente un refresh avec un couple client_id/secret donné."""
        basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()

        try:
            resp = requests.post(
                TOKEN_URL,
                headers={
                    "Authorization": f"Basic {basic}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                timeout=15,
            )

            if resp.status_code == 400:
                body = resp.json()
                error_code = body.get("errorCode", "")
                log.debug(f"[AUTH] Client {client_id[:8]}… refusé : {error_code}")
                return False

            if resp.status_code in (401, 403):
                log.warning(f"[AUTH] Refresh token expiré ou invalide (HTTP {resp.status_code}).")
                return False

            resp.raise_for_status()

            data = resp.json()
            self._access_token = data["access_token"]
            self._account_id = data.get("account_id", "")
            self._refresh_token = data.get("refresh_token", refresh_token)

            expires_in = data.get("expires_in", 0)
            log.info(f"[AUTH] Bearer token obtenu (expire dans {expires_in // 60} min).")
            return True

        except requests.RequestException as e:
            log.error(f"[AUTH] Erreur réseau lors du refresh : {e}")
            return False


# Singleton utilisé par claimer.py et library.py
auth = Auth()
