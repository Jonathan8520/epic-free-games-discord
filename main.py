"""
main.py — Orchestrateur principal déclenché par GitHub Actions.

Flux :
1. Récupère les jeux gratuits Epic (epic.py), en attendant la sortie si
   elle tombe dans les prochaines minutes (jeudi 11h New York)
2. Notifie sur Discord les nouveaux jeux (current + upcoming)
3. Notifie les jeux mobiles gratuits (GamerPower)
4. Sauvegarde l'état (seulement s'il a changé)

Pas de garde-fou horaire côté Python : c'est le cron d'epic.yml qui fixe le
rythme, et un run ne coûte que quelques appels HTTP.
"""

import sys
import time
from functools import partial
from datetime import datetime, timedelta, timezone
from config import cfg
from state import State
from epic import get_free_games, get_surprise_free_games
from mobile import get_epic_mobile_games, get_new_mobile_games, scan_scheduled_claims, state_keys
from notifier import notify_new_game, notify_upcoming_game, notify_surprise_game, notify_mobile_game, notify_recap, alert_api_down
from logger import log
from claim_browser import Claimer, ClaimOutcome
from gh_secrets import update_secret


# Un run qui arrive jusqu'à 25 min avant une sortie l'attend plutôt que de
# repartir : le cron suivant peut avoir beaucoup de retard (cf epic.yml).
RELEASE_WAIT_MAX = timedelta(minutes=25)
REFRESH_RETRIES  = 10   # l'API (servie par un CDN) peut basculer avec un peu de retard
# Le giveaway mobile n'ouvre pas forcément en même temps que le PC (le 08/10 :
# 15:05 UTC contre 15:00), et il n'est pas toujours annoncé à l'avance.
MOBILE_WAIT_MAX  = timedelta(minutes=15)

# Ordre d'envoi des notifs sur Discord quand un run en a plusieurs :
# violet = à venir (PC et mobile), vert = gratuit PC, rouge = gratuit mobile,
# jaune = surprise -100 %. Le récap (« tout réclamer ») part toujours en dernier.
OUTBOX_ORDER = ("violet", "vert", "rouge", "jaune")


def _parse_iso(value) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return None


def _wait_for_release(games: list[dict]) -> list[dict]:
    """Si un jeu « à venir » devient gratuit dans les prochaines minutes,
    dort jusqu'à la sortie puis recharge l'API jusqu'à ce qu'elle ait basculé.
    Retourne la liste de jeux à traiter (inchangée s'il n'y a rien à attendre)."""
    now = datetime.now(timezone.utc)
    upcoming = [(g, _parse_iso(g.get("start_date"))) for g in games if g["status"] == "next"]
    soon = [(g, s) for g, s in upcoming if s and timedelta(0) < s - now <= RELEASE_WAIT_MAX]
    if not soon:
        return games

    release  = min(s for _, s in soon)
    expected = {g["id"] for g, s in soon if s == release}
    delay    = (release - now).total_seconds() + 20
    log.info(f"[RELEASE] Sortie à {release:%H:%M} UTC dans {delay / 60:.1f} min "
             f"({len(expected)} jeu(x)) : on attend.")
    time.sleep(delay)

    for attempt in range(1, REFRESH_RETRIES + 1):
        try:
            games = get_free_games()
        except Exception:
            if attempt == REFRESH_RETRIES:
                raise
            time.sleep(60)
            continue
        current_ids = {g["id"] for g in games if g["status"] == "current"}
        if expected <= current_ids:
            log.info("[RELEASE] API à jour, on continue.")
            return games
        if attempt < REFRESH_RETRIES:
            log.info(f"[RELEASE] API pas encore à jour (essai {attempt}), nouvel essai dans 60 s.")
            time.sleep(60)
    log.warning("[RELEASE] API toujours pas à jour, le prochain run prendra le relais.")
    return games


def _wait_for_mobile(seen_ids: set) -> list[dict]:
    """Guette le nouveau giveaway mobile pendant MOBILE_WAIT_MAX au plus.
    Appelé par le run qui annonce la sortie PC : le cron suivant peut avoir
    plusieurs heures de retard, autant que ce run envoie tout, récap compris.
    Retourne les nouveaux jeux mobiles (vide si rien n'est apparu)."""
    log.info(f"[MOBILE] Pas encore de nouveau giveaway mobile : on guette "
             f"{MOBILE_WAIT_MAX.total_seconds() / 60:.0f} min max.")
    deadline = time.monotonic() + MOBILE_WAIT_MAX.total_seconds()
    while time.monotonic() < deadline:
        time.sleep(60)
        new_mobile = get_new_mobile_games(get_epic_mobile_games(fresh=True), seen_ids)
        if new_mobile:
            return new_mobile
    log.warning("[MOBILE] Toujours aucun nouveau giveaway mobile, le prochain run prendra le relais.")
    return []


