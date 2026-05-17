"""
test_claim.py - Test isole du claim Epic Games.

Aucune dependance au reste du projet. Le but est juste de savoir si :
  - L'endpoint legacy /api/order/v3/orders/public/orders accepte les tokens launcher
  - L'endpoint launcher quickPurchase accepte un claim a 0 EUR
  - Le captcha bloque encore ou non en 2026

Usage :
    # 1. Recuperer un refresh token launcher (a faire une fois)
    #    Va sur :
    #    https://www.epicgames.com/id/api/redirect?clientId=34a02cf8f4414e29b15921876da36f9a&responseType=code
    #    Copie la valeur de "authorizationCode" du JSON, puis :
    python test_claim.py --bootstrap <authorizationCode>

    # 2. Sauvegarde le refresh_token affiche dans EPIC_REFRESH_TOKEN, puis :
    $env:EPIC_REFRESH_TOKEN = "<refresh_token>"
    python test_claim.py rocket-league--triplex-black-wheels
"""

import os
import re
import sys
import base64
import json
import requests
from pprint import pprint

CLIENT_ID     = "34a02cf8f4414e29b15921876da36f9a"
CLIENT_SECRET = "daafbccc737745039dffe53d94fc76cf"

TOKEN_URL      = "https://account-public-service-prod.ol.epicgames.com/account/api/oauth/token"
GRAPHQL_URL    = "https://store.epicgames.com/graphql"
LEGACY_ORDER   = "https://store.epicgames.com/api/order/v3/orders/public/orders"
QUICK_PURCHASE = "https://orderprocessor-public-service-ecomprod01.ol.epicgames.com/orderprocessor/api/shared/accounts/{account_id}/orders/quickPurchase"
EGS_PLATFORM   = "https://egs-platform-service.store.epicgames.com/api/v2/private/egs/purchase/quickPurchase"

UA_BROWSER  = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
UA_LAUNCHER = "EpicGamesLauncher/15.17.1-36648867+++Portal+Release-Live Windows/10.0.22631.1.256.64bit"


def _basic_auth() -> str:
    return base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()


def exchange_auth_code(code: str) -> dict:
    r = requests.post(
        TOKEN_URL,
        headers={
            "Authorization": f"Basic {_basic_auth()}",
            "Content-Type" : "application/x-www-form-urlencoded",
        },
        data={"grant_type": "authorization_code", "code": code},
        timeout=15,
    )
    print(f"[BOOTSTRAP] HTTP {r.status_code}")
    if r.status_code != 200:
        print(r.text[:800])
        r.raise_for_status()
    return r.json()


def refresh_access_token(refresh_token: str) -> dict:
    r = requests.post(
        TOKEN_URL,
        headers={
            "Authorization": f"Basic {_basic_auth()}",
            "Content-Type" : "application/x-www-form-urlencoded",
        },
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        timeout=15,
    )
    print(f"[AUTH] HTTP {r.status_code}")
    if r.status_code != 200:
        print(r.text[:800])
        r.raise_for_status()
    return r.json()


SANDBOX_QUERY = """
query getSandbox($pageSlug: String!) {
  StorePageMapping {
    mapping(pageSlug: $pageSlug) {
      sandboxId
      productId
    }
  }
}
"""

CATALOG_NS_QUERY = """
query getCatalogNs($namespace: String!) {
  Catalog {
    catalogNs(namespace: $namespace) {
      mappings {
        pageSlug
        pageType
        mappings {
          offerId
        }
      }
    }
  }
}
"""

CATALOG_OFFERS_QUERY = """
query getCatalogOffers($namespace: String!) {
  Catalog {
    catalogOffers(namespace: $namespace) {
      elements {
        id
        title
        offerType
        productSlug
        urlSlug
        price(country: "FR") {
          totalPrice { originalPrice discountPrice }
        }
      }
    }
  }
}
"""


def _gql(query: str, variables: dict, op_name: str) -> dict:
    r = requests.post(
        GRAPHQL_URL,
        json={"query": query, "variables": variables, "operationName": op_name},
        headers={"Content-Type": "application/json", "User-Agent": UA_BROWSER},
        timeout=15,
    )
    data = r.json()
    if "errors" in data:
        print(f"[GQL] {op_name} -> HTTP {r.status_code} avec erreurs :")
        pprint(data["errors"])
        raise SystemExit(1)
    return data["data"]


