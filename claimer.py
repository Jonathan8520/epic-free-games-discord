"""
claimer.py — Réclame un jeu Epic gratuit via l'endpoint egs-platform-service.

Validé le 2026-05-17 : pas de captcha, accepte un Bearer access_token launcher.
Voir test_claim.py pour le script de test isolé qui a découvert ce flow.
"""

import requests
from logger import log

CLAIM_URL   = "https://egs-platform-service.store.epicgames.com/api/v2/private/egs/purchase/quickPurchase"
GRAPHQL_URL = "https://store.epicgames.com/graphql"

PRICE_QUERY = """
query getOfferPrice($namespace: String!, $offerId: String!) {
  Catalog {
    catalogOffer(namespace: $namespace, id: $offerId) {
      price(country: "FR") {
        totalPrice { discountPrice }
      }
    }
  }
}
"""

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class ClaimResult:
    SUCCESS      = "success"
    OWNED        = "owned"          # REACHED_PURCHASE_LIMIT
    EULA         = "eula_required"
    FAILED       = "failed"
    UNAUTHORIZED = "unauthorized"   # access_token périmé ou rejeté
    NOT_FREE     = "not_free"       # Garde-fou : offer pas à 0€ au moment du claim


def _is_free(namespace: str, offer_id: str) -> bool:
    """
    Garde-fou : vérifie via GraphQL Epic que l'offer est bien à 0€ juste avant le claim.
    En cas de doute (erreur réseau, prix absent), retourne False pour bloquer le claim.
    """
    try:
        r = requests.post(
            GRAPHQL_URL,
            json={"query": PRICE_QUERY, "variables": {"namespace": namespace, "offerId": offer_id}},
            headers={"Content-Type": "application/json", "User-Agent": UA},
            timeout=10,
        )
        r.raise_for_status()
        offer = (r.json().get("data") or {}).get("Catalog", {}).get("catalogOffer") or {}
        discount = (offer.get("price") or {}).get("totalPrice", {}).get("discountPrice")
    except (requests.RequestException, ValueError) as e:
        log.warning(f"[CLAIM] Vérif prix échouée ({e}) — skip par sécurité.")
        return False

    if discount is None:
        log.warning("[CLAIM] Prix absent de la réponse — skip par sécurité.")
        return False
    return discount == 0


def claim_game(access_token: str, namespace: str, offer_id: str, title: str = "?") -> tuple[str, str]:
    """
    Tente de réclamer (namespace, offer_id). Retourne (ClaimResult, message).
    Vérifie d'abord que l'offer est à 0€ (garde-fou).
    """
    if not (access_token and namespace and offer_id):
        return ClaimResult.FAILED, "Paramètres manquants"

    if not _is_free(namespace, offer_id):
        log.warning(f"[CLAIM] {title} : garde-fou prix — claim refusé.")
        return ClaimResult.NOT_FREE, "Garde-fou : offer != 0€"

    payload = {
        "country"     : "FR",
        "locale"      : "fr",
        "lineOffers"  : [{"offerId": offer_id, "namespace": namespace}],
        "salesChannel": "Windows-Store-EGSWeb",
    }

    try:
        resp = requests.post(
            CLAIM_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type" : "application/json",
                "User-Agent"   : UA,
                "Origin"       : "https://store.epicgames.com",
                "Referer"      : "https://store.epicgames.com/",
            },
            timeout=20,
        )
    except requests.RequestException as e:
        return ClaimResult.FAILED, f"Erreur réseau : {e}"

    if resp.status_code in (401, 403):
        return ClaimResult.UNAUTHORIZED, f"HTTP {resp.status_code}"

    if resp.status_code != 200:
        return ClaimResult.FAILED, f"HTTP {resp.status_code} : {resp.text[:200]}"

    try:
        status = resp.json().get("quickPurchaseStatus", "")
    except ValueError:
        return ClaimResult.FAILED, f"Réponse non-JSON : {resp.text[:200]}"

    if status == "SUCCESS":
        log.info(f"[CLAIM] ✅ {title} réclamé.")
        return ClaimResult.SUCCESS, ""

    if status == "REACHED_PURCHASE_LIMIT":
        log.info(f"[CLAIM] ℹ️  {title} déjà possédé.")
        return ClaimResult.OWNED, ""

    body = resp.text.lower()
    if "eula" in body or "agreement" in body:
        return ClaimResult.EULA, f"EULA requise (status={status})"

    return ClaimResult.FAILED, f"Status inattendu : {status} — {resp.text[:200]}"
