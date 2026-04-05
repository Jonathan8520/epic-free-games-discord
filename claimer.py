"""
claimer.py — Réclame automatiquement les jeux gratuits Epic Games.

Gère :
- Réclamation via cookies de session
- Retry automatique (jusqu'à CLAIM_RETRIES tentatives)
- Détection cookies expirés (401/403)
- Détection EULA non acceptée
- Détection captcha
- Jeu déjà possédé (400 + "owned")
"""

import time
import requests
from config import cfg
from auth import auth
from logger import log

ORDER_URL = "https://store.epicgames.com/api/order/v3/orders/public/orders"
EULA_URL  = "https://eulatracking-public-service-prod.ol.epicgames.com/eulatracking/api/public/agreements/fn/{namespace}/account/{account_id}/accept?locale=fr"

class ClaimResult:
    SUCCESS       = "success"
    OWNED         = "owned"
    FAILED        = "failed"
    EXPIRED       = "expired"
    EULA_REQUIRED = "eula_required"
    CAPTCHA       = "captcha"


def _headers() -> dict:
    # Préfère le token rafraîchi automatiquement, sinon fallback sur le token manuel
    token = auth.bearer_token or cfg.BEARER_TOKEN
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type" : "application/json",
        "User-Agent"   : (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Origin" : "https://store.epicgames.com",
        "Referer": "https://store.epicgames.com/",
    }


def _cookies() -> dict:
    # Avec un token rafraîchi via OAuth, le cookie SESSION_AP n'est pas nécessaire
    if auth.bearer_token:
        return {}
    return {"EPIC_SESSION_AP": cfg.SESSION_AP}


def _attempt_claim(game: dict) -> tuple[str, str]:
    """
    Tente une réclamation.
    Retourne (ClaimResult, message_erreur).
    """
    payload = {
        "offers"     : [{"namespace": game["namespace"], "id": game["id"], "quantity": 1}],
        "useDefault" : True,
        "setDefault" : False,
        "totalAmount": 0,
        "orderId"    : None,
        "sessionUUID": None,
        "syncToken"  : None,
    }

    try:
        resp = requests.post(
            ORDER_URL,
            json    = payload,
            headers = _headers(),
            cookies = _cookies(),
            timeout = 20,
        )

        body = resp.text.lower()

        if resp.status_code == 200:
            order_status = resp.json().get("orderStatus", "")
            if order_status in ("COMPLETED", "RECORDED"):
                return ClaimResult.SUCCESS, ""
            return ClaimResult.FAILED, f"orderStatus inattendu : {order_status}"

        if resp.status_code in (401, 403):
            return ClaimResult.EXPIRED, f"HTTP {resp.status_code}"

        if resp.status_code == 400:
            if "already" in body or "owned" in body:
                return ClaimResult.OWNED, ""
            if "eula" in body or "agreement" in body:
                return ClaimResult.EULA_REQUIRED, "EULA non acceptée"
            if "captcha" in body or "verification" in body or "one more step" in body:
                return ClaimResult.CAPTCHA, "Captcha détecté"

        return ClaimResult.FAILED, f"HTTP {resp.status_code} : {resp.text[:200]}"

    except requests.RequestException as e:
        return ClaimResult.FAILED, f"Erreur réseau : {e}"


def claim_game(game: dict) -> tuple[str, str]:
    """
    Tente de réclamer un jeu avec retry automatique.

    Retourne (ClaimResult, error_message).
    Les erreurs EXPIRED, EULA_REQUIRED, CAPTCHA ne sont pas retentées.
    """
    title = game.get("title", "?")

    if not game.get("namespace") or not game.get("id"):
        log.warning(f"[CLAIMER] Infos manquantes pour {title}")
        return ClaimResult.FAILED, "Namespace ou ID manquant"

    for attempt in range(1, cfg.CLAIM_RETRIES + 1):
        log.info(f"[CLAIMER] {title} — tentative {attempt}/{cfg.CLAIM_RETRIES}")
        result, error = _attempt_claim(game)

        if result == ClaimResult.SUCCESS:
            log.info(f"[CLAIMER] ✅ {title} réclamé avec succès !")
            return result, ""

        if result == ClaimResult.OWNED:
            log.info(f"[CLAIMER] ℹ️  {title} déjà possédé.")
            return result, ""

        if result in (ClaimResult.EXPIRED, ClaimResult.EULA_REQUIRED, ClaimResult.CAPTCHA):
            log.warning(f"[CLAIMER] {result} pour {title} — pas de retry.")
            return result, error

        log.warning(f"[CLAIMER] Échec tentative {attempt} pour {title} : {error}")
        if attempt < cfg.CLAIM_RETRIES:
            log.info(f"[CLAIMER] Attente {cfg.CLAIM_RETRY_DELAY}s avant retry...")
            time.sleep(cfg.CLAIM_RETRY_DELAY)

    return ClaimResult.FAILED, f"Échec après {cfg.CLAIM_RETRIES} tentatives"
