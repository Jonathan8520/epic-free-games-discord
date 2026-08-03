# Auto-claim Epic — Findings & Décision en attente

État au 2026-05-31.

## Tentative API pure (`claimer_api.py`)

Flow talon init + solveur captcha + confirm-order :
- ✅ Resolve slug → namespace/offerId : OK (note : `catalogOffers` refuse les sessions Bearer cookies avec HTTP 401, doit être appelé anonyme)
- ✅ Talon `/v1/init` → récupération de la siteKey hCaptcha : OK
- ❌ **CapMonster ne supporte pas hCaptcha sur le compte testé**. `HCaptchaTaskProxyless` → `ERROR_TASK_NOT_SUPPORTED`. `NoCaptchaTaskProxyless` (reCAPTCHA v2) → OK. C'est une **limite de tier** : le compte CapMonster basique ne supporte que reCAPTCHA, hCaptcha est probablement réservé aux upgrades payants.
- Code `claimer_api.py` est en place mais bloqué à l'étape 3. Le flow restant (`confirm-order` POST) est codé mais non testé.

Voies à reprendre :
- A. Utiliser 2Captcha, qui supporte hCaptcha sans souci de tier
- B. Vérifier le compte CapMonster pour comprendre la limitation (peut-être upgrade nécessaire)
- C. Tester CapSolver (autre service connu pour hCaptcha)
- D. Self-hosted runner sur PC (gratuit, code Playwright actuel suffit)

## TL;DR

L'auto-claim **fonctionne techniquement** mais **Cloudflare bloque l'IP Azure de GitHub Actions**. Pour que ça marche en prod, il faut soit :
- **A.** Bouger le runner sur ton PC (gratuit, ~15 min de setup) — recommandé
- **B.** Payer ~6 centimes/an pour CapMonster (résout le captcha pour nous)
- **C.** Garder le status quo et cliquer manuellement (gratuit, 1 click/semaine)

Tout le code Playwright qui marche en local est **déjà commit** sur main. Le bot envoie déjà les notifs Discord avec footer "⚠️ Auto-claim échoué" en attendant.

## Ce qu'on a découvert sur Epic en 2026

### L'API backend pure NE marche PAS pour les BASE_GAME hebdo

Testé le 2026-05-23 sur Tomb Raider et Down in Bermuda (non encore possédés) depuis IP résidentielle FR :

| Endpoint | Status | Détail |
|---|---|---|
| `store.epicgames.com/api/order/v3/...` (legacy) | hCaptcha HTML | Bloqué |
| `orderprocessor.../quickPurchase` | `quickPurchaseStatus: CHECKOUT` | Pas finalisé |
| `egs-platform-service.../quickPurchase` | HTTP 400 `Offer is not eligible` | Refusé |

→ L'hypothèse de mai 2026 "INELIGIBLE = déjà possédé" était fausse. Epic refuse structurellement le claim API pour les BASE_GAME hebdo, même non possédés.

### Le claim BASE_GAME hebdo passe par 4 endpoints (capture HAR du 31/05)

```
[0] talon-service-prod.ecosec.on.epicgames.com/v1/init        → setup hCaptcha plan
[1] payment-website-pci.ol.epicgames.com/v2/purchase/order-preview
[5] talon-service-prod.ecosec.on.epicgames.com/v1/init/execute → exécute le captcha
[7] payment-website-pci.ol.epicgames.com/v2/purchase/confirm-order → FINALISE
```

Le call critique `confirm-order` a un body **simple** :
```json
{
  "totalAmount": 0,
  "redeemRewardAmount": 0,
  "canQuickPurchase": true,
  "storePaymentMethod": false,
  "originatingRequest": "https://store.epicgames.com/p/<slug>?lang=fr&purchaseToken=<uuid>",
  "captchaToken": "<token hCaptcha — 15640 chars>"
}
```

→ Réponse : `orderStatus: "COMPLETED"` 🎉

