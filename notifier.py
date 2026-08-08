"""
notifier.py — Notifications Discord via webhook.

Deux webhooks distincts :
- DISCORD_WEBHOOK → salon principal (jeux gratuits)
- ALERT_WEBHOOK   → salon technique (heartbeat, alertes API)
  Si ALERT_WEBHOOK n'est pas défini, les alertes vont dans le salon principal.
"""

from datetime import datetime
import requests
from config import cfg
from logger import log


def _ts(iso_date: str | None) -> int | None:
    """Convertit une date ISO Epic en timestamp Unix pour Discord."""
    if not iso_date:
        return None
    try:
        return int(datetime.fromisoformat(iso_date.replace("Z", "+00:00")).timestamp())
    except (ValueError, TypeError):
        return None


def _post(webhook_url: str, payload: dict):
    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as e:
        log.error(f"[NOTIFIER] Échec envoi webhook : {e}")


CLAIM_FOOTERS = {
    "success": "✅ Réclamé automatiquement sur ton compte",
    "owned"  : "ℹ️ Déjà dans ta bibliothèque",
    "captcha": "⚠️ Captcha Epic — clique sur le lien pour récupérer",
    "failed" : "⚠️ Auto-claim échoué — clique pour récupérer",
}


def _game_embed(game: dict, color: int = 0x1ED760, claim_status: str | None = None,
                default_footer: str = "Epic Games Store • Gratuit cette semaine") -> dict:
    title = game.get("title", "Jeu inconnu")
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

    start_ts = _ts(game.get("start_date"))
    end_ts   = _ts(game.get("end_date"))
    if end_ts:
        if start_ts and start_ts > int(datetime.now().timestamp()):
            fields.append({
                "name"  : "Disponible",
                "value" : f"<t:{start_ts}:R> → <t:{end_ts}:R>",
                "inline": True,
            })
        else:
            fields.append({
                "name"  : "Expire",
                "value" : f"<t:{end_ts}:R>\n<t:{end_ts}:f>",
                "inline": True,
            })

    # Lien principal (PC) + liens mobiles si la promo couvre iOS/Android
    mobile_urls = game.get("mobile_urls") or {}
    links = [f"💻 [PC]({url})"]
    if mobile_urls.get("ios"):
        links.append(f"📱 [iOS]({mobile_urls['ios']})")
    if mobile_urls.get("android"):
        links.append(f"🤖 [Android]({mobile_urls['android']})")
    fields.append({
        "name"  : "Récupérer le jeu",
        "value" : " · ".join(links),
        "inline": True,
    })

    footer_text = CLAIM_FOOTERS.get(claim_status, default_footer)
    embed = {
        "title" : f"🎮 {title}",
        "url"   : url,
        "color" : color,
        "fields": fields,
        "footer": {"text": footer_text},
    }
    if image:
        embed["thumbnail"] = {"url": image}
    return embed


# ── Notifications principales ────────────────────────────────

def notify_new_game(game: dict, claim_status: str | None = None):
    """Notifie d'un nouveau jeu gratuit dans le salon principal."""
    ping  = f"<@&{cfg.ROLE_ID}> " if cfg.ROLE_ID else ""
    embed = _game_embed(game, claim_status=claim_status)
    _post(cfg.DISCORD_WEBHOOK, {"content": ping or None, "embeds": [embed]})
    log.info(f"[NOTIFIER] Notif envoyée pour {game['title']}")


def notify_upcoming_game(game: dict):
    """Notifie d'un jeu qui sera gratuit la semaine prochaine."""
    embed = _game_embed(game, color=0x7F77DD,
                        default_footer="Epic Games Store • Gratuit la semaine prochaine")
    embed["title"] = f"🔜 {game['title']}"
    _post(cfg.DISCORD_WEBHOOK, {"embeds": [embed]})
    log.info(f"[NOTIFIER] Notif upcoming envoyée pour {game['title']}")


def notify_surprise_game(game: dict, claim_status: str | None = None):
    """Notifie d'un jeu à -100% surprise (hors promo hebdo Epic)."""
    embed = _game_embed(game, color=0xFFD700, claim_status=claim_status,
                        default_footer="Epic Games Store • -100% hors promo hebdomadaire")
    embed["title"] = f"💎 {game['title']}"
    ping = f"<@&{cfg.ROLE_ID}> " if cfg.ROLE_ID else ""
    _post(cfg.DISCORD_WEBHOOK, {"content": ping or None, "embeds": [embed]})
    log.info(f"[NOTIFIER] Notif surprise envoyée pour {game['title']}")


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


# ── Notifications mobile ─────────────────────────────────────