def resolve_slug(slug_or_url: str) -> tuple[str, str]:
    """
    Resout slug ou URL -> (namespace, offer_id) via 2 queries GraphQL Epic :
      1. StorePageMapping.mapping(pageSlug) -> sandboxId
      2. Catalog.catalogNs(namespace).mappings -> cherche le pageSlug et lit offerId
    """
    # Extrait le slug d'une URL si besoin
    m = re.search(r"/p/([^/?#]+)", slug_or_url)
    slug = m.group(1) if m else slug_or_url

    # Etape 1 : sandboxId via pageSlug
    sandbox_data = _gql(SANDBOX_QUERY, {"pageSlug": slug}, "getSandbox")
    mapping = sandbox_data.get("StorePageMapping", {}).get("mapping")
    if not mapping or not mapping.get("sandboxId"):
        print(f"[MAPPING] Aucun sandboxId pour slug={slug}")
        raise SystemExit(1)
    namespace = mapping["sandboxId"]
    print(f"[MAPPING] slug={slug} -> sandboxId={namespace}")

    # Etape 2 : tous les mappings du namespace
    catalog_data = _gql(CATALOG_NS_QUERY, {"namespace": namespace}, "getCatalogNs")
    all_mappings = (catalog_data.get("Catalog", {}).get("catalogNs") or {}).get("mappings") or []

    # Cherche le sub-mapping qui matche exactement le slug
    def _offer(m: dict) -> str | None:
        sub = m.get("mappings") or {}
        return sub.get("offerId") if isinstance(sub, dict) else None

    target = next((m for m in all_mappings if m.get("pageSlug") == slug and _offer(m)), None)

    # Fallback : premier offerId trouve (cas productHome sans offer direct)
    if not target:
        target = next((m for m in all_mappings if _offer(m)), None)
        if target:
            print(f"[MAPPING] Fallback : slug {slug} sans offer direct, utilise {target['pageSlug']}")

    offer_id = _offer(target) if target else None
    if offer_id:
        return namespace, offer_id

    # Fallback : query catalogOffers pour lister directement les offers du sandbox
    print(f"[MAPPING] Aucun offerId dans catalogNs.mappings, fallback sur catalogOffers")
    offers_data = _gql(
        CATALOG_OFFERS_QUERY,
        {"namespace": namespace},
        "getCatalogOffers",
    )
    offers = (offers_data.get("Catalog", {}).get("catalogOffers") or {}).get("elements") or []
    print(f"[MAPPING] catalogOffers retourne {len(offers)} offers")
    for o in offers:
        price = (o.get("price") or {}).get("totalPrice") or {}
        print(f"   - {o.get('offerType')}: id={o.get('id')} title={o.get('title')!r} "
              f"original={price.get('originalPrice')} discount={price.get('discountPrice')}")

    # Choisit le premier BASE_GAME gratuit, sinon premier BASE_GAME
    base_games = [o for o in offers if o.get("offerType") == "BASE_GAME"]
    free_base = next((o for o in base_games
                      if ((o.get("price") or {}).get("totalPrice") or {}).get("discountPrice") == 0),
                     None)
    chosen = free_base or (base_games[0] if base_games else (offers[0] if offers else None))

    if not chosen:
        print(f"[MAPPING] Aucune offer trouvable dans le namespace {namespace}")
        raise SystemExit(1)

    print(f"[MAPPING] Choisi : {chosen.get('title')!r} ({chosen.get('offerType')})")
    return namespace, chosen["id"]


def try_legacy_order(access_token: str, namespace: str, offer_id: str) -> None:
    print("\n" + "=" * 70)
    print(f"[LEGACY] POST {LEGACY_ORDER}")
    print(f"         namespace={namespace}  offer={offer_id}")
    payload = {
        "offers"     : [{"namespace": namespace, "id": offer_id, "quantity": 1}],
        "useDefault" : True,
        "setDefault" : False,
        "totalAmount": 0,
        "orderId"    : None,
        "sessionUUID": None,
        "syncToken"  : None,
    }
    r = requests.post(
        LEGACY_ORDER,
        json=payload,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type" : "application/json",
            "User-Agent"   : UA_BROWSER,
            "Origin"       : "https://store.epicgames.com",
            "Referer"      : "https://store.epicgames.com/",
        },
        timeout=20,
    )
    print(f"         HTTP {r.status_code}")
    print(f"         Body: {r.text[:1500]}")
    _check_captcha(r)


