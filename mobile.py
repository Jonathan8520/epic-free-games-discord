"""
mobile.py — Récupère les jeux gratuits Epic Games Store sur mobile (iOS/Android)
via l'API GamerPower (gratuite, sans clé, agrège toutes les plateformes).

API docs : https://www.gamerpower.com/api-read
Limite : pas plus de 4 requêtes/seconde.

On filtre uniquement les jeux Epic Games sur mobile.
La réclamation est impossible automatiquement → notif Discord uniquement.
"""

import requests
from logger import log

GAMERPOWER_URL = "https://www.gamerpower.com/api/giveaways"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# Plateformes mobiles Epic à surveiller
MOBILE_PLATFORMS = ("android", "ios")


def get_epic_mobile_games() -> list[dict]:
    """
    Retourne les jeux gratuits Epic Games actuellement disponibles sur mobile.
    Chaque item : { id, title, description, url, image, platforms, worth, expires }
    """
    result = []

    for platform in MOBILE_PLATFORMS:
        try:
            resp = requests.get(
                GAMERPOWER_URL,
                params  = {"platform": platform, "type": "game"},
                headers = HEADERS,
                timeout = 10,
            )

            if resp.status_code == 201:
                log.info(f"[MOBILE] Aucun jeu gratuit sur {platform} en ce moment.")
                continue

            resp.raise_for_status()
            games = resp.json()

            for game in games:
                # Filtre : uniquement Epic Games Store
                if "epic" not in game.get("platforms", "").lower():
                    continue

                # Évite les doublons si un jeu est dispo iOS et Android
                already = any(g["id"] == str(game["id"]) for g in result)
                if already:
                    # Ajoute la plateforme manquante
                    for g in result:
                        if g["id"] == str(game["id"]) and platform not in g["platforms"]:
                            g["platforms"] += f", {platform}"
                    continue

                result.append({
                    "id"         : str(game.get("id", "")),
                    "title"      : game.get("title", "Jeu inconnu"),
                    "description": game.get("description", "")[:300],
                    "url"        : game.get("open_giveaway_url", game.get("giveaway_url", "")),
                    "image"      : game.get("image", ""),
                    "platforms"  : platform,
                    "worth"      : game.get("worth", ""),
                    "expires"    : game.get("end_date", ""),
                })

        except requests.RequestException as e:
            log.warning(f"[MOBILE] Erreur API GamerPower ({platform}) : {e}")

    log.info(f"[MOBILE] {len(result)} jeu(x) mobile(s) Epic gratuit(s) trouvé(s).")
    return result


def get_new_mobile_games(games: list[dict], seen_ids: set) -> list[dict]:
    """Filtre les jeux mobiles pas encore notifiés."""
    return [g for g in games if f"mobile_{g['id']}" not in seen_ids]
