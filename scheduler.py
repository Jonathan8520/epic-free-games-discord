"""
scheduler.py — Vérifie si ce run doit effectuer une vérification complète.

Stratégie :
- Jeudi 15h–20h UTC (heure de publication Epic) → toujours actif
- Reste du temps → actif seulement si le dernier check date de plus d'1h
  (permet d'éviter de tourner inutilement si le cron est fréquent)

GitHub Actions est configuré pour tourner toutes les 10 minutes le jeudi,
et toutes les heures le reste du temps (via deux cron dans le workflow).
Ce fichier ajoute une garde supplémentaire côté Python.
"""

from datetime import datetime, timezone, timedelta
from logger import log


def should_run(last_check_iso: str | None) -> bool:
    """
    Retourne True si le bot doit effectuer une vérification ce run.
    """
    now = datetime.now(timezone.utc)
    is_thursday       = now.weekday() == 3
    is_peak_hours     = 15 <= now.hour <= 20

    if is_thursday and is_peak_hours:
        log.info("[SCHEDULER] Jeudi heure de pointe — vérification forcée.")
        return True

    if last_check_iso is None:
        log.info("[SCHEDULER] Premier run — vérification forcée.")
        return True

    try:
        last = datetime.fromisoformat(last_check_iso)
        elapsed = now - last
        if elapsed >= timedelta(hours=1):
            log.info(f"[SCHEDULER] Dernier check il y a {elapsed} — vérification.")
            return True
        else:
            log.info(f"[SCHEDULER] Dernier check il y a {elapsed} — trop récent, skip.")
            return False
    except (ValueError, TypeError):
        log.warning("[SCHEDULER] last_check invalide — vérification par précaution.")
        return True
