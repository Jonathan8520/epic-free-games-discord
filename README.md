# 🎮 Epic Free Games Discord

Bot GitHub Actions qui détecte les jeux gratuits Epic Games Store et te
notifie sur Discord avec un lien direct pour les réclamer en 2 clics.

**Ce qu'il fait :**
- 🎮 Notifie les jeux gratuits **de la semaine** (1-2 jeux/semaine)
- 🔜 Notifie les jeux gratuits **à venir la semaine prochaine**
- 💎 Détecte les jeux à **-100% surprise** hors promo hebdo (rare)
- 📱 Notifie les jeux gratuits **mobiles** (iOS/Android) via GamerPower
- ⏰ Affiche les **dates de début/fin** avec timestamps Discord auto-localisés
- ✅ **Auto-claim optionnel** — réclame les jeux directement sur ton compte Epic (voir plus bas)

---

## 📁 Structure

```
├── main.py                    → Orchestrateur principal
├── preview.py                 → Test local des notifs (sans toucher au state)
├── config.py                  → Configuration centralisée
├── epic.py                    → API Epic Games Store
├── mobile.py                  → Jeux gratuits mobiles (GamerPower)
├── notifier.py                → Notifications Discord
├── scheduler.py               → Garde intelligente (évite les runs inutiles)
├── state.py                   → Gestion état persistant
├── logger.py                  → Logs
├── auth.py                    → OAuth Epic (refresh token launcher)         [auto-claim]
├── claimer.py                 → POST sur egs-platform-service quickPurchase  [auto-claim]
├── gh_secrets.py              → Update du EPIC_REFRESH_TOKEN via API GitHub  [auto-claim]
├── test_claim.py              → Script de test isolé du claim                [debug]
├── requirements.txt
└── .github/workflows/epic.yml → Workflow GitHub Actions
```

Le `state.json` vit sur une **branche `datas`** séparée pour garder `main` propre.

---

## 🚀 Setup

### 1. Créer un webhook Discord
Paramètres du salon → Intégrations → Webhooks → Nouveau webhook → copier l'URL.

Tu peux créer deux webhooks :
- Un pour les **jeux gratuits** (`DISCORD_WEBHOOK`)
- Un pour les **alertes techniques** (`ALERT_WEBHOOK`) — optionnel

### 2. Ajouter les secrets GitHub
Settings → Secrets and variables → Actions → New repository secret

| Secret | Requis | Description |
|---|---|---|
| `DISCORD_WEBHOOK`    | ✅ | Webhook salon jeux gratuits |
| `ALERT_WEBHOOK`      | ❌ | Webhook salon alertes (défaut = DISCORD_WEBHOOK) |
| `ROLE_ID`            | ❌ | ID rôle Discord à mentionner |
| `EPIC_REFRESH_TOKEN` | ❌ | Auto-claim — refresh token launcher Epic (voir [Auto-claim](#-auto-claim-optionnel)) |
| `GH_PAT`             | ❌ | Auto-claim — PAT GitHub avec scope `secrets:write` |

Et dans l'onglet **Variables** (pas Secrets) :

| Variable | Requise | Description |
|---|---|---|
| `AUTO_CLAIM` | ❌ | Mettre `true` pour activer l'auto-claim |

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

Pour prévisualiser les notifs sans toucher au `state.json` (utile pour itérer sur le design) :

```bash
pip install -r requirements.txt
export DISCORD_WEBHOOK="https://discord.com/api/webhooks/..."
python preview.py
```

---

## ✅ Auto-claim (optionnel)

**Mise à jour 2026** : Epic a (silencieusement) levé le captcha sur son endpoint
de claim launcher. Un POST `egs-platform-service.store.epicgames.com/api/v2/private/egs/purchase/quickPurchase`
avec un Bearer token launcher suffit pour réclamer un jeu gratuit. Pas de
browser headless, pas de Playwright, pas de captcha à résoudre.

Le bot peut donc maintenant **réclamer automatiquement** chaque jeu gratuit
sur ton compte Epic, juste après la notif Discord. Le footer de l'embed
indique le statut :

- `✅ Réclamé automatiquement sur ton compte`
- `ℹ️ Déjà dans ta bibliothèque`
- `⚠️ Auto-claim échoué — clique pour récupérer`

### Garde-fous

Aucun risque de payer un jeu non gratuit :

1. `epic.py` ne retourne que des jeux dont la promo `discountPercentage == 0` est active
2. `claimer._is_free()` re-vérifie le prix juste avant le POST via GraphQL
3. Epic refuse de débiter sans `paymentMethod` dans le payload (qu'on n'envoie jamais)

### Activation

#### a) Générer un refresh token Epic

1. Connecte-toi à https://www.epicgames.com
2. Ouvre : https://www.epicgames.com/id/api/redirect?clientId=34a02cf8f4414e29b15921876da36f9a&responseType=code
3. Copie la valeur `authorizationCode` du JSON (5 min de validité)
4. Lance :
   ```bash
   python test_claim.py --bootstrap <authorizationCode>
   ```
5. Copie le `refresh_token` affiché → secret GitHub `EPIC_REFRESH_TOKEN`

Le refresh token est valide ~1 an. Epic en émet un nouveau à chaque usage —
le bot le re-pousse automatiquement dans le secret GitHub via l'API.

#### b) Générer un PAT GitHub fine-grained

Pour permettre au bot de mettre à jour `EPIC_REFRESH_TOKEN` après rotation :

1. https://github.com/settings/personal-access-tokens → **Generate new token**
2. **Repository access** : sélectionne uniquement ce repo
3. **Permissions → Repository → Secrets** : **Read and write**
4. Pas d'autre permission nécessaire
5. Copie le token → secret GitHub `GH_PAT`

#### c) Activer

Dans l'onglet **Variables** des Actions du repo :
- `AUTO_CLAIM` = `true`

Au prochain run, les jeux gratuits seront réclamés automatiquement.

### Désactiver

Met `AUTO_CLAIM` à `false` (ou supprime la variable). Aucun impact sur les notifs.

### Tester en local

Le script `test_claim.py` permet de tester le flow indépendamment du bot :

```bash
$env:EPIC_REFRESH_TOKEN = "..."
python test_claim.py rocket-league--triplex-black-wheels
# ou un slug quelconque, ou --manual <namespace> <offerId>
```
