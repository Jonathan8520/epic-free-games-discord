"""
claim_browser.py — Auto-claim Epic via Playwright (DOM clicks).

C'est la seule méthode qui marche pour les BASE_GAME hebdo : Epic exige le
flow web complet (click "Obtenir" → iframe → "Ajouter à la bibliothèque" →
"J'accepte" EULA) qu'aucun endpoint API ne reproduit.

Trois modes d'auth :
1. Local interactif : profil persistant `.pw_profile/` (alimenté par login_epic.py)
2. Local prod-like : fichier `epic_storage_state.json` (env var EPIC_STORAGE_STATE_FILE)
3. CI / GH Actions : env var `EPIC_STORAGE_STATE_B64` (base64 du JSON)

Usage standalone (test local) :
    python claim_browser.py <slug-ou-url>

API pour main.py :
    with Claimer() as c:
        outcome, msg = c.claim("tomb-raider-iiii-remastered-538640")
        ...
    # c.new_storage_state_b64 contient le state mis à jour à la sortie
"""

import base64
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

STATE_FILE  = Path(__file__).parent / "epic_storage_state.json"
PROFILE_DIR = Path(__file__).parent / ".pw_profile"

# Détecte si on tourne en CI (GH Actions, etc.) — change headless + screenshots
IS_CI = bool(os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"))
DEBUG_CLAIM = os.environ.get("DEBUG_CLAIM") == "1"

SELECTORS = {
    "purchase_cta"   : '[data-testid="purchase-cta-button"]',
    "device_continue": 'div.css-16r1tk9 div.css-15w5v2y-CTA button[type="button"]',
    "iframe"         : '#webPurchaseContainer iframe',
}

PLACE_ORDER_TEXTS = [
    "Ajouter à la bibliothèque",
    "Add to Library",
    "Commander",
    "Place Order",
]
EULA_AGREE_TEXTS = [
    "J'accepte",
    "I Agree",
    "Accept",
]

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


class ClaimOutcome:
    SUCCESS  = "success"
    OWNED    = "owned"
    CAPTCHA  = "captcha"
    TIMEOUT  = "timeout"
    FAILED   = "failed"


def _click_button_by_text(frame, texts: list[str], timeout_ms: int) -> bool:
    for text in texts:
        try:
            frame.get_by_role("button", name=text, exact=False).first.click(timeout=timeout_ms)
            return True
        except Exception:
            continue
    return False


def _detect_owned(page) -> bool:
    try:
        text = page.locator(SELECTORS["purchase_cta"]).first.inner_text(timeout=3000)
    except PWTimeout:
        return False
    t = text.lower()
    return "bibliothèque" in t or "in library" in t or "owned" in t


def _detect_captcha(page) -> bool:
    for frame in page.frames:
        if "hcaptcha.com" in frame.url or "captcha-delivery.com" in frame.url:
            return True
    return False


def _shot(page, name: str) -> None:
    if DEBUG_CLAIM:
        try:
            page.screenshot(path=f"debug_{name}.png", full_page=True)
        except Exception:
            pass


class Claimer:
    """Gère une session browser pour claim plusieurs jeux d'affilée."""

    def __init__(self):
        self._pw = None
        self._context = None
        self._state_tmp: Path | None = None  # storage_state temp file (mode b64)
        self.new_storage_state_b64: str | None = None

    def __enter__(self):
        self._pw = sync_playwright().start()
        b64 = os.environ.get("EPIC_STORAGE_STATE_B64")
        state_file_env = os.environ.get("EPIC_STORAGE_STATE_FILE")

        launch_args = ["--disable-blink-features=AutomationControlled"]
        context_kwargs = dict(
            locale="fr-FR",
            viewport={"width": 1280, "height": 800},
            user_agent=UA,
        )

        if b64:
            # Mode CI / prod : storage_state depuis base64 → fichier temp
            self._state_tmp = Path(tempfile.mkdtemp()) / "epic_storage_state.json"
            self._state_tmp.write_bytes(base64.b64decode(b64))
            browser = self._pw.chromium.launch(headless=True, args=launch_args)
            self._context = browser.new_context(storage_state=str(self._state_tmp), **context_kwargs)
            self._browser = browser
            print(f"[CLAIMER] Mode CI (storage_state b64, {self._state_tmp.stat().st_size} bytes)")
        elif state_file_env and Path(state_file_env).exists():
            # Mode local prod-like : storage_state.json explicite
            browser = self._pw.chromium.launch(headless=not DEBUG_CLAIM, args=launch_args)
            self._context = browser.new_context(storage_state=state_file_env, **context_kwargs)
            self._browser = browser
            print(f"[CLAIMER] Mode local prod-like ({state_file_env})")
        elif PROFILE_DIR.exists():
            # Mode local interactif : profil persistant
            self._context = self._pw.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                headless=False,
                args=launch_args,
                **context_kwargs,
            )
            self._browser = None
            print(f"[CLAIMER] Mode local interactif (profil {PROFILE_DIR.name})")
        else:
            raise RuntimeError("Aucune source d'auth (EPIC_STORAGE_STATE_B64, EPIC_STORAGE_STATE_FILE, ou .pw_profile/)")

        # Vérif session
        cookies = self._context.cookies()
        epic_session = [c for c in cookies if c["name"] in ("EPIC_BEARER_TOKEN", "EPIC_SESSION_AP", "EPIC_SSO")]
        if not epic_session:
            raise RuntimeError("Pas de cookie de session Epic — la session a expiré (refais login_epic.py)")
        print(f"[CLAIMER] {len(epic_session)} cookie(s) session Epic OK")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            # Dump le state mis à jour (cookies rotés par Epic au cours du run)
            state = self._context.storage_state()
            state_json = json.dumps(state)
            self.new_storage_state_b64 = base64.b64encode(state_json.encode()).decode()
            # Si on était en mode local, on persiste aussi sur disque
            if not os.environ.get("EPIC_STORAGE_STATE_B64"):
                STATE_FILE.write_text(state_json, encoding="utf-8")
        except Exception as e:
            print(f"[CLAIMER] Warn : impossible de dump le state : {e}")
        try:
            self._context.close()
        except Exception:
            pass
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
        if self._pw:
            self._pw.stop()
        if self._state_tmp:
            try:
                self._state_tmp.unlink(missing_ok=True)
                self._state_tmp.parent.rmdir()
            except Exception:
                pass

    def claim(self, slug_or_url: str) -> tuple[str, str]:
        m = re.search(r"/p/([^/?#]+)", slug_or_url)
        slug = m.group(1) if m else slug_or_url
        url = f"https://store.epicgames.com/fr/p/{slug}"

        page = self._context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            print(f"[CLAIM] {url}")

            if _detect_owned(page):
                print("[CLAIM] Déjà dans la bibliothèque.")
                return ClaimOutcome.OWNED, ""

            # 1. Click "Obtenir"
            page.locator(SELECTORS["purchase_cta"]).first.click(timeout=10000)

            # 2. Popup "device not supported" (parfois)
            try:
                page.locator(SELECTORS["device_continue"]).last.click(timeout=3000)
            except PWTimeout:
                pass

            # 3. Iframe checkout
            iframe_handle = page.wait_for_selector(SELECTORS["iframe"], timeout=15000)
            frame = iframe_handle.content_frame()
            if not frame:
                return ClaimOutcome.FAILED, "Iframe checkout introuvable"

            # 4. Click "Ajouter à la bibliothèque"
            page.wait_for_timeout(3000)
            _shot(page, "iframe")
            if not _click_button_by_text(frame, PLACE_ORDER_TEXTS, timeout_ms=10000):
                _shot(page, "no_button")
                if _detect_captcha(page):
                    return ClaimOutcome.CAPTCHA, "hCaptcha bloque le bouton principal"
                return ClaimOutcome.TIMEOUT, "Bouton principal introuvable"

            # 5. EULA — polling jusqu'à 8s car Epic le présente avec un délai variable
            for attempt in range(8):
                page.wait_for_timeout(1000)
                iframe_handle = page.query_selector(SELECTORS["iframe"])
                if not iframe_handle:
                    break  # iframe fermée → claim finalisé
                frame_current = iframe_handle.content_frame()
                if frame_current and _click_button_by_text(frame_current, EULA_AGREE_TEXTS, timeout_ms=500):
                    page.wait_for_timeout(2000)
                    break

            # 6. Wait + refresh + vérification
            page.wait_for_timeout(3000)
            _shot(page, "after_claim")
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(3000)
            _shot(page, "final")

            if _detect_owned(page):
                print("[CLAIM] ✅ SUCCESS")
                return ClaimOutcome.SUCCESS, ""
            return ClaimOutcome.FAILED, "CTA pas passé à 'Dans la bibliothèque' après refresh"

        except PWTimeout as e:
            _shot(page, "timeout")
            if _detect_captcha(page):
                return ClaimOutcome.CAPTCHA, "hCaptcha détecté lors du flow"
            return ClaimOutcome.TIMEOUT, f"Timeout : {e}"
        except Exception as e:
            _shot(page, "error")
            return ClaimOutcome.FAILED, f"{type(e).__name__}: {e}"
        finally:
            try:
                page.close()
            except Exception:
                pass


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    with Claimer() as c:
        outcome, msg = c.claim(sys.argv[1])
    print(f"\n=== {outcome.upper()} ===")
    if msg:
        print(msg)


if __name__ == "__main__":
    main()
