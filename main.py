"""
main.py — Orchestrateur principal déclenché par GitHub Actions.

Flux complet :
1. Vérifie si ce run est nécessaire (scheduler)
2. Récupère les jeux gratuits (epic.py)
3. Pour chaque nouveau jeu → notifie Discord
4. Vérifie la bibliothèque Epic (library.py) → évite les doublons
5. Réclame automatiquement + gère tous les cas d'erreur
6. Retente les jeux précédemment en échec
7. Envoie le heartbeat hebdomadaire
8. Sauvegarde l'état
"""

import sys
from config import cfg
from state import State
from epic import get_free_games
from mobile import get_epic_mobile_games, get_new_mobile_games
from library import get_owned_ids, is_owned
from claimer import claim_game, ClaimResult
from notifier import (
    notify_new_game, notify_claimed, notify_already_owned,
    notify_mobile_game,
    alert_cookies_expired, alert_eula_required, alert_captcha,
    alert_claim_failed, alert_api_down, send_heartbeat,
)
from scheduler import should_run
from logger import log


def process_claim(game: dict, state: State):
    """Gère la réclamation d'un jeu et met à jour l'état selon le résultat."""
    result, error = claim_game(game)

    if result == ClaimResult.SUCCESS:
        state.mark_claimed(game["id"])
        notify_claimed(game)

    elif result == ClaimResult.OWNED:
        state.mark_owned(game["id"])
        notify_already_owned(game)

    elif result == ClaimResult.EXPIRED:
        state.set_cookies_expired(True)
        state.mark_failed(game["id"], error)
        alert_cookies_expired(game)

    elif result == ClaimResult.EULA_REQUIRED:
        state.mark_eula(game["id"])
        alert_eula_required(game)

    elif result == ClaimResult.CAPTCHA:
        state.mark_captcha(game["id"])
        alert_captcha(game)

    else:
        state.mark_failed(game["id"], error)
        alert_claim_failed(game, error, cfg.CLAIM_RETRIES)


def main():
    log.info("=" * 50)
    log.info("Epic Free Games Bot v3 — démarrage")

    state = State(cfg.STATE_FILE)

    # 1. Faut-il tourner ce run ?
    if not should_run(state._data.get("last_check")):
        log.info("Rien à faire ce run.")
        state.save()
        return

    # 2. Récupère les jeux gratuits
    try:
        games = get_free_games()
    except Exception:
        log.error("API Epic inaccessible — arrêt sans modifier l'état.")
        alert_api_down()
        return

    current_games = [g for g in games if g["status"] == "current"]
    log.info(f"{len(current_games)} jeu(x) actuellement gratuit(s).")

    # 3. Récupère la bibliothèque Epic (si les cookies sont configurés)
    owned_ids: set[str] = set()
    if cfg.can_claim:
        owned_ids = get_owned_ids()

    # 4. Nouveaux jeux → notification + réclamation
    for game in current_games:
        if not state.is_notified(game["id"]):
            log.info(f"Nouveau jeu détecté : {game['title']}")
            notify_new_game(game)
            state.mark_notified(game)

            if cfg.can_claim:
                if is_owned(game["id"], owned_ids):
                    log.info(f"{game['title']} déjà possédé (bibliothèque).")
                    state.mark_owned(game["id"])
                    notify_already_owned(game)
                else:
                    process_claim(game, state)
            else:
                log.info("Réclamation auto désactivée ou cookies manquants.")

    # 5. Retry des jeux précédemment en échec
    pending = state.pending_claim()
    if pending:
        log.info(f"{len(pending)} jeu(x) en attente de retry.")
        if cfg.can_claim:
            for game_state in pending:
                if is_owned(game_state["id"], owned_ids):
                    state.mark_owned(game_state["id"])
                    continue
                game = {
                    "id"       : game_state["id"],
                    "title"    : game_state["title"],
                    "namespace": game_state.get("namespace", ""),
                    "url"      : f"https://store.epicgames.com/fr/free-games",
                }
                log.info(f"Retry pour : {game['title']} (tentative {game_state['retries'] + 1})")
                process_claim(game, state)
        else:
            log.info("Cookies manquants — retry impossible.")

    # 6. Réinitialise le flag cookies_expired si on a réussi une réclamation
    if any(
        state.get_game(g["id"]) and state.get_game(g["id"])["status"] == "claimed"
        for g in current_games
    ):
        state.set_cookies_expired(False)

    # 7. Jeux gratuits mobiles (iOS / Android) — notification uniquement
    try:
        mobile_games = get_epic_mobile_games()
        seen_ids     = set(state._data["games"].keys())
        new_mobile   = get_new_mobile_games(mobile_games, seen_ids)

        for game in new_mobile:
            log.info(f"[MOBILE] Nouveau jeu mobile : {game['title']}")
            notify_mobile_game(game)
            # Stocke avec préfixe "mobile_" pour éviter collision avec les IDs PC
            state._data["games"][f"mobile_{game['id']}"] = {
                "title"      : game["title"],
                "status"     : "notified",
                "notified_at": __import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc).isoformat(),
                "claimed_at" : None,
                "retries"    : 0,
                "last_error" : None,
                "value"      : game.get("worth"),
            }
    except Exception as e:
        log.warning(f"[MOBILE] Erreur récupération jeux mobiles : {e}")

    # 8. Heartbeat hebdomadaire
    if state.needs_heartbeat():
        send_heartbeat(state.summary())
        state.mark_heartbeat()

    # 9. Sauvegarde
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