def try_quick_purchase(access_token: str, account_id: str, namespace: str, offer_id: str) -> None:
    print("\n" + "=" * 70)
    url = QUICK_PURCHASE.format(account_id=account_id)
    print(f"[QUICK] POST {url}")
    print(f"        namespace={namespace}  offer={offer_id}")
    payload = {
        "salesChannel"             : "Launcher",
        "entitlementSource"        : "Launcher",
        "returnSplitPaymentItems"  : False,
        "lineOffers"               : [{
            "offerId"                   : offer_id,
            "quantity"                  : 1,
            "namespace"                 : namespace,
            "appliedAccountCreditAmount": 0,
        }],
    }
    r = requests.post(
        url,
        json=payload,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type" : "application/json",
            "User-Agent"   : UA_LAUNCHER,
        },
        timeout=20,
    )
    print(f"        HTTP {r.status_code}")
    print(f"        Body: {r.text[:1500]}")
    _check_captcha(r)


def try_egs_platform(access_token: str, namespace: str, offer_id: str) -> None:
    """Endpoint reel utilise par le frontend store.epicgames.com (clic 'Obtenir')."""
    print("\n" + "=" * 70)
    print(f"[EGS]   POST {EGS_PLATFORM}")
    print(f"        namespace={namespace}  offer={offer_id}")
    payload = {
        "country"     : "FR",
        "lineOffers"  : [{"offerId": offer_id, "namespace": namespace}],
        "locale"      : "fr",
        "salesChannel": "Windows-Store-EGSWeb",
    }
    r = requests.post(
        EGS_PLATFORM,
        json=payload,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type" : "application/json",
            "User-Agent"   : UA_BROWSER,
            "Origin"       : "https://store.epicgames.com",
            "Referer"      : "https://store.epicgames.com/",
        },
        timeout=20,
    )
    print(f"        HTTP {r.status_code}")
    print(f"        Body: {r.text[:1500]}")
    _check_captcha(r)


def _check_captcha(r: requests.Response) -> None:
    body = r.text.lower()
    flags = [k for k in ("captcha", "verification", "one more step", "h-captcha", "hcaptcha", "recaptcha") if k in body]
    if flags:
        print(f"        >>> CAPTCHA DETECTE ({', '.join(flags)})")
    elif r.status_code == 200:
        print("        >>> Pas de captcha, HTTP 200")
    elif r.status_code in (401, 403):
        print(f"        >>> {r.status_code} : token launcher rejete par cet endpoint")


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)

    if args[0] == "--bootstrap":
        if len(args) < 2:
            print("Usage: python test_claim.py --bootstrap <authorizationCode>")
            sys.exit(1)
        data = exchange_auth_code(args[1])
        print("\n=== TOKENS ===")
        print(f"displayName  : {data.get('displayName')}")
        print(f"account_id   : {data.get('account_id')}")
        print(f"refresh_token: {data.get('refresh_token')}")
        print(f"expires_at   : {data.get('refresh_expires_at')}")
        print("\nSauvegarde le refresh_token :")
        print('  $env:EPIC_REFRESH_TOKEN = "..."')
        return

    # Mode manuel : python test_claim.py --manual <namespace> <offer_id>
    manual = None
    if args[0] == "--manual":
        if len(args) < 3:
            print("Usage: python test_claim.py --manual <namespace> <offer_id>")
            sys.exit(1)
        manual = (args[1], args[2])
    else:
        slug = args[0]

    rt = os.environ.get("EPIC_REFRESH_TOKEN", "")
    if not rt:
        print("EPIC_REFRESH_TOKEN manquant.")
        print("1. Va sur :")
        print(f"   https://www.epicgames.com/id/api/redirect?clientId={CLIENT_ID}&responseType=code")
        print('2. Copie la valeur "authorizationCode" du JSON.')
        print("3. python test_claim.py --bootstrap <authorizationCode>")
        sys.exit(1)

    tokens     = refresh_access_token(rt)
    access     = tokens["access_token"]
    account_id = tokens.get("account_id", "")
    print(f"[AUTH] OK - account_id={account_id}  display={tokens.get('displayName')}")

    if manual:
        namespace, offer_id = manual
    else:
        namespace, offer_id = resolve_slug(slug)
    print(f"[MAPPING] namespace={namespace}  offerId={offer_id}")

    try_legacy_order(access, namespace, offer_id)
    try_quick_purchase(access, account_id, namespace, offer_id)
    try_egs_platform(access, namespace, offer_id)


if __name__ == "__main__":
    main()
