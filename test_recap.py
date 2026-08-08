"""
test_recap.py — Vérifie le rendu du récapitulatif (embed + bouton "tout réclamer").

    py -3 test_recap.py           # affiche le payload, n'envoie rien
    py -3 test_recap.py --send    # envoie pour de vrai sur DISCORD_WEBHOOK

Le but du --send est de valider que Discord accepte le bouton lien sur un
webhook de salon classique (via ?with_components=true). Si le POST est refusé,
notify_recap retombe automatiquement sur l'embed seul, lien markdown inclus.
"""

import json
import os
import sys

# config.py exige DISCORD_WEBHOOK à l'import. En dry-run on n'envoie rien, donc
# une valeur bidon suffit — ça évite d'avoir à copier le vrai webhook en local.
if "--send" not in sys.argv:
    os.environ.setdefault("DISCORD_WEBHOOK", "https://discord.invalid/dry-run")

from notifier import build_cart_url, notify_recap

# Deux vrais jeux hebdo (namespace + offerId réels) pour tester l'URL de panier.
FAKE_PC = [
    {
        "title": "Tomb Raider I-III Remastered",
        "url": "https://store.epicgames.com/fr/p/tomb-raider-i-iii-remastered",
        "namespace": "c5f6069e7dd644dab009294f0fddc7a7",
        "id": "231e8f6d250a453f9c44c0adf3a34656",
        "original_price": "29,99 €",
    },
    {
        "title": "Down in Bermuda",
        "url": "https://store.epicgames.com/fr/p/down-in-bermuda",
        "namespace": "d5241c76f178492ea1540fce45616757",
        "id": "8bd4b4b0ed3f4d4fb1b9a2e0e5b5c8f1",
        "original_price": "14,99 €",
    },
]

FAKE_MOBILE = [
    {
        "title": "A Guidebook Of Babel",
        "urls": {
            "android": "https://store.epicgames.com/fr/p/a-guidebook-of-babel-android-1f2a3b",
            "ios": "https://store.epicgames.com/fr/p/a-guidebook-of-babel-ios-31c4fd",
        },
    }
]


def main():
    cart = build_cart_url(FAKE_PC)
    print("URL panier :\n ", cart, "\n")

    if "--send" not in sys.argv:
        print("Dry-run. Relance avec --send pour envoyer sur Discord.")
        print("\nAperçu du bouton envoyé :")
        print(json.dumps({
            "type": 1,
            "components": [{
                "type": 2, "style": 5,
                "label": f"🛒 Tout réclamer ({len(FAKE_PC)} jeux)",
                "url": cart,
            }],
        }, indent=2))  # ensure_ascii : la console Windows est en cp1252
        return

    notify_recap(FAKE_PC, FAKE_MOBILE)
    print("Envoyé. Regarde le salon : le bouton doit apparaître sous l'embed.")


if __name__ == "__main__":
    main()
