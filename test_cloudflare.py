"""
test_cloudflare.py — Est-ce que cette machine peut charger le store Epic ?

À lancer SUR la VM Oracle, avant de monter quoi que ce soit :

    sudo apt install -y python3-pip
    pip3 install playwright
    python3 -m playwright install --with-deps chromium
    python3 test_cloudflare.py

C'est le test décisif : sur GitHub Actions (IP Azure), Cloudflare sert un
challenge Turnstile avant même la page produit, ce qui tue l'auto-claim. Si la
VM Oracle passe, le runner self-hosted est jouable ; si elle est challengée
aussi, inutile d'aller plus loin.

Un simple curl ne suffit pas à répondre : Cloudflare juge aussi l'empreinte du
navigateur, et peut laisser passer un vrai Chromium là où il bloque curl (ou
l'inverse). D'où Playwright ici, dans les mêmes conditions que claim_browser.py.
"""

import sys

from playwright.sync_api import sync_playwright

URLS = (
    "https://store.epicgames.com/fr/free-games",
    # Page produit : c'est celle que claim_browser.py ouvre réellement.
    "https://store.epicgames.com/fr/p/a-guidebook-of-babel-ios-31c4fd",
)

# ATTENTION : ne PAS chercher "challenge-platform" ni "turnstile" dans le HTML.
# Cloudflare injecte ce script sur toutes les pages qu'il protège, y compris
# quand il te laisse passer — s'en servir comme marqueur de blocage donne un
# faux positif systématique. L'interstitiel se reconnaît à son titre et au fait
# que la page fait quelques dizaines de Ko au lieu de plus d'un Mo.
BLOCK_TITLES = (
    "un instant",
    "just a moment",
    "attention required",
    "vérifiez que vous êtes humain",
    "checking your browser",
)


# Mêmes réglages que claim_browser.py, sinon le test ne prouve rien : Playwright
# lance par défaut `chrome-headless-shell`, une cible bien plus facile à
# détecter qu'un Chromium complet. channel="chromium" force le vrai binaire.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]


def check(page, url: str) -> bool:
    """True si la page a chargé pour de vrai, False si Cloudflare a challengé."""
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    except Exception as e:
        print(f"  ECHEC chargement : {e}")
        return False

    page.wait_for_timeout(5000)  # laisse le challenge s'afficher s'il y en a un
    html, title = page.content(), page.title()
    status = resp.status if resp else 0

    print(f"  HTTP {status} — {len(html):>9} octets — titre : {title[:60]!r}")

    if status == 403 or any(t in title.lower() for t in BLOCK_TITLES):
        return False
    return len(html) > 200_000  # une vraie page store pèse plus d'un Mo


def main() -> int:
    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel="chromium", args=LAUNCH_ARGS)
        page = browser.new_page(
            locale="fr-FR",
            user_agent=UA,
            viewport={"width": 1280, "height": 800},
        )
        for i, url in enumerate(URLS):
            print(f"\n{url}")
            results[url] = check(page, url)
            page.screenshot(path=f"cloudflare_test_{i}.png")
        browser.close()

    print()
    for url, ok in results.items():
        print(f"{'OK    ' if ok else 'BLOQUE'}  {url}")

    if all(results.values()):
        print("\nCette IP passe Cloudflare. Le runner self-hosted est jouable.")
        return 0
    print("\nCette IP est challengee, comme celles de GitHub Actions.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
