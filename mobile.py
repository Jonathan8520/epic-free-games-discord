"""
mobile.py — Jeux gratuits Epic Games Store sur mobile (Android/iOS).

Source : API publique du store mobile Epic (celle que consomme l'app EGS Mobile).
    GET https://egs-platform-service.store.epicgames.com/api/v2/public/discover/home
        ?count=10&start=0&country=FR&locale=fr&platform=android|ios&store=EGS

Pourquoi pas freeGamesPromotions ? Cet endpoint ne couvre que le PC : les
giveaways mobiles n'y apparaissent jamais (vérifié). GamerPower, lui, agrège
avec du retard et perd les dates exactes.

Deux fonctions :
  - get_epic_mobile_games()  : le(s) giveaway(s) mobile(s) en cours
  - scan_scheduled_claims()  : détecte les bascules "Claim" programmées dans le
    futur (Epic pré-charge le calendrier de prix dans le catalogue). Voir la
    note dans la docstring de la fonction sur les limites de cette détection.

Aucune authentification requise. Pas de réclamation automatique possible
(le claim mobile passe par l'app) → notification Discord uniquement.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import requests

try:
    from logger import log
except ImportError:  # exécution standalone
    import logging

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    log = logging.getLogger("mobile")

API_URL = "https://egs-platform-service.store.epicgames.com/api/v2/public/discover/home"
PLATFORMS = ("android", "ios")
COUNTRY = "FR"
LOCALE = "fr"
TIMEOUT = 15
RETRIES = 3

HEADERS = {
    "User-Agent": "EpicGamesStore/1.0 (Android)",
    "Accept": "application/json",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

STORE_URL = "https://store.epicgames.com/{locale}/p/{slug}"


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


_CACHE: dict[str, dict] = {}


def _fetch(platform: str) -> dict:
    """Appelle discover/home pour une plateforme. count est plafonné à 10 côté API.

    Le résultat est mémorisé pour la durée du process : get_epic_mobile_games() et
    scan_scheduled_claims() partagent donc le même payload (2 requêtes, pas 4).
    """
    if platform in _CACHE:
        return _CACHE[platform]
    params = {
        "count": 10,
        "start": 0,
        "country": COUNTRY,
        "locale": LOCALE,
        "platform": platform,
        "store": "EGS",
        # Cache-buster obligatoire : la reponse est mise en cache CDN sur la query
        # string exacte. Sans ce parametre, on peut recevoir l'ancien giveaway
        # pendant de longues minutes apres la rotation du jeudi 15:00 UTC.
        "cb": int(time.time() * 1000),
    }
    last_err = None
    for attempt in range(RETRIES):
        try:
            resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            _CACHE[platform] = resp.json()
            return _CACHE[platform]
        except requests.RequestException as e:
            last_err = e
            if attempt < RETRIES - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"[MOBILE] API Epic injoignable ({platform}) : {last_err}")


def _iter_offers(payload: dict):
    """Parcourt tous les modules et rend (module, offre)."""
    for module in payload.get("data", []) or []:
        for offer in module.get("offers", []) or []:
            yield module, offer


def _parse_offer(offer: dict, platform: str) -> dict | None:
    """Transforme une offre brute en dict normalisé, ou None si pas de state Claim."""
    content = offer.get("content") or {}
    purchases = content.get("purchase") or []

    claim = next((p for p in purchases if p.get("purchaseType") == "Claim"), None)
    if not claim:
        return None

    discount = claim.get("discount") or {}
    media = content.get("media") or {}
    slug = (content.get("mapping") or {}).get("slug", "")

    starts = claim.get("purchaseStateEffectiveDate", "")
    expires = discount.get("discountEndDate", "")
    starts_dt = _parse_date(starts)
    expires_dt = _parse_date(expires)

    return {
        "id": offer.get("offerId", ""),
        "sandbox_id": offer.get("sandboxId", ""),
        "title": content.get("title", "Jeu inconnu"),
        "slug": slug,
        "url": STORE_URL.format(locale=LOCALE, slug=slug) if slug else "",
        "urls": {platform: STORE_URL.format(locale=LOCALE, slug=slug)} if slug else {},
        "image": (media.get("card16x9") or media.get("coverImage") or {}).get("imageSrc", ""),
        "icon": (media.get("appIcon") or {}).get("imageSrc", ""),
        "platforms": platform,
        "worth": discount.get("originalPriceDisplay", ""),
        "starts": starts,
        "expires": expires,
        "starts_ts": int(starts_dt.timestamp()) if starts_dt else None,
        "expires_ts": int(expires_dt.timestamp()) if expires_dt else None,
    }


def _merge(results: list[dict], game: dict) -> None:
    """Fusionne les plateformes quand le même jeu est offert sur Android et iOS."""
    for existing in results:
        if existing["title"] == game["title"]:
            if game["platforms"] not in existing["platforms"]:
                existing["platforms"] += f", {game['platforms']}"
            existing["urls"].update(game.get("urls") or {})
            # lien principal : iOS en priorite, sinon Android
            existing["url"] = existing["urls"].get("ios") or existing["urls"].get("android") or existing["url"]
            return
    results.append(game)


def get_epic_mobile_games() -> list[dict]:
    """
    Retourne les giveaways mobiles Epic actuellement réclamables.
    Chaque item : { id, sandbox_id, title, slug, url, image, icon,
                    platforms, worth, starts, expires }
    """
    results: list[dict] = []
    now = datetime.now(timezone.utc)

    for platform in PLATFORMS:
        try:
            payload = _fetch(platform)
        except RuntimeError as e:
            log.warning(str(e))
            continue

        for module, offer in _iter_offers(payload):
            if module.get("type") != "freeGame":
                continue

            game = _parse_offer(offer, platform)
            if not game:
                continue

            # Garde-fou : ignore une offre dont la fenêtre est déjà passée
            expires = _parse_date(game["expires"])
            if expires and expires < now:
                continue

            _merge(results, game)

    log.info(f"[MOBILE] {len(results)} giveaway(s) mobile(s) en cours.")
    return results


def scan_scheduled_claims() -> list[dict]:
    """
    Détecte les jeux dont une bascule gratuite est PROGRAMMÉE mais pas active.

    Epic pré-charge le calendrier de prix dans le catalogue : une offre porte
    plusieurs états successifs avec leur purchaseStateEffectiveDate. Un état
    Claim daté dans le futur = giveaway à venir, avant toute annonce.

    Limite connue : discover/home est un flux éditorialisé (environ 200 offres),
    pas le catalogue complet. Un titre absent de la home passe sous le radar.
    Les routes produit/offre unitaires renvoient 403/404 en public et
    store.epicgames.com/graphql est derrière Cloudflare, donc pas de balayage
    exhaustif sans compte authentifié.
    """
    upcoming: list[dict] = []
    now = datetime.now(timezone.utc)

    for platform in PLATFORMS:
        try:
            payload = _fetch(platform)
        except RuntimeError as e:
            log.warning(str(e))
            continue

        for _, offer in _iter_offers(payload):
            content = offer.get("content") or {}
            for purchase in content.get("purchase") or []:
                if purchase.get("purchaseType") != "Claim":
                    continue

                effective = _parse_date(purchase.get("purchaseStateEffectiveDate"))
                if not effective or effective <= now:
                    continue

                game = _parse_offer(offer, platform)
                if game:
                    _merge(upcoming, game)

    if upcoming:
        log.info(f"[MOBILE] {len(upcoming)} giveaway(s) mobile(s) programmé(s).")
    return upcoming


def get_new_mobile_games(games: list[dict], seen_ids: set) -> list[dict]:
    """Filtre les jeux mobiles pas encore notifiés. (Signature inchangée.)"""
    return [g for g in games if f"mobile_{g['id']}" not in seen_ids]


if __name__ == "__main__":
    for g in get_epic_mobile_games():
        print(f"[EN COURS] {g['title']} ({g['platforms']}) {g['worth']} -> {g['expires']}")
        print(f"           {g['url']}")
    for g in scan_scheduled_claims():
        print(f"[A VENIR]  {g['title']} ({g['platforms']}) a partir de {g['starts']}")
