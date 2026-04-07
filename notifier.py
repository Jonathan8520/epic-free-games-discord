"""
notifier.py — Notifications Discord via webhook.

Deux webhooks distincts :
- DISCORD_WEBHOOK → salon principal (jeux gratuits)
- ALERT_WEBHOOK   → salon technique (heartbeat, alertes API)
  Si ALERT_WEBHOOK n'est pas défini, les alertes vont dans le salon principal.
"""

import requests
from config import cfg
from logger import log


def _post(webhook_url: str, payload: dict):
    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as e:
        log.error(f"[NOTIFIER] Échec envoi webhook : {e}")


def _game_embed(game: dict, color: int = 0x1ED760) -> dict:
    title = game.get("title", "Jeu inconnu")
    desc  = game.get("description", "")[:300]
    url   = game.get("url", "https://store.epicgames.com/fr/free-games")
    image = game.get("image")
    price = game.get("original_price")

    fields = []
    if price:
        fields.append({
            "name"  : "Prix habituel",
            "value" : f"~~{price}~~  →  **GRATUIT**",
            "inline": True,
        })
    fields.append({
        "name"  : "Récupérer le jeu",
        "value" : f"[Ouvrir le store Epic]({url})",
        "inline": True,
    })

    embed = {
        "title"      : f"🎮 {title}",
        "description": desc + ("…" if len(game.get("description", "")) > 300 else ""),
        "url"        : url,
        "color"      : color,
        "fields"     : fields,
        "footer"     : {"text": "Epic Games Store • Gratuit cette semaine"},
    }
    if image:
        embed["thumbnail"] = {"url": image}
    return embed


# ── Notifications principales ────────────────────────────────

def notify_new_game(game: dict):
    """Notifie d'un nouveau jeu gratuit dans le salon principal."""
    ping    = f"<@&{cfg.ROLE_ID}> " if cfg.ROLE_ID else ""
    content = f"{ping}🎮 Nouveau jeu gratuit sur Epic Games Store !"
    _post(cfg.DISCORD_WEBHOOK, {"content": content, "embeds": [_game_embed(game)]})
    log.info(f"[NOTIFIER] Notif envoyée pour {game['title']}")


# ── Alertes techniques ───────────────────────────────────────

def alert_api_down():
    """L'API Epic est inaccessible."""
    _post(cfg.alert_webhook, {
        "content": (
            "⚠️ **API Epic Games inaccessible.**\n"
            "Le bot n'a pas pu vérifier les jeux gratuits ce run.\n"
            "Aucun jeu n'a été marqué comme vu — la vérification reprendra normalement au prochain run."
        )
    })


def send_heartbeat(summary: dict):
    """Heartbeat hebdomadaire : le bot est vivant + stats."""
    total = summary["total_notified"]
    last  = summary.get("last_check", "inconnue")

    lines = [
        "💚 **Heartbeat hebdomadaire — le bot est vivant !**",
        "",
        f"🎮 Jeux notifiés au total : **{total}**",
        f"\n_Dernier check : {last}_",
    ]
    _post(cfg.alert_webhook, {"content": "\n".join(lines)})
    log.info("[NOTIFIER] Heartbeat envoyé.")


# ── Notifications mobile ─────────────────────────────────────

def notify_mobile_game(game: dict):
    """
    Notifie d'un jeu gratuit Epic sur mobile (iOS/Android).
    Lien direct vers la fiche du jeu.
    """
    title     = game.get("title", "Jeu inconnu")
    url       = game.get("url", "")
    image     = game.get("image", "")
    platforms = game.get("platforms", "").upper()
    worth     = game.get("worth", "")
    expires   = game.get("expires", "")

    ping    = f"<@&{cfg.ROLE_ID}> " if cfg.ROLE_ID else ""
    content = f"{ping}📱 Jeu gratuit Epic Games sur **{platforms}** !"

    fields = []
    if worth and worth not in ("$0.00", "0.00", ""):
        fields.append({
            "name"  : "Prix habituel",
            "value" : f"~~{worth}~~  →  **GRATUIT**",
            "inline": True,
        })
    if expires:
        fields.append({
            "name"  : "Disponible jusqu'au",
            "value" : expires,
            "inline": True,
        })
    fields.append({
        "name"  : "Réclamer le jeu",
        "value" : f"[Ouvrir dans l'app Epic]({url})",
        "inline": False,
    })

    embed = {
        "title"      : f"📱 {title}",
        "description": game.get("description", ""),
        "url"        : url,
        "color"      : 0x7F77DD,
        "fields"     : fields,
        "footer"     : {"text": f"Epic Games Store Mobile • {platforms}"},
    }
    if image:
        embed["image"] = {"url": image}

    _post(cfg.DISCORD_WEBHOOK, {"content": content, "embeds": [embed]})
