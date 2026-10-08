# 🎮 Epic Free Games Discord

Bot GitHub Actions qui détecte les jeux gratuits Epic Games Store et te
notifie sur Discord avec un lien direct pour les réclamer en 2 clics.

**Ce qu'il fait :**
- 🎮 Notifie les jeux gratuits **de la semaine** (1-2 jeux/semaine)
- 🔜 Notifie les jeux gratuits **à venir la semaine prochaine**
- 💎 Détecte les jeux à **-100% surprise** hors promo hebdo (rare)
- 📱 Notifie les jeux gratuits **mobiles** (iOS/Android) via l'API du store mobile Epic
- ⏰ Affiche les **dates de début/fin** avec timestamps Discord auto-localisés
- 🛒 Envoie un **récapitulatif** quand plusieurs jeux sortent ensemble, avec un lien
  qui ouvre le panier Epic déjà rempli : tout se réclame en une seule validation
- ❌ **Auto-claim** : abandonné en septembre 2026 (voir [pourquoi](#-auto-claim--abandonné))

---

## 📁 Structure

```
├── main.py                    → Orchestrateur principal
├── preview.py                 → Test local des notifs (sans toucher au state)
├── config.py                  → Configuration centralisée
├── epic.py                    → API Epic Games Store
├── mobile.py                  → Jeux gratuits mobiles (API du store mobile Epic)
├── notifier.py                → Notifications Discord
├── state.py                   → Gestion état persistant
├── logger.py                  → Logs
├── test_recap.py              → Test du récap et de son bouton panier
│
├── requirements.txt
├── .env.example
└── .github/workflows/
    ├── epic.yml               → Workflow principal (le seul qui tourne tout seul)
    └── test-recap.yml         → Lance test_recap.py à la main
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
| `DISCORD_WEBHOOK` | ✅ | Webhook salon jeux gratuits |
| `ALERT_WEBHOOK`   | ❌ | Webhook salon alertes (défaut = DISCORD_WEBHOOK) |
| `ROLE_ID`         | ❌ | ID rôle Discord à mentionner |

### 3. Créer la branche `datas`
```bash
git checkout --orphan datas
git rm -rf .
echo '{"games":{}}' > state.json
git add state.json
git commit -m "init datas branch"
git push -u origin datas
git checkout main
```

### 4. C'est tout
Va dans Actions → "Run workflow" pour tester.

---

## 💡 Fonctionnement

- Le workflow tourne **toutes les 20 min** (minutes 8, 28 et 48, jamais à l'heure
  pile : c'est le créneau où GitHub retarde ou supprime le plus de runs planifiés).
  Ça couvre les jeux surprises, qui n'ont pas d'horaire fixe.
- **Jeudi** : Epic publie à 11h heure de New York (17h à Paris). Des crons
  supplémentaires tombent entre 10h40 et 11h20 (fuseau `America/New_York`, donc
  changements d'heure gérés tout seuls). Un run qui arrive jusqu'à 25 min avant
  la sortie **attend** qu'elle ait lieu au lieu de repartir, puis recharge l'API
  jusqu'à ce qu'elle ait basculé.
- En pratique, GitHub saute une bonne partie des crons (parfois 3 à 6 h sans
  run). Le run de sortie du jeudi fait donc tout lui-même : si le giveaway
  mobile n'est pas encore ouvert (il peut avoir quelques minutes de retard sur
  le PC), il le guette jusqu'à 15 min avant d'envoyer les notifs.
- Un seul run à la fois (`concurrency`) : pas de notif en double.
- Quand un run a plusieurs notifs, elles partent toujours dans le même ordre :
  violet (à venir), vert (gratuit PC), rouge (gratuit mobile), jaune (surprise),
  puis le récap. Ordre réglable via `OUTBOX_ORDER` dans `main.py`.
- `state.json` n'est poussé sur `datas` que s'il a changé.
- À chaque nouveau jeu détecté → notif Discord avec image, prix, dates et lien direct
- Tu cliques sur le lien → Epic ouvre la page → tu réclames en 2 clics
- Si au moins 2 jeux sortent dans le même run → un récap avec le lien panier, pour
  tout réclamer d'un coup

---

## 🧪 Tester en local

Pour prévisualiser les notifs sans toucher au `state.json` :

```bash
pip install -r requirements.txt
cp .env.example .env  # puis remplis DISCORD_WEBHOOK dedans
python preview.py
```

---

## ❌ Auto-claim — abandonné

**Décision finale (septembre 2026)** : le bot notifie, il ne réclame pas. Le
code d'auto-claim a été retiré de `main` le 08/10/2026. Il reste entier au tag
[`archive/auto-claim`](../../tree/archive/auto-claim) (`git checkout archive/auto-claim`),
avec ses scripts de diagnostic et ses workflows de test.

### Pourquoi

Epic protège la validation de commande par un **hCaptcha Enterprise**. Depuis le
navigateur habituel du propriétaire du compte, il reste invisible. Depuis
n'importe quelle autre machine, il exige un défi à images qu'aucun bot ne passe
seul.

Mesuré depuis une VM Oracle en septembre 2026 : le bot va jusqu'au bout du
paiement, puis le défi tombe au clic « Ajouter à la bibliothèque », quels que
soient l'IP (même résidentielle), le navigateur (vrai Chrome, mode furtif) ou la
session Epic utilisée.

Les deux dernières voies ont été écartées : payer un solveur de captcha, ou faire
tourner le bot sur son propre PC allumé en permanence. Le détail de l'enquête est
dans [AUTO_CLAIM_FINDINGS.md](../../blob/archive/auto-claim/AUTO_CLAIM_FINDINGS.md).

En pratique, le lien panier du récap fait le travail en une seule validation.

---

## 🔧 Si un jour ça casse

Le bot tourne sans entretien. Si les notifs s'arrêtent :

| Symptôme | Cause probable | Quoi faire |
|---|---|---|
| Plus aucune notif | Le workflow échoue | Onglet **Actions** → ouvrir le dernier run en rouge |
| Mail de GitHub « scheduled workflow disabled » | 60 jours sans activité sur le dépôt public | **Actions** → *Epic Free Games Bot* → **Enable workflow** |
| Plus de notif après avoir modifié le salon Discord | Webhook supprimé ou régénéré | Coller la nouvelle URL dans le secret `DISCORD_WEBHOOK` |
| « ⚠️ API Epic Games inaccessible » (une alerte par panne) qui ne se résout pas | Epic a changé son API | Adapter `epic.py` |

Pour lancer une vérification à la main : **Actions** → *Epic Free Games Bot* →
**Run workflow** (ou un `POST` sur l'API `workflows/epic.yml/dispatches`). Les jeux déjà notifiés ne sont pas renvoyés.
