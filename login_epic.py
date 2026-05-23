"""
login_epic.py — One-shot login Epic Games dans un browser Playwright visible.

Le but : ouvrir Chromium, te laisser login manuellement (avec captcha si Epic le
demande), puis sauvegarder les cookies de session dans `epic_storage_state.json`.

Ces cookies seront ensuite utilisés par `claim_browser.py` (en headless, sans
login) pour DOM-clicker le bouton "Obtenir" sur les jeux gratuits hebdo —
seule méthode qui marche pour les BASE_GAME (cf reference_autoclaim_endpoint).

Usage:
    python login_epic.py
"""

from pathlib import Path
from playwright.sync_api import sync_playwright

STATE_FILE   = Path(__file__).parent / "epic_storage_state.json"
PROFILE_DIR  = Path(__file__).parent / ".pw_profile"  # persistent — Epic te re-reconnaît
PROFILE_DIR.mkdir(exist_ok=True)


def main():
    with sync_playwright() as p:
        # launch_persistent_context = profil Chromium réutilisable (cookies + historique).
        # Évite que Epic te flag comme "nouveau device" et déclenche un captcha hostile.
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            locale="fr-FR",
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            # Réduit les fingerprints d'automation
            args=["--disable-blink-features=AutomationControlled"],
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
