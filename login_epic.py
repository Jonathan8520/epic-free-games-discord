"""
login_epic.py — One-shot login Epic Games dans un browser Playwright visible.

⚠️  NE MARCHE PLUS depuis le 2026-09-09 : Epic sert un captcha qui échoue
    systématiquement dès que le navigateur est piloté par Playwright — le
    bouton "Se connecter" tourne indéfiniment, et le captcha refuse même
    résolu à la main. Le passage au vrai Chrome (channel="chrome"), la
    suppression de l'UA maquillée et le masquage de navigator.webdriver
    n'y changent rien : c'est le pilotage lui-même qui est détecté.

    ➜ Utiliser `login_epic_cdp.py`, qui récupère la session depuis un Chrome
      lancé normalement, que Playwright ne pilote pas.

    Ce script est conservé au cas où Epic relâcherait la contrainte.

Le but : ouvrir Chromium, te laisser login manuellement (avec captcha si Epic le
demande), puis sauvegarder les cookies de session dans `epic_storage_state.json`.

Ces cookies seront ensuite utilisés par `claim_browser.py` (en headless, sans
login) pour DOM-clicker le bouton "Obtenir" sur les jeux gratuits hebdo —
seule méthode qui marche pour les BASE_GAME (cf reference_autoclaim_endpoint).

Usage:
    python login_epic.py
"""

import os
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

STATE_FILE   = Path(__file__).parent / "epic_storage_state.json"

# Epic bloque le login quand il flaire un navigateur automatisé : le bouton
# "Se connecter" tourne indéfiniment, sans message d'erreur (vu le 2026-09-09).
# Le Chromium livré avec Playwright se fait repérer là où le vrai Chrome passe,
# d'où channel="chrome" par défaut. EPIC_LOGIN_CHANNEL=chromium pour revenir en
# arrière, EPIC_LOGIN_FRESH=1 pour repartir d'un profil vierge quand l'ancien
# traîne des cookies périmés qui font boucler la page.
CHANNEL = os.environ.get("EPIC_LOGIN_CHANNEL", "chrome")
FRESH   = os.environ.get("EPIC_LOGIN_FRESH") == "1"
PROFILE_DIR = Path(__file__).parent / (".pw_profile_fresh" if FRESH else ".pw_profile")
PROFILE_DIR.mkdir(exist_ok=True)


def main():
    with sync_playwright() as p:
        # launch_persistent_context = profil Chromium réutilisable (cookies + historique).
        # Évite que Epic te flag comme "nouveau device" et déclenche un captcha hostile.
        launch = dict(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            locale="fr-FR",
            viewport={"width": 1280, "height": 800},
            # Réduit les fingerprints d'automation
            args=["--disable-blink-features=AutomationControlled"],
        )
        # Pas de user_agent forcé avec le vrai Chrome : les Client Hints
        # (sec-ch-ua) annoncent la version réelle, et une UA "Chrome/120" posée
        # par-dessus un Chrome 153 est une incohérence immédiatement visible.
        # Le Chromium de Playwright, lui, annonce "HeadlessChrome" et doit être
        # maquillé — on aligne alors l'UA sur celle de claim_browser.py.
        if CHANNEL != "chrome":
            launch["user_agent"] = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )

        try:
            context = p.chromium.launch_persistent_context(channel=CHANNEL, **launch)
            print(f"[LOGIN] Navigateur : {CHANNEL}  |  profil : {PROFILE_DIR.name}")
        except Exception as e:
            if CHANNEL == "chromium":
                raise
            print(f"[LOGIN] {CHANNEL} indisponible ({type(e).__name__}) → Chromium")
            launch.setdefault("user_agent",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
            context = p.chromium.launch_persistent_context(**launch)

        # navigator.webdriver reste à True même avec le flag ci-dessus, et c'est
        # l'un des premiers signaux que lit la page de login d'Epic.
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://www.epicgames.com/id/login", wait_until="domcontentloaded")

        print("=" * 60)
        print("Fenêtre Chromium ouverte. Login avec ton compte Epic.")
        print("Si Epic demande date de naissance / captcha, fais-le tranquillement.")
        print("Vérifie ensuite que ton avatar apparaît en haut à droite.")
        print("Puis reviens ici et appuie sur Entrée.")
        print("=" * 60)
        input("[Entrée quand login terminé] ")

        # Navigue vers store pour propager les cookies de session sur ce sous-domaine
        print("[1/2] Navigation vers store.epicgames.com pour propager les cookies...")
        page.goto("https://store.epicgames.com/fr/", wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(2000)

        # Vérif login via cookies Epic
        cookies = context.cookies()
        session_cookies = [c["name"] for c in cookies if c["name"] in ("EPIC_BEARER_TOKEN", "EPIC_SESSION_AP", "EPIC_SSO")]
        print(f"[2/2] Cookies session Epic détectés : {session_cookies or 'AUCUN'}")
        if not session_cookies:
            print("⚠️  Aucun cookie de session — le login n'a pas abouti.")
            print("    Vérifie que tu vois bien ton avatar dans la fenêtre, puis relance.")
            browser.close()
            return

        context.storage_state(path=str(STATE_FILE))
        print(f"\n✓ Cookies sauvés dans {STATE_FILE.name}")
        print(f"  ({STATE_FILE.stat().st_size} bytes — contient ta session, ne le commit jamais)")
        print(f"✓ Profil persistant dans {PROFILE_DIR.name}/ (à conserver pour les futurs login)")
        context.close()


if __name__ == "__main__":
    main()
