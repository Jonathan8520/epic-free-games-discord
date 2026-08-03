# 🎮 Epic Free Games Discord

Bot GitHub Actions qui détecte les jeux gratuits Epic Games Store et te
notifie sur Discord avec un lien direct pour les réclamer en 2 clics.

**Ce qu'il fait :**
- 🎮 Notifie les jeux gratuits **de la semaine** (1-2 jeux/semaine)
- 🔜 Notifie les jeux gratuits **à venir la semaine prochaine**
- 💎 Détecte les jeux à **-100% surprise** hors promo hebdo (rare)
- 📱 Notifie les jeux gratuits **mobiles** (iOS/Android) via GamerPower
- ⏰ Affiche les **dates de début/fin** avec timestamps Discord auto-localisés
- ⚠️ **Auto-claim** — à l'arrêt depuis fin mai 2026 (voir [état actuel](#-auto-claim--état-de-larrêt-actuel))

---

## 📁 Structure

```
├── main.py                    → Orchestrateur principal
├── preview.py                 → Test local des notifs (sans toucher au state)
├── config.py                  → Configuration centralisée
├── epic.py                    → API Epic Games Store
├── mobile.py                  → Jeux gratuits mobiles (GamerPower)
├── notifier.py                → Notifications Discord (avec footers claim)
├── scheduler.py               → Garde intelligente (évite les runs inutiles)
├── state.py                   → Gestion état persistant
├── logger.py                  → Logs
│
│  Auto-claim — code présent mais bloqué (voir AUTO_CLAIM_FINDINGS.md)
├── claim_browser.py           → Playwright DOM clicks (marche en local, bloqué Cloudflare sur GH Actions)
├── claimer_api.py             → Tentative API pure avec CapMonster (incomplet, captcha solver à finaliser)
├── login_epic.py              → One-shot pour générer epic_storage_state.json
├── claimer.py                 → Ancien claim API legacy (marche encore pour F2P / DLC)
├── auth.py                    → OAuth Epic launcher (utilisé par claimer.py)
├── gh_secrets.py              → Update des secrets GH via API (rotation tokens)
├── test_claim.py              → Debug API claim (bootstrap + 3 endpoints candidats)
│
├── requirements.txt
├── .env.example
├── .github/workflows/
│   ├── epic.yml               → Workflow horaire principal
│   └── test_claim.yml         → workflow_dispatch pour tester claim_browser
└── AUTO_CLAIM_FINDINGS.md     → Investigation complète sur le claim Epic 2026 + options
```

Le `state.json` vit sur une **branche `datas`** séparée pour garder `main` propre.

---

## 🚀 Setup minimal (juste les notifs, sans auto-claim)

### 1. Créer un webhook Discord
Paramètres du salon → Intégrations → Webhooks → Nouveau webhook → copier l'URL.

Tu peux créer deux webhooks :
- Un pour les **jeux gratuits** (`DISCORD_WEBHOOK`)
- Un pour les **alertes techniques** (`ALERT_WEBHOOK`) — optionnel

### 2. Ajouter les secrets GitHub
Settings → Secrets and variables → Actions → New repository secret

| Secret | Requis | Description |
|---|---|---|
| `DISCORD_WEBHOOK` | ✅ | Webhook salon jeux gratuits |
| `ALERT_WEBHOOK`   | ❌ | Webhook salon alertes (défaut = DISCORD_WEBHOOK) |
| `ROLE_ID`         | ❌ | ID rôle Discord à mentionner |

### 3. Créer la branche `datas`
```bash
git checkout --orphan datas
git rm -rf .
echo '{"games":{},"last_check":null}' > state.json
git add state.json
git commit -m "init datas branch"
git push -u origin datas
git checkout main
```

### 4. C'est tout
Va dans Actions → "Run workflow" pour tester.

---

## 💡 Fonctionnement

- Le workflow tourne **toutes les heures** (cron horaire)
- Le scheduler Python filtre intelligemment :
  - Jeudi 15h–20h UTC → vérification à chaque run (Epic publie ~16h-17h UTC)
  - Reste du temps → vérification seulement si le dernier check date de +1h
- À chaque nouveau jeu détecté → notif Discord avec image, prix, dates et lien direct
- Tu cliques sur le lien → Epic ouvre la page → tu réclames en 2 clics

---

## 🧪 Tester en local

Pour prévisualiser les notifs sans toucher au `state.json` :

```bash
pip install -r requirements.txt
cp .env.example .env  # puis remplis DISCORD_WEBHOOK dedans
python preview.py
```

---

## ⚠️ Auto-claim — état de l'arrêt actuel

**État au 2026-05-31** : l'auto-claim ne fonctionne plus, **par choix temporaire**. Le bot envoie quand même les notifs Discord ; tu cliques manuellement sur le lien pour réclamer.

### Pourquoi c'est arrêté

Plusieurs barrages Epic mis en 2026 :

1. **L'API pure (claimer.py)** : marche pour F2P / DLC permanents (Valorant, Triplex…), mais **pas pour les BASE_GAME hebdo** (les jeux gratuits du jeudi). Epic répond `not eligible` ou `CHECKOUT` sur ces offers, quelle que soit l'IP.

2. **Le browser Playwright (claim_browser.py)** : marche parfaitement en local (testé sur Tomb Raider + Bermuda le 23/05) mais **bloqué par Cloudflare** sur GitHub Actions (les IPs Azure du runner sont flaguées comme datacenter et reçoivent un challenge "Vérifiez que vous êtes humain"). Même problème sur Oracle Cloud, AWS, etc.

3. **L'API du flow checkout (claimer_api.py)** : tentative en cours. On a capturé un HAR du flow manuel, identifié l'endpoint `payment-website-pci.ol.epicgames.com/v2/purchase/confirm-order` qui finalise le claim sans Cloudflare. **Le bloqueur unique** est qu'il exige un `captchaToken` hCaptcha qu'on doit obtenir via un service tiers (2Captcha, CapMonster, CapSolver…). Voir [AUTO_CLAIM_FINDINGS.md](AUTO_CLAIM_FINDINGS.md) pour les détails.

### Options pour le relancer

Documentées dans [AUTO_CLAIM_FINDINGS.md](AUTO_CLAIM_FINDINGS.md), mais en résumé :

| Option | Coût | Setup |
|---|---|---|
| **A. Self-hosted runner sur ton PC** | 0 € | ~15 min — IP résidentielle FR = pas de Cloudflare, code Playwright actuel marche direct |
| **B. Service de résolution captcha (2Captcha hCaptcha)** | ~1 $/3 ans | ~30 min — finir `claimer_api.py` + push API key en GH Secret |
| **C. Status quo** | 0 € | 0 min — clic manuel via la notif Discord (1 click/semaine) |

À toi de choisir quand tu veux relancer. Le bot continue à notifier correctement entre-temps.

### Tester en local (si tu veux jouer avec le claim)

Le code Playwright fonctionne sur ta machine (IP résidentielle) :

```bash
# 1. One-shot login (génère epic_storage_state.json)
python login_epic.py

# 2. Test claim sur un slug
python claim_browser.py tomb-raider-iiii-remastered-538640
```

Et l'ancien claim API (F2P / DLC seulement) :

```bash
$env:EPIC_REFRESH_TOKEN = "..."  # généré via test_claim.py --bootstrap
python test_claim.py rocket-league--triplex-black-wheels
```
