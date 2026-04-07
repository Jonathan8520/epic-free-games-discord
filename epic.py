"""
epic.py — Interroge l'API publique Epic Games Store.
"""

import requests
from datetime import datetime, timezone
from logger import log

API_URL = (
    "https://store-site-backend-static-ipv4.ak.epicgames.com"
    "/freeGamesPromotions?locale=fr&country=FR&allowCountries=FR"
)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def _extract_image(game: dict) -> str | None:
    images = game.get("keyImages", [])
    for wanted in ("Thumbnail", "DieselStoreFrontWide", "OfferImageWide"):
        for img in images:
            if img.get("type") == wanted:
                return img.get("url")
    return images[0].get("url") if images else None


def _extract_price(game: dict) -> str | None:
    try:
        p = game["price"]["totalPrice"]["fmtPrice"]["originalPrice"]
        return p if p not in ("0", "Free", "", "0,00 €") else None
    except (KeyError, TypeError):
        return None


def _is_free_now(game: dict) -> bool:
    now = datetime.now(timezone.utc)
    try:
        for group in game["promotions"]["promotionalOffers"]:
            for offer in group.get("promotionalOffers", []):
                start    = datetime.fromisoformat(offer["startDate"].replace("Z", "+00:00"))
                end      = datetime.fromisoformat(offer["endDate"].replace("Z", "+00:00"))
                discount = offer["discountSetting"]["discountPercentage"]
                if start <= now <= end and discount == 0:
                    return True
    except (KeyError, TypeError):
        pass
    return False


def _is_free_next(game: dict) -> bool:
    now = datetime.now(timezone.utc)
    try:
        for group in game["promotions"]["upcomingPromotionalOffers"]:
            for offer in group.get("promotionalOffers", []):
                start    = datetime.fromisoformat(offer["startDate"].replace("Z", "+00:00"))
                discount = offer["discountSetting"]["discountPercentage"]
                if start > now and discount == 0:
                    return True
    except (KeyError, TypeError):
        pass
    return False


def _extract_slug(game: dict) -> str:
    """
    Cherche le vrai slug du produit dans plusieurs champs possibles.
    Epic met le slug à différents endroits selon le type d'offre.
    """
    # 1. catalogNs.mappings[].pageSlug (le plus fiable pour les jeux récents)
    try:
        for m in game.get("catalogNs", {}).get("mappings", []) or []:
            slug = m.get("pageSlug")
            if slug:
                return slug
    except (AttributeError, TypeError):
        pass

    # 2. offerMappings[].pageSlug
    try:
        for m in game.get("offerMappings", []) or []:
            slug = m.get("pageSlug")
            if slug:
                return slug
    except (AttributeError, TypeError):
        pass

    # 3. productSlug / urlSlug (legacy)
    slug = game.get("productSlug") or game.get("urlSlug") or ""
    # Vire les suffixes type "/home" qu'Epic ajoute parfois
    if slug:
        return slug.split("/")[0]

    return ""


def _parse_game(game: dict, status: str) -> dict:
    slug = _extract_slug(game)
    url  = (
        f"https://store.epicgames.com/fr/p/{slug}"
        if slug else "https://store.epicgames.com/fr/free-games"
    )
    return {
        "id"             : game.get("id", ""),
        "title"          : game.get("title", "Jeu inconnu"),
        "description"    : game.get("description", ""),
        "url"            : url,
        "image"          : _extract_image(game),
        "original_price" : _extract_price(game),
        "status"         : status,
        "namespace"      : game.get("namespace", ""),
        "offer_type"     : game.get("offerType", ""),
    }


def get_free_games() -> list[dict]:
    """
    Appelle l'API Epic.
    Retourne une liste de jeux (current + next).
    Lève une exception si l'API est inaccessible.
    """
    try:
        resp = requests.get(API_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        log.error(f"API Epic inaccessible : {e}")
        raise

    items = resp.json()["data"]["Catalog"]["searchStore"]["elements"]
    result = []
    for game in items:
        if game.get("offerType") not in ("BASE_GAME", "OTHERS", "DLC"):
            continue
        if _is_free_now(game):
            result.append(_parse_game(game, "current"))
        elif _is_free_next(game):
            result.append(_parse_game(game, "next"))

    log.info(f"API Epic : {sum(1 for g in result if g['status']=='current')} jeu(x) gratuit(s) actuellement, "
             f"{sum(1 for g in result if g['status']=='next')} à venir.")
    return result


# ── Bonus : -100% surprise (hors promo hebdo) ──────────────────

GRAPHQL_URL = "https://store.epicgames.com/graphql"

SEARCH_QUERY = """
query searchStoreQuery($category: String, $count: Int, $country: String!, $locale: String, $priceRange: String) {
  Catalog {
    searchStore(category: $category, count: $count, country: $country, locale: $locale, priceRange: $priceRange) {
      elements {
        id
        title
        description
        namespace
        offerType
        productSlug
        urlSlug
        keyImages { type url }
        catalogNs { mappings { pageSlug } }
        offerMappings { pageSlug }
        price(country: $country) {
          totalPrice {
            discountPrice
            originalPrice
            fmtPrice(locale: $locale) { originalPrice discountPrice }
          }
        }
      }
    }
  }
}
"""


def get_surprise_free_games(exclude_ids: set[str] | None = None) -> list[dict]:
    """
    Cherche les jeux du catalogue actuellement à 0€ (hors promo hebdo).
    Filtre les démos et les jeux déjà couverts par get_free_games().
    Retourne une liste vide en cas d'erreur (non bloquant).
    """
    exclude_ids = exclude_ids or set()
    try:
        resp = requests.post(
            GRAPHQL_URL,
            json={
                "query": SEARCH_QUERY,
                "variables": {
                    "category"  : "games/edition/base",
                    "count"     : 40,
                    "country"   : "FR",
                    "locale"    : "fr",
                    "priceRange": "[0,0]",
                },
            },
            headers={**HEADERS, "Content-Type": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        elements = resp.json()["data"]["Catalog"]["searchStore"]["elements"]
    except (requests.RequestException, KeyError, TypeError) as e:
        log.warning(f"[SURPRISE] API searchStore inaccessible : {e}")
        return []

    result = []
    for game in elements:
        # Skip démos, bundles, addons
        if game.get("offerType") not in ("BASE_GAME", "OTHERS"):
            continue
        # Skip si déjà notifié via la promo hebdo
        if game.get("id") in exclude_ids:
            continue
        # Vérif réelle du prix actuel
        try:
            current_price = game["price"]["totalPrice"]["discountPrice"]
            original      = game["price"]["totalPrice"]["originalPrice"]
        except (KeyError, TypeError):
            continue
        # On veut un jeu normalement payant, actuellement à 0
        if current_price != 0 or original == 0:
            continue

        result.append(_parse_game(game, "surprise"))

    log.info(f"[SURPRISE] {len(result)} jeu(x) à -100% hors promo hebdo.")
    return result