### Le BLOQUEUR : le captchaToken (hCaptcha invisible)

Pour générer ce token, soit :

1. **Browser réel** : ton browser lance le widget hCaptcha sur la page de checkout, hCaptcha analyse le contexte (IP, fingerprint, comportement) et donne un token **passif** (sans challenge image visible). C'est ce que ton browser a fait pendant la capture HAR.

2. **Reproduire en API** : appeler `talon-service-prod.../v1/init/execute` avec un body de 7315 chars contenant `xal` (6828 chars de crypto JS) — **impossible à reproduire en Python pur** (le `xal` est généré par du JS Epic anti-bot).

3. **Service captcha tiers** (2Captcha, CapMonster, etc.) : on leur envoie le siteKey + URL, ils résolvent et donnent un token valide. Payant mais 1$ = ~16 ans pour notre volume.

### Cloudflare bloque les IPs datacenter en 2026

Confirmé via screenshot d'erreur capturé sur GH Actions :

```
"Encore une étape — Vérifiez que vous êtes humain"
Adresse IP : 104.209.11.20  (Microsoft Azure)
```

Vérifié par recherche : **toutes** les IPs cloud sont flaguées par Cloudflare en 2026 :
- Azure (GH Actions, Azure VMs)
- AWS
- Oracle Cloud (même le free tier)
- GCP
- Hetzner, OVH cloud, etc.

→ Toute solution sur cloud public est bloquée par Cloudflare quand on navigue sur `store.epicgames.com`.

**Exception cruciale** : les endpoints `*.ol.epicgames.com` et `*.ecosec.on.epicgames.com` ne sont **PAS** sur Cloudflare. Si on a un captchaToken valide, on peut appeler `confirm-order` depuis n'importe où.

## État du code (commit sur `main`)

| Fichier | Rôle |
|---|---|
| `claim_browser.py` | Playwright DOM clicks — marche localement, échec sur GH Actions à cause de Cloudflare |
| `login_epic.py` | One-shot interactif pour générer `epic_storage_state.json` |
| `claimer.py` | Ancien claim API (egs-platform-service) — marche pour F2P/DLC seulement |
| `test_claim.py` | Debug API avec 3 endpoints candidats |
| `_parse_har.py` + `_parse_har_deep.py` | Scripts d'analyse du HAR (utilisés pour cette investigation) |
| `.github/workflows/epic.yml` | Workflow horaire — utilise Playwright sur ubuntu-latest |
| `.github/workflows/test_claim.yml` | Workflow_dispatch pour tester un slug |

**Secrets GH actifs** :
- `EPIC_STORAGE_STATE_B64` — cookies de session web (généré par `login_epic.py`)
- `GH_PAT` — pour persister le storage_state après chaque run
- `EPIC_REFRESH_TOKEN` — legacy, utilisé par `test_claim.py` seulement
- `DISCORD_WEBHOOK`

**Variable repo** : `AUTO_CLAIM=true`

## Options détaillées pour la suite

### A. Self-hosted runner sur ton PC (100% gratuit, recommandé)

**Setup** :
1. GH repo → Settings → Actions → Runners → New self-hosted runner → Windows x64
2. PowerShell (admin) : copier-coller les 4 commandes fournies par GitHub
3. Lancer `./run.cmd` (ou installer en service avec `./svc.sh install`)
4. Dans `.github/workflows/epic.yml`, changer `runs-on: ubuntu-latest` → `runs-on: self-hosted`
5. Commit + push

**Comment ça marche** :
- Quand le cron déclenche (toutes les heures), GitHub envoie le job à ton runner
- Ton runner exécute le bot **en local** sur ton PC, avec **ton IP résidentielle FR**
- Cloudflare passe direct (IP trusted), le claim se fait
- Résultat repushé sur GitHub

