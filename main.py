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
from mobile import get_epic_mobile_games, get_new_mobile_games, scan_scheduled_claims
from notifier import notify_new_game, notify_upcoming_game, notify_surprise_game, notify_mobile_game, alert_api_down
from scheduler import should_run
from logger import log
from claim_browser import Claimer, ClaimOutcome
from gh_secrets import update_secret


def main():
    log.info("=" * 50)
    log.info("Epic Free Games Bot v3 — démarrage")

    state = State(cfg.STATE_FILE)

    # 1. Faut-il tourner ce run ?
    if cfg.FORCE_RUN:
        log.info("[SCHEDULER] FORCE_RUN actif - garde-fou ignore.")
    elif not should_run(state._data.get("last_check")):
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

    # 4. Auto-claim via Playwright (DOM clicks). Voir AUTO_CLAIM_FINDINGS.md.
    #    Marche en local. Sur GH Actions Azure : bloqué par Cloudflare → fallback footer "captcha".
    claimer: Claimer | None = None
    claim_blocked = False
    new_games_to_process = [g for g in current_games if not state.is_notified(g["id"])]
    surprise_to_process  = [g for g in surprise if not state.is_notified(g["id"])]

    if not cfg.can_claim:
        log.info(
            f"[CLAIM] Désactivé — AUTO_CLAIM={cfg.AUTO_CLAIM} "
            f"EPIC_STORAGE_STATE_B64={'set' if cfg.EPIC_STORAGE_STATE_B64 else 'MISSING'} "
            f"GH_PAT={'set' if cfg.GH_PAT else 'MISSING'} "
            f"GITHUB_REPO={cfg.GITHUB_REPO or 'MISSING'}"
        )
    elif new_games_to_process or surprise_to_process:
        try:
            claimer = Claimer().__enter__()
        except Exception as e:
            log.warning(f"[CLAIM] Init browser échoué ({e}) — claim désactivé pour ce run.")
            claimer = None

    def try_claim(game) -> str | None:
        nonlocal claim_blocked
        if not claimer or claim_blocked:
            return None
        slug_or_url = game.get("url") or ""
        if not slug_or_url:
            return None
        outcome, msg = claimer.claim(slug_or_url)
        log.info(f"[CLAIM] {game['title']} → {outcome}" + (f" ({msg})" if msg else ""))
        if outcome == ClaimOutcome.CAPTCHA:
            log.warning("[CLAIM] hCaptcha actif — claims suivants désactivés.")
            claim_blocked = True
            return "captcha"
        return {
            ClaimOutcome.SUCCESS: "success",
            ClaimOutcome.OWNED  : "owned",
            ClaimOutcome.TIMEOUT: "failed",
            ClaimOutcome.FAILED : "failed",
        }.get(outcome, "failed")

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

    # 8. Fermer le browser et persister le storage_state mis à jour
    if claimer:
        try:
            claimer.__exit__(None, None, None)
        except Exception as e:
            log.warning(f"[CLAIM] Fermeture browser : {e}")
        if claimer.new_storage_state_b64 and claimer.new_storage_state_b64 != cfg.EPIC_STORAGE_STATE_B64:
            update_secret(cfg.GITHUB_REPO, cfg.GH_PAT, "EPIC_STORAGE_STATE_B64", claimer.new_storage_state_b64)

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
        # Giveaways mobiles programmés mais pas encore actifs (voir docstring
        # de scan_scheduled_claims : couverture partielle, souvent vide).
        for game in scan_scheduled_claims():
            key = f"mobile_next_{game['id']}"
            if key in seen_ids:
                continue
            log.info(f"[MOBILE] Giveaway mobile à venir : {game['title']}")
            notify_mobile_game(game, upcoming=True)
            state.mark_notified({
                "id"            : key,
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