def notify_mobile_game(game: dict, upcoming: bool = False):
    """
    Notifie d'un jeu gratuit Epic sur mobile (iOS/Android).
    upcoming=True : giveaway programmé mais pas encore actif (embed violet).
    """
    title     = game.get("title", "Jeu inconnu")
    url       = game.get("url", "")
    # Vignette a droite comme les embeds PC (embed["image"] = grande image en
    # dessous). L'appIcon est carre, il rend mieux qu'un card16x9 letterboxe.
    image     = game.get("icon") or game.get("image", "")
    platforms = game.get("platforms", "").upper()
    worth     = game.get("worth", "")
    expires   = game.get("expires", "")

    # Pas de ligne de texte : l'embed porte deja le titre, la plateforme et
    # le statut. On aligne sur notify_new_game qui n'envoie que le ping.
    ping = f"<@&{cfg.ROLE_ID}> " if cfg.ROLE_ID else ""

    fields = []
    if worth and worth not in ("$0.00", "0.00", ""):
        fields.append({
            "name"  : "Prix habituel",
            "value" : f"~~{worth}~~  →  **GRATUIT**",
            "inline": True,
        })
    starts_ts = game.get("starts_ts")
    if upcoming and starts_ts:
        fields.append({
            "name"  : "Disponible à partir du",
            "value" : f"<t:{starts_ts}:f> (<t:{starts_ts}:R>)",
            "inline": True,
        })

    expires_ts = game.get("expires_ts")
    if expires_ts:
        fields.append({
            "name"  : "Disponible jusqu'au",
            "value" : f"<t:{expires_ts}:f> (<t:{expires_ts}:R>)",
            "inline": True,
        })
    elif expires:
        fields.append({
            "name"  : "Disponible jusqu'au",
            "value" : expires,
            "inline": True,
        })
    mobile_urls = game.get("urls") or {}
    links = []
    if mobile_urls.get("ios"):
        links.append(f"📱 [iOS]({mobile_urls['ios']})")
    if mobile_urls.get("android"):
        links.append(f"🤖 [Android]({mobile_urls['android']})")
    if not links:
        links.append(f"[Ouvrir dans l'app Epic]({url})")
    fields.append({
        "name"  : "Réclamer le jeu",
        "value" : " · ".join(links),
        "inline": False,
    })

    embed = {
        "title"      : f"{'🔜📱' if upcoming else '📱'} {title}",
        "description": game.get("description", ""),
        "url"        : url,
        "color"      : 0x7F77DD if upcoming else 0x1ED760,
        "fields"     : fields,
        "footer"     : {"text": ("Epic Games Store Mobile • Bientôt gratuit • " if upcoming else "Epic Games Store Mobile • ") + platforms},
    }
    if image:
        embed["thumbnail"] = {"url": image}

    _post(cfg.DISCORD_WEBHOOK, {"content": ping or None, "embeds": [embed]})


# ── Récapitulatif ────────────────────────────────────────────

CART_URL = "https://store.epicgames.com/purchase?highlightColor=0078f2{offers}#/purchase/verify"


def build_cart_url(games: list[dict]) -> str | None:
    """
    Construit une URL de panier Epic pré-rempli avec plusieurs offres.
    Format : store.epicgames.com/purchase?offers=1-{namespace}-{offerId} (répétable).
    Ne fonctionne que pour le PC : les offres mobiles se réclament dans l'app.
    """
    parts = [
        f"&offers=1-{g['namespace']}-{g['id']}"
        for g in games
        if g.get("namespace") and g.get("id")
    ]
    return CART_URL.format(offers="".join(parts)) if parts else None


def notify_recap(pc_games: list[dict], mobile_games: list[dict] | None = None):
    """
    Message final du run : liste de tout ce qui est réclamable + un lien unique
    qui ouvre le panier Epic avec tous les jeux PC dedans.
    """
    mobile_games = mobile_games or []
    if len(pc_games) + len(mobile_games) < 2:
        return  # un seul jeu : l'embed individuel suffit

    lines = []
    for g in pc_games:
        price = g.get("original_price")
        suffix = f" ({price})" if price else ""
        lines.append(f"🎮 [{g.get('title', '?')}]({g.get('url', '')}){suffix}")
    for g in mobile_games:
        urls = g.get("urls") or {}
        links = " · ".join(
            f"[{name}]({link})" for name, link in (("iOS", urls.get("ios")), ("Android", urls.get("android"))) if link
        )
        lines.append(f"📱 **{g.get('title', '?')}** — {links}" if links else f"📱 {g.get('title', '?')}")

    fields = [{"name": "À réclamer", "value": "\n".join(lines), "inline": False}]

    cart = build_cart_url(pc_games)
    if cart:
        fields.append({
            "name"  : "Tout réclamer d'un coup",
            "value" : f"🛒 [Ouvrir le panier avec les {len(pc_games)} jeux PC]({cart})",
            "inline": False,
        })
    if mobile_games:
        fields.append({
            "name"  : "Mobile",
            "value" : "À réclamer dans l'app Epic Games Store, le panier web ne les accepte pas.",
            "inline": False,
        })

    embed = {
        "title" : "📋 Récapitulatif",
        "color" : 0x2B2D31,
        "fields": fields,
        "footer": {"text": "Epic Games Store • Récapitulatif du run"},
    }
    _post(cfg.DISCORD_WEBHOOK, {"embeds": [embed]})
    log.info(f"[NOTIFIER] Récap envoyé ({len(pc_games)} PC, {len(mobile_games)} mobile).")
