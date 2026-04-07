"""
main.py — Orchestrateur principal déclenché par GitHub Actions.

Flux :
1. Vérifie si ce run est nécessaire (scheduler)
2. Récupère les jeux gratuits Epic (epic.py)
3. Notifie sur Discord les nouveaux jeux
4. Notifie les jeux mobiles gratuits (GamerPower)
5. Envoie le heartbeat hebdomadaire
6. Sauvegarde l'état
"""

import sys
from config import cfg
from state import State
from epic import get_free_games
from mobile import get_epic_mobile_games, get_new_mobile_games
from notifier import notify_new_game, notify_mobile_game, alert_api_down, send_heartbeat
from scheduler import should_run
from logger import log


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

    current_games = [g for g in games if g["status"] == "current"]
    log.info(f"{len(current_games)} jeu(x) actuellement gratuit(s).")

    # 3. Nouveaux jeux → notification
    for game in current_games:
        if not state.is_notified(game["id"]):
            log.info(f"Nouveau jeu détecté : {game['title']}")
            notify_new_game(game)
            state.mark_notified(game)

    # 4. Jeux gratuits mobiles (iOS / Android)
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

    # 5. Heartbeat hebdomadaire
    if state.needs_heartbeat():
        send_heartbeat(state.summary())
        state.mark_heartbeat()

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
