"""
library.py — Vérifie si un jeu est déjà dans la bibliothèque Epic Games.
Évite de tenter de réclamer un jeu déjà possédé.
"""

import requests
from config import cfg
from logger import log

LIBRARY_URL = (
    "https://library-service.live.use1a.on.epicgames.com"
    "/library/api/public/items?includeMetadata=true"
)

def _headers() -> dict:
    return {
        "Authorization": f"Bearer {cfg.BEARER_TOKEN}",
        "User-Agent"   : (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }

def _cookies() -> dict:
    return {"EPIC_SESSION_AP": cfg.SESSION_AP}


def get_owned_ids() -> set[str]:
    """
    Retourne l'ensemble des IDs de jeux déjà possédés.
    En cas d'erreur réseau, retourne un set vide (on ne bloque pas le bot).
    """
    try:
        resp = requests.get(
            LIBRARY_URL,
            headers = _headers(),
            cookies = _cookies(),
            timeout = 15,
        )
        if resp.status_code == 401:
            log.warning("Bibliothèque Epic : cookies expirés (401).")
            return set()
        resp.raise_for_status()

        records = resp.json().get("records", [])
        ids = {r.get("catalogItemId", "") for r in records if r.get("catalogItemId")}
        log.info(f"Bibliothèque Epic : {len(ids)} jeu(x) possédé(s).")
        return ids

    except requests.RequestException as e:
        log.warning(f"Impossible de récupérer la bibliothèque Epic : {e}")
        return set()


def is_owned(game_id: str, owned_ids: set[str]) -> bool:
    return game_id in owned_ids