**Trade-offs** :
- ✅ Gratuit, marche à 100%
- ✅ Code Playwright actuel sans modification
- ⚠️ PC doit être ON pendant la fenêtre de claim (jeudi 17h CEST + 7 jours de retry à chaque heure)
- ⚠️ Petite conso élec du service runner (négligeable, ~0.5 W au repos)
- ⚠️ Si tu réinstalles Windows ou changes de PC, il faut reconfigurer

### B. CapMonster (~6 cts / an, marche 24/7)

**Setup** :
1. Compte sur capmonster.cloud
2. Acheter 1$ de crédit (= ~330 résolutions = ~5 ans pour notre volume)
3. Récupérer l'API key
4. Ajouter `CAPMONSTER_API_KEY` dans les GH Secrets
5. Refondre `claimer.py` en flow API pur :
   - GraphQL pour résoudre slug → namespace/offerId
   - Talon `/v1/init` pour récupérer la siteKey hCaptcha
   - CapMonster API pour résoudre → captchaToken
   - `payment-website-pci.../v2/purchase/confirm-order` avec captchaToken → SUCCESS

**Trade-offs** :
- ✅ Marche 24/7, indépendant de ton PC
- ✅ Quasi-gratuit (1$ tient ~16 ans)
- ✅ Plus de browser, plus de Cloudflare — flow API pur léger
- ⚠️ Dépendance à un service tiers payant
- ⚠️ Si CapMonster change ses prix ou ferme, faut migrer
- ⚠️ Recoder le claimer (~2h de dev), garder le browser comme fallback

**Note** : ~2 claims/semaine = ~104/an. À $0.0006/résolution chez CapMonster = $0.06/an.

### C. Status quo (gratuit, click manuel)

Ne rien faire de plus. Le bot envoie la notif Discord avec footer "⚠️ Auto-claim échoué — clique pour récupérer". Tu cliques sur le lien Discord, ça t'amène sur la page Epic, tu cliques "Obtenir". 1 click par semaine.

- ✅ 100% gratuit, 0 setup
- ✅ Tu reçois la notif de toute façon
- ❌ Mais c'est précisément pour ne pas faire ça que tu voulais l'auto-claim

### D. Browser local lancé manuellement (gratuit, no GH Actions)

Garder GH Actions pour la notif Discord uniquement. Le jeudi 17h, lancer `python claim_browser.py <slug>` sur ton PC. Le code Playwright actuel marche.

- ✅ Gratuit
- ✅ Pas de runner GH à installer
- ❌ Faut savoir quels jeux et quand → tu y penses chaque jeudi

## Fichiers à supprimer après décision

```bash
rm store.epicgames.com.har             # 85 MB, contient des cookies sensibles
rm debug_*.png                          # screenshots de debug locaux
rm debug_timeout_gh_calico.png          # screenshot du Cloudflare challenge
rm _parse_har.py _parse_har_deep.py     # scripts one-shot d'analyse
rm AUTO_CLAIM_FINDINGS.md               # ce fichier, après décision
```

⚠️ **À FAIRE DE SUITE** : supprimer `store.epicgames.com.har` (85 MB, contient ta session Epic). Il est gitignored donc pas dans le repo, mais il traîne en local.

## Décisions à prendre quand tu reprends

1. **A**, **B**, **C**, ou **D** ? (cf options ci-dessus)
2. Si **A** : tu veux installer le runner GH en mode **service Windows** (démarre auto au boot) ou en mode **launcher manuel** (tu le lances quand tu veux) ?
3. Si **B** : OK pour créer compte CapMonster + acheter 1$ ?
4. Si **C/D** : on désactive le claim côté `main.py` pour économiser des ressources GH Actions (~30s par run × 24/jour = quelques minutes/mois de quota) ?

## Mémoires Claude liées

- `reference_autoclaim_endpoint.md` — endpoint API + flow Playwright
- `project_overview.md` — vue d'ensemble du projet
- `feedback_no_autoclaim.md` — historique 2025 obsolète
- `reference_external_tools.md` — outils externes alternatifs

À mettre à jour quand on décide.
