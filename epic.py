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


def _parse_game(game: dict, status: str) -> dict:
    slug = game.get("productSlug") or game.get("urlSlug") or ""
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
