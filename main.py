"""
main.py — Orchestrateur principal déclenché par GitHub Actions.

Flux :
1. Vérifie si ce run est nécessaire (scheduler)
2. Récupère les jeux gratuits Epic (epic.py)
3. Notifie sur Discord les nouveaux jeux (current + upcoming)
4. Notifie les jeux mobiles gratuits (GamerPower)
5. Sauvegarde l'état
"""

import sys
from config import cfg
from state import State
from epic import get_free_games, get_surprise_free_games
from mobile import get_epic_mobile_games, get_new_mobile_games
from notifier import notify_new_game, notify_upcoming_game, notify_surprise_game, notify_mobile_game, alert_api_down
from scheduler import should_run
from logger import log
from auth import auth
from claimer import claim_game, ClaimResult
from gh_secrets import update_secret


def main():
    log.info("=" * 50)
    log.info("Epic Free Games Bot v3 — démarrage")

    state = State(cfg.STATE_FILE)

    # 1. Faut-il tourner ce run ?
    if not should_run(state._data.get("last_check")):
        log.info("Rien à faire ce run.")
        state.save()
        return

    # 2. Récupère les jeux gratuits Epic
    try:
        games = get_free_games()
    except Exception:
        log.error("API Epic inaccessible — arrêt sans modifier l'état.")
        alert_api_down()
        return

    current_games  = [g for g in games if g["status"] == "current"]
    upcoming_games = [g for g in games if g["status"] == "next"]
    log.info(f"{len(current_games)} actuel(s), {len(upcoming_games)} à venir.")

    # 3. Surprise -100% (hors promo hebdo) — fetched ici pour que le claim sache quoi traiter
    surprise: list = []
    try:
        weekly_ids = {g["id"] for g in games}
        surprise   = get_surprise_free_games(exclude_ids=weekly_ids)
    except Exception as e:
        log.warning(f"[SURPRISE] Erreur fetch : {e}")

    # 4. Auto-claim (optionnel) — closure pour que les notifs en aval connaissent le statut
    _claim = {"token": None, "blocked": False}
    if not cfg.can_claim:
        log.info(
            f"[CLAIM] Désactivé — AUTO_CLAIM={cfg.AUTO_CLAIM} "
            f"EPIC_REFRESH_TOKEN={'set' if cfg.EPIC_REFRESH_TOKEN else 'MISSING'} "
            f"GH_PAT={'set' if cfg.GH_PAT else 'MISSING'} "
            f"GITHUB_REPO={cfg.GITHUB_REPO or 'MISSING'}"
        )
    elif current_games or surprise:
        if auth.refresh(cfg.EPIC_REFRESH_TOKEN):
            _claim["token"] = auth.access_token
        else:
            log.warning("[CLAIM] Refresh token rejeté — vérifier EPIC_REFRESH_TOKEN.")

    def try_claim(game) -> str | None:
        """Tente le claim, retourne le claim_status pour l'embed Discord (ou None)."""
        if not _claim["token"] or _claim["blocked"]:
            return None
        if not (game.get("namespace") and game.get("id")):
            return None
        result, msg = claim_game(_claim["token"], game["namespace"], game["id"], game["title"])
        if result == ClaimResult.UNAUTHORIZED:
            log.warning("[CLAIM] Token rejeté en cours de run — claim désactivé.")
            _claim["blocked"] = True
            return None
        if result == ClaimResult.FAILED:
            log.warning(f"[CLAIM] Échec {game['title']} : {msg}")
        return {
            ClaimResult.SUCCESS : "success",
            ClaimResult.OWNED   : "owned",
            ClaimResult.NOT_FREE: None,        # garde-fou : pas la peine d'embêter l'user
        }.get(result, "failed")

    # 5. Jeux actuellement gratuits → claim + notif
    for game in current_games:
        if not state.is_notified(game["id"]):
            log.info(f"Nouveau jeu détecté : {game['title']}")
            status = try_claim(game)
            notify_new_game(game, claim_status=status)
            state.mark_notified(game)
            state.remove(f"upcoming_{game['id']}")

    # 6. Jeux à venir → notification "bientôt gratuit" (pas de claim, pas encore dispo)
    for game in upcoming_games:
        upcoming_id = f"upcoming_{game['id']}"
        if not state.is_notified(upcoming_id):
            log.info(f"Jeu à venir détecté : {game['title']}")
            notify_upcoming_game(game)
            state.mark_notified({**game, "id": upcoming_id})

    # 7. Surprise -100% → claim + notif
    for game in surprise:
        if not state.is_notified(game["id"]):
            log.info(f"Surprise gratuite détectée : {game['title']}")
            status = try_claim(game)
            notify_surprise_game(game, claim_status=status)
            state.mark_notified(game)

    # 8. Persister le nouveau refresh_token (Epic invalide l'ancien à chaque usage)
    if _claim["token"] and auth.new_refresh_token and auth.new_refresh_token != cfg.EPIC_REFRESH_TOKEN:
        update_secret(cfg.GITHUB_REPO, cfg.GH_PAT, "EPIC_REFRESH_TOKEN", auth.new_refresh_token)

    # 6. Jeux gratuits mobiles (iOS / Android)
    try:
        mobile_games = get_epic_mobile_games()
        seen_ids     = set(state._data["games"].keys())
        new_mobile   = get_new_mobile_games(mobile_games, seen_ids)

        for game in new_mobile:
            log.info(f"[MOBILE] Nouveau jeu mobile : {game['title']}")
            notify_mobile_game(game)
            state.mark_notified({
                "id"            : f"mobile_{game['id']}",
                "title"         : game["title"],
                "namespace"     : "",
                "url"           : game.get("url", ""),
                "original_price": game.get("worth"),
            })
    except Exception as e:
        log.warning(f"[MOBILE] Erreur récupération jeux mobiles : {e}")

    # 6. Sauvegarde
    state.save()
    log.info("Done.")


if __name__ == "__main__":
    try:
        main()
    except EnvironmentError as e:
        log.error(f"Configuration manquante : {e}")
        sys.exit(1)
    except Exception as e:
        log.error(f"Erreur inattendue : {e}", exc_info=True)
        sys.exit(1)
