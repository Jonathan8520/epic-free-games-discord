"""
notifier.py — Toutes les notifications Discord via webhook.

Deux webhooks distincts :
- DISCORD_WEBHOOK  → salon principal (jeux gratuits)
- ALERT_WEBHOOK    → salon technique (erreurs, heartbeat, alertes)
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
    title   = game.get("title", "Jeu inconnu")
    desc    = game.get("description", "")[:300]
    url     = game.get("url", "https://store.epicgames.com/fr/free-games")
    image   = game.get("image")
    price   = game.get("original_price")

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
        embed["image"] = {"url": image}
    return embed


# ── Notifications principales ────────────────────────────────

def notify_new_game(game: dict):
    """Notifie d'un nouveau jeu gratuit dans le salon principal."""
    ping    = f"<@&{cfg.ROLE_ID}> " if cfg.ROLE_ID else ""
    content = f"{ping}🎮 Nouveau jeu gratuit sur Epic Games Store !"
    _post(cfg.DISCORD_WEBHOOK, {"content": content, "embeds": [_game_embed(game)]})
    log.info(f"[NOTIFIER] Notif envoyée pour {game['title']}")


def notify_upcoming_game(game: dict):
    """Notifie d'un jeu qui sera gratuit la semaine prochaine."""
    embed = _game_embed(game, color=0x7F77DD)
    embed["title"]  = f"🔜 Bientôt gratuit : {game['title']}"
    embed["footer"] = {"text": "Epic Games Store • Gratuit la semaine prochaine"}
    _post(cfg.DISCORD_WEBHOOK, {"content": "Un jeu sera gratuit la semaine prochaine !", "embeds": [embed]})


def notify_claimed(game: dict):
    _post(cfg.DISCORD_WEBHOOK, {
        "content": f"✅ **{game['title']}** a été réclamé automatiquement sur ton compte Epic !"
    })


def notify_already_owned(game: dict):
    _post(cfg.DISCORD_WEBHOOK, {
        "content": f"ℹ️ **{game['title']}** est déjà dans ta bibliothèque Epic."
    })


# ── Alertes techniques ───────────────────────────────────────

def alert_cookies_expired(game: dict | None = None):
    """Alerte critique : cookies expirés, réclamation impossible."""
    lines = [
        "🔑 **Cookies Epic expirés !**",
        "La réclamation automatique est désactivée.",
        f"👉 [Mettre à jour les secrets GitHub]({cfg.secrets_url})",
    ]
    if game:
        lines += [
            "",
            f"**{game['title']}** n'a pas pu être réclamé automatiquement.",
            f"👉 Réclame-le manuellement : {game['url']}",
        ]
    _post(cfg.alert_webhook, {"content": "\n".join(lines)})
    log.warning("[NOTIFIER] Alerte cookies expirés envoyée.")


def alert_eula_required(game: dict):
    """Le jeu nécessite d'accepter des CGU spécifiques avant réclamation."""
    _post(cfg.alert_webhook, {
        "content": (
            f"📋 **{game['title']}** nécessite d'accepter des conditions spécifiques.\n"
            f"Réclame-le manuellement en 1 clic : {game['url']}"
        )
    })


def alert_captcha(game: dict):
    """Epic a affiché un captcha, réclamation impossible automatiquement."""
    _post(cfg.alert_webhook, {
        "content": (
            f"🤖 **Captcha détecté** pour {game['title']}.\n"
            f"Réclame-le manuellement : {game['url']}\n"
            f"_(Si ça se répète, tes cookies sont peut-être trop anciens.)_"
        )
    })


def alert_claim_failed(game: dict, error: str, retries: int):
    """Échec après tous les retries."""
    _post(cfg.alert_webhook, {
        "content": (
            f"⚠️ **Échec réclamation** pour {game['title']} après {retries} tentative(s).\n"
            f"Erreur : `{error[:200]}`\n"
            f"Le bot réessaiera au prochain run.\n"
            f"Ou réclame manuellement : {game['url']}"
        )
    })


def alert_refresh_expired():
    """Alerte : le refresh token a expiré, il faut le renouveler manuellement."""
    _post(cfg.alert_webhook, {
        "content": (
            "🔑 **Refresh token Epic expiré !**\n"
            "Le bot ne peut plus rafraîchir automatiquement le bearer token.\n"
            "Il faut renouveler le `EPIC_REFRESH_TOKEN` dans les secrets GitHub.\n\n"
            "**Comment faire :**\n"
            "1. Va sur https://store.epicgames.com et connecte-toi\n"
            "2. F12 → Network → filtre `graphql` → clique une requête\n"
            "3. Dans les cookies, copie la valeur de `REFRESH_EPIC_EG1`\n"
            f"4. Colle-la ici : {cfg.secrets_url}\n\n"
            "_Ce token dure ~1 an, tu ne devrais pas avoir à refaire ça souvent._"
        )
    })
    log.warning("[NOTIFIER] Alerte refresh token expiré envoyée.")


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
    total    = summary["total_claimed"]
    saved    = summary["total_saved_eur"]
    failed   = summary["total_failed"]
    eula     = summary["total_eula"]
    captcha  = summary["total_captcha"]
    last     = summary.get("last_check", "inconnue")

    lines = [
        "💚 **Heartbeat hebdomadaire — le bot est vivant !**",
        "",
        f"🎮 Jeux réclamés au total : **{total}**",
        f"💰 Valeur économisée : **{saved:.2f} €**",
    ]
    if failed:
        lines.append(f"⚠️ Échecs en attente de retry : **{failed}**")
    if eula:
        lines.append(f"📋 En attente d'acceptation EULA : **{eula}**")
    if captcha:
        lines.append(f"🤖 Bloqués par captcha : **{captcha}**")
    lines.append(f"\n_Dernier check : {last}_")

    _post(cfg.alert_webhook, {"content": "\n".join(lines)})
    log.info("[NOTIFIER] Heartbeat envoyé.")


def send_retry_notice(game: dict, attempt: int, max_retries: int):
    """Optionnel : notifie qu'un retry est en cours."""
    if attempt == 1:
        return
    _post(cfg.alert_webhook, {
        "content": f"🔄 Retry {attempt}/{max_retries} pour **{game['title']}**…"
    })


# ── Notifications mobile ─────────────────────────────────────

def notify_mobile_game(game: dict):
    """
    Notifie d'un jeu gratuit Epic sur mobile (iOS/Android).
    Pas de réclamation auto possible → lien direct uniquement.
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
        "value" : f"[Ouvrir dans l'app Epic]({url})\n_Réclamation manuelle requise (mobile)_",
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
