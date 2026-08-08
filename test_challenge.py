"""
test_challenge.py — Le Turnstile d'Epic se résout-il tout seul si on attend ?

Constat qui motive ce test : sur une IP datacenter (Azure comme Oracle), une
page produit chargée AVEC la session Epic renvoie un interstitiel "Encore une
étape" portant un widget Cloudflare Turnstile. claim_browser.py abandonne au
bout d'environ 1,5 s — il n'a jamais laissé sa chance au challenge.

Or un Turnstile en mode managé se résout fréquemment sans interaction, en
quelques secondes, quand l'empreinte du navigateur est correcte. Ce script
charge la page et sonde jusqu'à 90 s pour voir si le CTA finit par apparaître.

À lancer via le workflow test-claim (le secret EPIC_STORAGE_STATE_B64 doit
être injecté), ou en local avec epic_storage_state.json.
"""

import sys
import time

from claim_browser import Claimer, SELECTORS

URL = "https://store.epicgames.com/fr/p/beacon-pines-629fc3"
BUDGET_S = 90
POLL_S = 5


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else URL

    with Claimer() as c:
        page = c._context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)

        start = time.time()
        while time.time() - start < BUDGET_S:
            elapsed = int(time.time() - start)
            title = page.title()
            cta = page.locator(SELECTORS["purchase_cta"])
            n = cta.count()
            label = ""
            if n:
                try:
                    label = cta.first.inner_text(timeout=2000).strip()
                except Exception:
                    label = "<illisible>"

            print(f"  t+{elapsed:>3}s  titre={title[:42]!r:46} CTA={n} {label!r}")

            if n and label and label != "<illisible>":
                print(f"\nRESOLU tout seul apres {elapsed}s — CTA = {label!r}")
                page.screenshot(path="debug_challenge_ok.png")
                return 0

            time.sleep(POLL_S)

        print(f"\nTOUJOURS BLOQUE apres {BUDGET_S}s — titre final : {page.title()!r}")
        page.screenshot(path="debug_challenge_ko.png", full_page=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
