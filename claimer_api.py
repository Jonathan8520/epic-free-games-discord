"""
claimer_api.py — Auto-claim Epic via API pure (sans browser, sans Cloudflare).

Flow découvert dans le HAR du 2026-05-31 :
  1. Resolve slug → namespace/offerId via GraphQL store.epicgames.com
  2. Generate purchaseToken (UUID hex)
  3. Talon /v1/init → récupère la siteKey hCaptcha (dynamique au cas où Epic change)
  4. CapMonster résout le hCaptcha → captchaToken
  5. POST payment-website-pci/v2/purchase/confirm-order avec captchaToken → SUCCESS

Endpoints utilisés (pas sur Cloudflare !) :
  - store.epicgames.com/graphql                                 (Cloudflare mais Bearer cookies OK)
  - talon-service-prod.ecosec.on.epicgames.com/v1/init          (pas Cloudflare)
  - payment-website-pci.ol.epicgames.com/v2/purchase/confirm-order (pas Cloudflare)
"""

import base64
import json
import os
import re
import time
import uuid
from pathlib import Path

import requests
from logger import log

CAPMONSTER_URL = "https://api.capmonster.cloud"
TALON_INIT_URL = "https://talon-service-prod.ecosec.on.epicgames.com/v1/init"
CONFIRM_ORDER_URL = "https://payment-website-pci.ol.epicgames.com/v2/purchase/confirm-order"
GRAPHQL_URL = "https://store.epicgames.com/graphql"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36")

SANDBOX_QUERY = """
query getSandbox($pageSlug: String!) {
  StorePageMapping {
    mapping(pageSlug: $pageSlug) {
      sandboxId
    }
  }
}
"""

CATALOG_NS_QUERY = """
query getCatalogNs($namespace: String!) {
  Catalog {
    catalogNs(namespace: $namespace) {
      mappings { pageSlug mappings { offerId } }
    }
  }
}
"""

CATALOG_OFFERS_QUERY = """
query getCatalogOffers($namespace: String!) {
  Catalog {
    catalogOffers(namespace: $namespace) {
      elements {
        id title offerType
        price(country: "FR") { totalPrice { discountPrice } }
      }
    }
  }
}
"""


class ClaimOutcome:
    SUCCESS    = "success"
    OWNED      = "owned"
    CAPTCHA    = "captcha"        # CapMonster a foiré
    NOT_FREE   = "not_free"       # offer pas à 0€
    FAILED     = "failed"


def _session_with_cookies(storage_state_b64: str) -> requests.Session:
    """Charge les cookies du storage_state base64 dans une session requests."""
    state = json.loads(base64.b64decode(storage_state_b64.strip()))
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8"})
    for c in state.get("cookies", []):
        s.cookies.set(
            name=c["name"],
            value=c["value"],
            domain=c["domain"].lstrip("."),
            path=c.get("path", "/"),
        )
    return s


def _resolve_slug(slug_or_url: str) -> tuple[str, str] | None:
    """Résout slug → (namespace, offer_id) via GraphQL Epic en anonyme
    (catalogOffers refuse les sessions authentifiées avec 401)."""
    m = re.search(r"/p/([^/?#]+)", slug_or_url)
    slug = m.group(1) if m else slug_or_url
    headers = {"Content-Type": "application/json", "User-Agent": UA}

    # 1. pageSlug → sandboxId (namespace)
    r = requests.post(GRAPHQL_URL, headers=headers,
                      json={"query": SANDBOX_QUERY, "variables": {"pageSlug": slug},
                            "operationName": "getSandbox"},
                      timeout=15)
    r.raise_for_status()
    mapping = (r.json().get("data") or {}).get("StorePageMapping", {}).get("mapping") or {}
    namespace = mapping.get("sandboxId")
    if not namespace:
        log.warning(f"[CLAIM] Aucun sandboxId pour {slug}")
        return None

    # 2. namespace → offerId (cherche le mapping pour ce slug)
    r = requests.post(GRAPHQL_URL, headers=headers,
                      json={"query": CATALOG_NS_QUERY, "variables": {"namespace": namespace},
                            "operationName": "getCatalogNs"},
                      timeout=15)
    r.raise_for_status()
    catalog_ns = (((r.json().get("data") or {}).get("Catalog") or {}).get("catalogNs")) or {}
    mappings = catalog_ns.get("mappings") or []
    for m in mappings:
        if m.get("pageSlug") == slug:
            sub = m.get("mappings") or {}
            offer_id = sub.get("offerId") if isinstance(sub, dict) else None
            if offer_id:
                return namespace, offer_id

    # Fallback : prendre le BASE_GAME gratuit du namespace
    r = requests.post(GRAPHQL_URL, headers=headers,
                      json={"query": CATALOG_OFFERS_QUERY, "variables": {"namespace": namespace},
                            "operationName": "getCatalogOffers"},
                      timeout=15)
    r.raise_for_status()
    catalog_offers = (((r.json().get("data") or {}).get("Catalog") or {}).get("catalogOffers")) or {}
    offers = catalog_offers.get("elements") or []
    base_games = [o for o in offers if o.get("offerType") == "BASE_GAME"]
    free = next((o for o in base_games
                 if ((o.get("price") or {}).get("totalPrice") or {}).get("discountPrice") == 0),
                None) or (base_games[0] if base_games else None)
    if free:
        return namespace, free["id"]
    return None


