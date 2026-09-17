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
import time
from pathlib import Path

# Moteur furtif optionnel : patchright expose la même API que playwright, avec
# un Chromium patché qui n'expose pas les marqueurs d'automatisation (fuite CDP
# Runtime.enable notamment). EPIC_STEALTH=1 pour l'utiliser.
if os.environ.get("EPIC_STEALTH") == "1":
    from patchright.sync_api import sync_playwright, TimeoutError as PWTimeout
else:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

STATE_FILE  = Path(__file__).parent / "epic_storage_state.json"
PROFILE_DIR = Path(__file__).parent / ".pw_profile"

# Détecte si on tourne en CI (GH Actions, etc.) — change headless + screenshots
IS_CI = bool(os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"))
DEBUG_CLAIM = os.environ.get("DEBUG_CLAIM") == "1"

# Chromium AVEC fenêtre (sous Xvfb sur un serveur sans écran). Mesuré le
# 2026-09-10 depuis la VM Oracle : en headless, le chemin de paiement
# /purchase renvoie 403 alors même que la page produit se charge normalement ;
# en fenêtre il répond 200 et l'écran "Ajouter à la bibliothèque" s'affiche.
# En fenêtre on garde l'UA native : l'UA maquillée ne sert qu'à masquer le
# marqueur "HeadlessChrome" du mode headless, et mentir sur l'OS déclenche des
# incohérences avec les Client Hints.
HEADFUL = os.environ.get("EPIC_HEADFUL") == "1"

# EPIC_WAIT_HUMAN=<secondes> : laisse la fenêtre ouverte pour qu'un humain
# résolve l'enquête de sécurité d'Epic (hCaptcha à images) via VNC. Le jeton
# hCaptcha est à usage unique et valable ~120 s : impossible de le mettre en
# cache d'une semaine sur l'autre, seul un humain devant l'écran le produit.
# L'enjeu du mode : savoir si Epic cesse de réclamer l'enquête ensuite.
WAIT_HUMAN = int(os.environ.get("EPIC_WAIT_HUMAN") or 0)

SELECTORS = {
    "purchase_cta"   : '[data-testid="purchase-cta-button"]',
    "device_continue": 'div.css-16r1tk9 div.css-15w5v2y-CTA button[type="button"]',
    "iframe"         : '#webPurchaseContainer iframe',
}

# Un claim à 0 € affiche "Ajouter à la bibliothèque" (vérifié 2026-05-23).
# "Commander" / "Place Order" sont les libellés d'un ACHAT PAYANT — ils ont été
# retirés volontairement : si Epic présentait ce bouton, c'est que l'offre n'est
# pas gratuite, et on préfère échouer que payer.
PLACE_ORDER_TEXTS = [
    "Ajouter à la bibliothèque",
    "Add to Library",
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
    NOT_FREE = "not_free"   # garde-fou prix : l'offre n'est plus à 0 €


# Garde-fou prix. Relevé sur le store le 2026-08-09 :
#   gratuit → CTA "Obtenir", bloc d'achat "-100 % / 17,99 €* / Gratuit"
#   payant  → CTA "Acheter",  bloc d'achat "59,99 €" (pas de "Gratuit")
# On exige les DEUX signaux : un CTA d'acquisition ET la mention de gratuité.
BUY_CTA_TEXTS  = ("acheter", "buy", "commander", "place order",
                  "précommander", "pre-order", "pre-purchase")
FREE_CTA_TEXTS = ("obtenir", "get")
FREE_MARKERS   = ("gratuit", "free")


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


def _wait_cta_ready(page, timeout_ms: int = 30_000) -> str:
    """Attend que le CTA porte enfin un libellé, et le retourne.

    La page produit est une SPA : le bouton est attaché au DOM **vide**, puis
    rempli une seconde plus tard. Playwright le considère prêt dès qu'il est
    visible, donc `inner_text()` renvoie '' sans lever de timeout — et tout ce
    qui suit lit une chaîne vide sur une page parfaitement saine. C'est ce qui
    faisait répondre "CTA inattendu = ''" et s'abstenir (vu le 2026-09-09 sur
    la VM Oracle, sur un jeu qui était en réalité déjà dans la bibliothèque).

    Retourne '' si le libellé ne vient jamais — l'appelant distingue alors une
    page bloquée (Turnstile) d'une offre payante.
    """
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        try:
            label = page.locator(SELECTORS["purchase_cta"]).first.inner_text(
                timeout=2000).strip()
        except Exception:
            label = ""
        if label:
            return label
        page.wait_for_timeout(500)
    return ""


def _is_free_offer(page) -> tuple[bool, str]:
    """
    Revérifie que l'offre est bien à 0 € JUSTE AVANT de cliquer.

    Indispensable : le filtre de `epic.py` porte sur la fenêtre de promo au
    moment du fetch, et la rotation Epic tombe le jeudi 15:00 UTC. Un run qui
    récupère la liste à 14:59 et clique à 15:00 viserait un jeu redevenu payant.
    Ici on lit le DOM au dernier moment, donc plus de fenêtre de course.

    Retourne (c_est_gratuit, raison).
    """
    try:
        cta = page.locator(SELECTORS["purchase_cta"]).first
        label = cta.inner_text(timeout=10000).strip()
    except Exception as e:
        return False, f"CTA illisible ({type(e).__name__}) — on ne clique pas"

    low = label.lower()
    if any(t in low for t in BUY_CTA_TEXTS):
        return False, f"CTA = {label!r} → offre payante"
    if not any(t in low for t in FREE_CTA_TEXTS):
        return False, f"CTA inattendu = {label!r} → on s'abstient"

    # Deuxième signal : le bloc d'achat autour du bouton doit annoncer "Gratuit".
    try:
        block = cta.evaluate(
            "e => { let n = e;"
            " for (let i = 0; i < 6 && n.parentElement; i++) n = n.parentElement;"
            " return n.innerText; }"
        )
    except Exception as e:
        return False, f"bloc d'achat illisible ({type(e).__name__})"

    if not any(m in block.lower() for m in FREE_MARKERS):
        extract = " / ".join(l.strip() for l in block.split("\n") if l.strip())[:120]
        return False, f"pas de mention de gratuité dans le bloc d'achat : {extract!r}"

    return True, label


CAPTCHA_HOSTS = ("hcaptcha.com", "captcha-delivery.com", "challenges.cloudflare.com")


def _visible_captcha_frames(page) -> list:
    """Les iframes de captcha réellement AFFICHÉES.

    hCaptcha charge toujours une iframe invisible, même quand il laisse passer :
    la compter faisait répondre "hCaptcha bloque le bouton" à chaque échec, quel
    qu'en soit le vrai motif (vu le 2026-09-14, où le blocage venait en fait du
    cartouche de rétractation). On exige donc une iframe visible et de taille
    réelle.
    """
    out = []
    for frame in page.frames:
        if not any(h in (frame.url or "") for h in CAPTCHA_HOSTS):
            continue
        try:
            el = frame.frame_element()
            box = el.bounding_box() if el.is_visible() else None
        except Exception:
            continue
        if box and box.get("height", 0) >= 40 and box.get("width", 0) >= 40:
            out.append(frame)
    return out


def _try_captcha_checkbox(page) -> str:
    """Coche la case « je suis humain » quand l'enquête n'a pas d'images.

    Epic en présente deux, distinctes (observé le 2026-09-17) : une simple case
    à cocher, franchissable d'un clic — c'est celle-ci — puis un défi à images
    après "Ajouter à la bibliothèque", qui exige un humain.

    Retourne ce qui a été cliqué, '' si rien de cliquable n'a été trouvé.
    """
    for frame in _visible_captcha_frames(page):
        for sel in ("#checkbox", "#anchor", "[role=checkbox]", "input[type=checkbox]"):
            try:
                loc = frame.locator(sel).first
                if loc.count() and loc.is_visible():
                    loc.click(timeout=3000)
                    host = (frame.url or "").split("/")[2]
                    return f"{sel} @ {host}"
            except Exception:
                continue
    return ""


def _detect_captcha(page) -> bool:
    """hCaptcha (iframe de paiement) OU Turnstile Cloudflare (interstitiel Epic).

    Le Turnstile est servi par Epic lui-même sur une page "Encore une étape /
    Remplissez l'enquête de sécurité" dès qu'on charge le store avec une session
    authentifiée. Il ne se résout jamais seul (sondé 90 s le 2026-08-09).

    Ça dépend de l'IP, et pas de la même façon partout : le 2026-09-09, à
    quelques minutes d'intervalle avec la même session et le même jeu, GitHub
    Actions (Azure) restait sur "Un instant…" pendant 90 s là où la VM Oracle
    chargeait la page complète et lisait son CTA. Ne pas généraliser depuis un
    seul hébergeur.
    """
    if _visible_captcha_frames(page):
        return True
    try:
        return page.title().strip().lower() in ("un instant…", "un instant...",
                                                "just a moment…", "just a moment...")
    except Exception:
        return False


# Cookies posés par Cloudflare (laissez-passer + score anti-bot). À NE JAMAIS
# transporter d'un run à l'autre : cf_clearance est lié à l'IP/UA/navigateur
# qui l'a obtenu, et __cf_bm porte le score attribué lors d'un passage
# précédent. Réinjectés, ils déclenchent l'interstitiel "Un instant…".
# Mesuré le 2026-09-10, même session, même IP Oracle, même minute : avec ces
# cookies → challenge ; sans eux → page chargée et compte connecté. Le
# navigateur regagne de lui-même un laissez-passer neuf à chaque run.
# (C'était la vraie cause du blocage depuis mai, pas l'IP de datacenter.)
CF_COOKIE_PREFIXES = ("cf_", "__cf", "_cfuvid")


def _strip_cloudflare(state: dict) -> dict:
    cookies = state.get("cookies") or []
    kept = [c for c in cookies if not c.get("name", "").startswith(CF_COOKIE_PREFIXES)]
    return {**state, "cookies": kept}


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
        )
        if not HEADFUL:
            context_kwargs["user_agent"] = UA

        if b64:
            # Mode CI / prod : storage_state depuis base64 → fichier temp.
            # Strip espaces/BOM/newlines (peut être pollué par l'encoding du shell qui a set le secret)
            b64_clean = b64.strip().lstrip("﻿").replace("\r", "").replace("\n", "")
            self._state_tmp = Path(tempfile.mkdtemp()) / "epic_storage_state.json"
            state = json.loads(base64.b64decode(b64_clean, validate=False))
            self._state_tmp.write_text(json.dumps(_strip_cloudflare(state)), encoding="utf-8")
            browser = self._pw.chromium.launch(headless=not HEADFUL, args=launch_args)
            self._context = browser.new_context(storage_state=str(self._state_tmp), **context_kwargs)
            self._browser = browser
            print(f"[CLAIMER] Mode CI (storage_state b64, {self._state_tmp.stat().st_size} bytes)")
        elif state_file_env and Path(state_file_env).exists():
            # Mode local prod-like : storage_state.json explicite
            browser = self._pw.chromium.launch(headless=not DEBUG_CLAIM, args=launch_args)
            state = json.loads(Path(state_file_env).read_text(encoding="utf-8"))
            self._context = browser.new_context(storage_state=_strip_cloudflare(state), **context_kwargs)
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
            state = _strip_cloudflare(self._context.storage_state())
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

            # domcontentloaded ne garantit que le squelette : sans cette
            # attente, tout ce qui suit lit un CTA vide (cf. _wait_cta_ready).
            label = _wait_cta_ready(page)
            print(f"[CLAIM] CTA = {label!r}" if label
                  else "[CLAIM] CTA toujours vide après 30 s")

            if _detect_owned(page):
                print("[CLAIM] Déjà dans la bibliothèque.")
                return ClaimOutcome.OWNED, ""

            # 0. Garde-fou prix — rien n'est cliqué tant que ce n'est pas à 0 €
            is_free, why = _is_free_offer(page)
            if not is_free:
                # Distinguer "offre payante" de "page jamais rendue" : sinon le
                # footer Discord annonce "plus gratuit" alors que le vrai motif
                # est un challenge Cloudflare, et on cherche au mauvais endroit.
                if _detect_captcha(page):
                    print("[CLAIM] ⛔ Challenge Cloudflare — claim impossible ici")
                    _shot(page, "challenge")
                    return ClaimOutcome.CAPTCHA, "Turnstile Cloudflare sur la page produit"
                print(f"[CLAIM] ⛔ ABANDON — {why}")
                _shot(page, "not_free")
                return ClaimOutcome.NOT_FREE, why
            print(f"[CLAIM] Prix vérifié : gratuit (CTA {why!r})")

            # 0 bis. Enquête de sécurité à case unique : on la coche nous-mêmes.
            hit = _try_captcha_checkbox(page)
            if hit:
                print(f"[CLAIM] Case anti-robot cochée ({hit})", flush=True)
                _shot(page, "captcha_case")
                page.wait_for_timeout(3000)

            # 1. Click "Obtenir"
            # no_wait_after : Epic programme une navigation qui n'aboutit jamais
            # (le paiement s'ouvre en surcouche), et Playwright resterait sinon
            # bloqué sur "waiting for scheduled navigations to finish".
            page.locator(SELECTORS["purchase_cta"]).first.click(
                timeout=10000, no_wait_after=True)

            # 2. Popup "Appareil non compatible" : en UA native le navigateur
            # s'annonce Linux, et Epic demande confirmation pour un jeu Windows.
            # Visé par son texte — les classes CSS de device_continue sont
            # générées et changent au gré des déploiements d'Epic.
            if _click_button_by_text(page, ["Continuer", "Continue"], timeout_ms=4000):
                print("[CLAIM] Popup 'Appareil non compatible' → Continuer")
            else:
                try:
                    page.locator(SELECTORS["device_continue"]).last.click(timeout=2000)
                except PWTimeout:
                    pass

            # 3. Iframe checkout
            iframe_handle = page.wait_for_selector(SELECTORS["iframe"], timeout=30000)
            frame = iframe_handle.content_frame()
            if not frame:
                return ClaimOutcome.FAILED, "Iframe checkout introuvable"

            # 4-5. Écran de paiement. Deux boutons s'y succèdent dans un ordre
            # variable : "Ajouter à la bibliothèque", puis le cartouche
            # "Informations sur le droit de rétractation" (J'accepte) qui le
            # RECOUVRE. Les traiter en deux étapes séparées faisait tourner le
            # bot sur un bouton devenu inaccessible pendant que le cartouche
            # attendait derrière (mesuré le 2026-09-14, capture à l'appui).
            # Une seule boucle essaie donc les deux à chaque tour, jusqu'à ce que
            # l'iframe se ferme — ce qui signe la fin du claim.
            page.wait_for_timeout(3000)
            _shot(page, "iframe")
            deadline = time.monotonic() + max(45, WAIT_HUMAN)
            clicked = []
            signale = False
            while time.monotonic() < deadline:
                handle = page.query_selector(SELECTORS["iframe"])
                if not handle:
                    break                       # iframe fermée → claim finalisé
                hit = _try_captcha_checkbox(page)
                if hit:
                    print(f"[CLAIM] Case anti-robot cochée ({hit})", flush=True)
                    _shot(page, "captcha_case")
                    page.wait_for_timeout(3000)

                frame_now = handle.content_frame()
                if frame_now:
                    # EULA d'abord : quand il s'affiche, il est au-dessus du reste.
                    if _click_button_by_text(frame_now, EULA_AGREE_TEXTS, timeout_ms=800):
                        clicked.append("J'accepte")
                        page.wait_for_timeout(2000)
                    elif _click_button_by_text(frame_now, PLACE_ORDER_TEXTS, timeout_ms=800):
                        clicked.append("Ajouter à la bibliothèque")
                        page.wait_for_timeout(2000)
                if WAIT_HUMAN and not signale and _detect_captcha(page):
                    signale = True
                    _shot(page, "survey")
                    print("[CLAIM] ⏳ Enquête de sécurité affichée — à résoudre à la main "
                          f"({int(deadline - time.monotonic())} s restantes)", flush=True)
                page.wait_for_timeout(1000)
            print(f"[CLAIM] Boutons cliqués : {sorted(set(clicked)) or 'aucun'}")
            if not clicked:
                _shot(page, "no_button")
                # Le bot n'a rien cliqué, mais quelqu'un a pu finir l'achat à la
                # main pendant l'enquête de sécurité. Vu le 2026-09-17 sur Shogun
                # Showdown : jeu bien obtenu, rapporté en échec — ce qui, en prod,
                # enverrait un "auto-claim échoué" pour un jeu acquis.
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    verif = _wait_cta_ready(page)
                    print(f"[CLAIM] CTA après vérification = {verif!r}")
                    if _detect_owned(page):
                        print("[CLAIM] ✅ SUCCESS (finalisé à la main pendant l'enquête)")
                        return ClaimOutcome.SUCCESS, ""
                except PWTimeout:
                    pass
                if _detect_captcha(page):
                    return ClaimOutcome.CAPTCHA, "enquête de sécurité non résolue"
                return ClaimOutcome.TIMEOUT, "Bouton principal introuvable"

            # 6. Wait + refresh + vérification
            page.wait_for_timeout(3000)
            _shot(page, "after_claim")
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            final = _wait_cta_ready(page)   # sinon CTA vide → faux échec
            print(f"[CLAIM] CTA après refresh = {final!r}")
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
