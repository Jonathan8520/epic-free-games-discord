"""
login_epic_cdp.py — Récupère la session Epic depuis un Chrome NON piloté.

Epic sert un captcha qui échoue systématiquement dans un navigateur lancé par
Playwright, quelles que soient les précautions de fingerprint (constaté le
2026-09-09 : le bouton "Se connecter" tourne indéfiniment, et le captcha refuse
même résolu à la main). `login_epic.py` est donc inutilisable tant qu'Epic
maintient ça.

Ici on inverse le problème : Playwright ne lance rien et ne pilote rien pendant
le login. Tu ouvres ton vrai Chrome, tu te connectes comme d'habitude — le
captcha passe puisque rien n'est automatisé — et ce script vient simplement
lire les cookies par le port de debug.

MODE D'EMPLOI
  1. Ferme complètement Chrome (toutes les fenêtres).
  2. Lance Chrome avec un profil dédié et le port de debug :

       "/c/Program Files/Google/Chrome/Application/chrome.exe" \
           --remote-debugging-port=9222 \
           --user-data-dir="$TEMP/epic-chrome" &

     Le profil dédié n'est pas un caprice : depuis Chrome 136, le port de debug
     est ignoré sur le profil par défaut.
  3. Dans cette fenêtre, connecte-toi sur https://www.epicgames.com/id/login
     puis va sur https://store.epicgames.com/fr/ (propage les cookies du store).
  4. Laisse Chrome ouvert et lance : py -3 login_epic_cdp.py
"""

import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

STATE_FILE = Path(__file__).parent / "epic_storage_state.json"
CDP_URL    = "http://localhost:9222"
# Les deux qui portent réellement la session longue durée.
WANTED     = ("EPIC_SSO_RM", "EPIC_SESSION_AP", "EPIC_BEARER_TOKEN", "EPIC_SSO", "EPIC_DEVICE")


def main() -> int:
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(CDP_URL)
        except Exception as e:
            print(f"Connexion à {CDP_URL} impossible : {type(e).__name__}")
            print("Chrome n'est pas lancé avec --remote-debugging-port=9222,")
            print("ou il tourne sur le profil par défaut (le port y est ignoré).")
            return 1

        if not browser.contexts:
            print("Chrome répond mais n'a aucun onglet ouvert.")
            return 1

        context = browser.contexts[0]
        cookies = context.cookies()
        epic = [c for c in cookies if "epicgames.com" in c.get("domain", "")]
        names = sorted({c["name"] for c in epic if c["name"] in WANTED})

        print(f"{len(cookies)} cookies au total, {len(epic)} sur epicgames.com")
        print(f"Cookies de session reconnus : {names or 'AUCUN'}")

        if "EPIC_SSO_RM" not in names:
            print("\nPas de EPIC_SSO_RM : la session ne survivra pas au premier usage.")
            print("Vérifie que tu es bien connecté dans cette fenêtre Chrome,")
            print("et que tu as visité store.epicgames.com après le login.")
            return 1

        context.storage_state(path=str(STATE_FILE))
        print(f"\n✓ Session écrite dans {STATE_FILE.name} "
              f"({STATE_FILE.stat().st_size} octets)")
        print("  Ne le commit jamais — il contient ta session Epic.")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