def _generate_purchase_token() -> str:
    """Génère un purchaseToken hex de 32 chars (format observé dans le HAR)."""
    return uuid.uuid4().hex


def _talon_init(session: requests.Session, namespace: str, offer_id: str,
                purchase_token: str) -> tuple[str, dict] | None:
    """
    Appelle Talon /v1/init pour récupérer la siteKey hCaptcha.
    Retourne (siteKey, session_dict) ou None.
    """
    offers_param = f"1-{namespace}-{offer_id}--"
    purchase_url = (f"https://store.epicgames.com/purchase"
                    f"?highlightColor=0078f2&lang=fr&offers={offers_param}&showNavigation=true")
    r = session.post(TALON_INIT_URL,
                     json={"flow_id": "checkout_free_prod", "url": purchase_url},
                     headers={"Content-Type": "application/json", "Origin": "https://store.epicgames.com",
                              "Referer": purchase_url},
                     timeout=15)
    if r.status_code != 200:
        log.warning(f"[CLAIM] Talon init HTTP {r.status_code} : {r.text[:200]}")
        return None
    data = r.json()
    site_key = ((data.get("session") or {}).get("plan") or {}).get("h_captcha", {}).get("site_key")
    if not site_key:
        log.warning(f"[CLAIM] Pas de siteKey dans la réponse Talon : {data}")
        return None
    return site_key, data.get("session", {})


def _capmonster_solve(api_key: str, site_key: str, page_url: str) -> str | None:
    """Demande à CapMonster de résoudre le hCaptcha. Retourne le token (str) ou None."""
    # 1. createTask
    r = requests.post(f"{CAPMONSTER_URL}/createTask", json={
        "clientKey": api_key,
        "task": {
            "type": "HCaptchaTaskProxyless",
            "websiteURL": page_url,
            "websiteKey": site_key,
        },
    }, timeout=20)
    r.raise_for_status()
    data = r.json()
    if data.get("errorId"):
        log.warning(f"[CLAIM] CapMonster createTask error : {data}")
        return None
    task_id = data["taskId"]
    log.info(f"[CLAIM] CapMonster task {task_id} créée, attente résolution...")

    # 2. Poll getTaskResult (max 120s)
    deadline = time.time() + 120
    while time.time() < deadline:
        time.sleep(5)
        r = requests.post(f"{CAPMONSTER_URL}/getTaskResult",
                          json={"clientKey": api_key, "taskId": task_id},
                          timeout=20)
        r.raise_for_status()
        res = r.json()
        if res.get("errorId"):
            log.warning(f"[CLAIM] CapMonster getTaskResult error : {res}")
            return None
        if res.get("status") == "ready":
            token = (res.get("solution") or {}).get("gRecaptchaResponse")
            if token:
                log.info(f"[CLAIM] CapMonster résolu ({len(token)} chars)")
                return token
            log.warning(f"[CLAIM] CapMonster ready mais pas de token : {res}")
            return None
    log.warning("[CLAIM] CapMonster timeout 120s")
    return None