def main():
    log.info("=" * 50)
    log.info("Epic Free Games Bot v3 — démarrage")

    state = State(cfg.STATE_FILE)

    # 1. Récupère les jeux gratuits Epic (attend la sortie si elle est imminente)
    try:
        games = _wait_for_release(get_free_games())
    except Exception:
        log.error("API Epic inaccessible — arrêt sans toucher aux jeux vus.")
        if state.set_api_down(True):
            alert_api_down()
        state.save()
        return
    state.set_api_down(False)

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
    # Les notifs ne partent pas au fil de l'eau : elles sont rangées par couleur
    # puis envoyées dans un ordre fixe à la fin du run (voir OUTBOX_ORDER).
    outbox: dict[str, list] = {color: [] for color in OUTBOX_ORDER}

    claimer: Claimer | None = None
    recap_pc: list[dict] = []
    recap_mobile: list[dict] = []
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
            ClaimOutcome.SUCCESS : "success",
            ClaimOutcome.OWNED   : "owned",
            ClaimOutcome.TIMEOUT : "failed",
            ClaimOutcome.FAILED  : "failed",
            ClaimOutcome.NOT_FREE: "not_free",
        }.get(outcome, "failed")

    # 5. Jeux actuellement gratuits → claim + notif
    for game in current_games:
        if not state.is_notified(game["id"]):
            log.info(f"Nouveau jeu détecté : {game['title']}")
            status = try_claim(game)
            outbox["vert"].append(partial(notify_new_game, game, claim_status=status))
            if status not in ("success", "owned"):
                recap_pc.append(game)  # inutile de re-proposer un jeu déjà dans la lib
            state.mark_notified(game)
            state.remove(f"upcoming_{game['id']}")

    # 6. Jeux à venir → notification "bientôt gratuit" (pas de claim, pas encore dispo)
    for game in upcoming_games:
        upcoming_id = f"upcoming_{game['id']}"
        if not state.is_notified(upcoming_id):
            log.info(f"Jeu à venir détecté : {game['title']}")
            outbox["violet"].append(partial(notify_upcoming_game, game))
            state.mark_notified({**game, "id": upcoming_id})

    # 7. Surprise -100% → claim + notif
    for game in surprise:
        if not state.is_notified(game["id"]):
            log.info(f"Surprise gratuite détectée : {game['title']}")
            status = try_claim(game)
            outbox["jaune"].append(partial(notify_surprise_game, game, claim_status=status))
            if status not in ("success", "owned"):
                recap_pc.append(game)  # inutile de re-proposer un jeu déjà dans la lib
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
        if new_games_to_process and not new_mobile:
            new_mobile = _wait_for_mobile(seen_ids)

        for game in new_mobile:
            log.info(f"[MOBILE] Nouveau jeu mobile : {game['title']}")
            outbox["rouge"].append(partial(notify_mobile_game, game))
            recap_mobile.append(game)
            state.mark_notified({
                "id"            : state_keys(game)[0],
                "title"         : game["title"],
                "namespace"     : "",
                "url"           : game.get("url", ""),
                "original_price": game.get("worth"),
            })
        # Giveaways mobiles programmés mais pas encore actifs (voir docstring
        # de scan_scheduled_claims : couverture partielle, souvent vide).
        for game in scan_scheduled_claims():
            keys = state_keys(game, prefix="mobile_next")
            if any(k in seen_ids for k in keys):
                continue
            key = keys[0]
            log.info(f"[MOBILE] Giveaway mobile à venir : {game['title']}")
            outbox["violet"].append(partial(notify_mobile_game, game, upcoming=True))
            state.mark_notified({
                "id"            : key,
                "title"         : game["title"],
                "namespace"     : "",
                "url"           : game.get("url", ""),
                "original_price": game.get("worth"),
            })
    except Exception as e:
        log.warning(f"[MOBILE] Erreur récupération jeux mobiles : {e}")

    # 9. Envoi dans l'ordre : violet, vert, rouge, jaune, puis le récap
    for color in OUTBOX_ORDER:
        for send in outbox[color]:
            send()
    notify_recap(recap_pc, recap_mobile)  # uniquement si au moins 2 jeux ce run

    # 10. Sauvegarde
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