def _confirm_order(session: requests.Session, namespace: str, offer_id: str,
                   purchase_token: str, captcha_token: str, slug: str) -> tuple[str, str]:
    """POST confirm-order avec captchaToken. Retourne (outcome, message)."""
    originating = (f"https://store.epicgames.com/p/{slug}"
                   f"?lang=fr&purchaseToken={purchase_token}")
    payload = {
        "totalAmount": 0,
        "redeemRewardAmount": 0,
        "canQuickPurchase": True,
        "storePaymentMethod": False,
        "originatingRequest": originating,
        "captchaToken": captcha_token,
        # Note : le HAR ne montre pas namespace/offerId dans le body de confirm-order,
        # ils sont véhiculés via le purchaseToken / context server-side.
        # Si ça pète, on les ajoutera explicitement.
    }
    purchase_url = (f"https://store.epicgames.com/purchase?lang=fr"
                    f"&offers=1-{namespace}-{offer_id}--")
    r = session.post(CONFIRM_ORDER_URL, json=payload,
                     headers={
                         "Content-Type": "application/json",
                         "Origin": "https://store.epicgames.com",
                         "Referer": purchase_url,
                         "x-requested-with": purchase_token,
                     },
                     timeout=30)
    body = r.text[:500]
    if r.status_code == 200:
        try:
            data = r.json()
            order = data.get("orderResponse") or {}
            status = order.get("orderStatus") or order.get("status")
            if status == "COMPLETED":
                return ClaimOutcome.SUCCESS, f"orderId={order.get('orderId')}"
            return ClaimOutcome.FAILED, f"Status inattendu : {status} / body: {body}"
        except ValueError:
            return ClaimOutcome.FAILED, f"Réponse non-JSON : {body}"
    if r.status_code == 409 and "already" in body.lower():
        return ClaimOutcome.OWNED, "Déjà possédé"
    return ClaimOutcome.FAILED, f"HTTP {r.status_code} : {body}"


def claim_via_api(slug_or_url: str, storage_state_b64: str, capmonster_key: str,
                  title: str = "?") -> tuple[str, str]:
    """Point d'entrée principal. Retourne (ClaimOutcome, message)."""
    if not (storage_state_b64 and capmonster_key):
        return ClaimOutcome.FAILED, "EPIC_STORAGE_STATE_B64 ou CAPMONSTER_API_KEY manquant"

    try:
        session = _session_with_cookies(storage_state_b64)

        # Vérif quick que la session web est encore valide
        epic_cookies = [c for c in session.cookies if c.name in ("EPIC_BEARER_TOKEN", "EPIC_SESSION_AP", "EPIC_SSO")]
        if not epic_cookies:
            return ClaimOutcome.FAILED, "Pas de cookies session Epic — session expirée ?"
        log.info(f"[CLAIM] {len(epic_cookies)} cookie(s) session Epic OK")

        # 1. Resolve slug (anonyme — catalogOffers refuse les sessions auth)
        resolved = _resolve_slug(slug_or_url)
        if not resolved:
            return ClaimOutcome.FAILED, f"Slug introuvable : {slug_or_url}"
        namespace, offer_id = resolved
        m = re.search(r"/p/([^/?#]+)", slug_or_url)
        slug = m.group(1) if m else slug_or_url
        log.info(f"[CLAIM] {title} : ns={namespace[:8]}.. offer={offer_id[:8]}..")

        # 2. Talon init → siteKey hCaptcha
        purchase_token = _generate_purchase_token()
        talon = _talon_init(session, namespace, offer_id, purchase_token)
        if not talon:
            return ClaimOutcome.FAILED, "Talon init a échoué"
        site_key, _ = talon
        log.info(f"[CLAIM] siteKey hCaptcha : {site_key}")

        # 3. CapMonster résout
        offers_param = f"1-{namespace}-{offer_id}--"
        purchase_url = (f"https://store.epicgames.com/purchase"
                        f"?highlightColor=0078f2&lang=fr&offers={offers_param}&showNavigation=true")
        captcha_token = _capmonster_solve(capmonster_key, site_key, purchase_url)
        if not captcha_token:
            return ClaimOutcome.CAPTCHA, "CapMonster a échoué à résoudre le hCaptcha"

        # 4. Confirm order
        return _confirm_order(session, namespace, offer_id, purchase_token, captcha_token, slug)

    except requests.RequestException as e:
        return ClaimOutcome.FAILED, f"Réseau : {e}"
    except Exception as e:
        log.error(f"[CLAIM] Erreur inattendue", exc_info=True)
        return ClaimOutcome.FAILED, f"{type(e).__name__}: {e}"


# CLI pour test isolé : python claimer_api.py <slug>
if __name__ == "__main__":
    import sys
    storage = os.environ.get("EPIC_STORAGE_STATE_B64") or base64.b64encode(
        Path("epic_storage_state.json").read_bytes()).decode() if Path("epic_storage_state.json").exists() else ""
    cm_key = os.environ.get("CAPMONSTER_API_KEY", "")
    if len(sys.argv) < 2:
        print("Usage: python claimer_api.py <slug>")
        sys.exit(1)
    outcome, msg = claim_via_api(sys.argv[1], storage, cm_key, title=sys.argv[1])
    print(f"\n=== {outcome.upper()} ===")
    if msg:
        print(msg)
