# 🎮 Epic Free Games Bot v3

Bot GitHub Actions complet pour détecter, notifier et réclamer automatiquement
les jeux gratuits Epic Games Store.

---

## 📁 Structure

```
├── main.py                    → Orchestrateur principal
├── config.py                  → Configuration centralisée
├── epic.py                    → API Epic Games Store
├── library.py                 → Vérification bibliothèque Epic
├── claimer.py                 → Réclamation automatique + retry
├── notifier.py                → Notifications Discord (jeux + alertes)
├── scheduler.py               → Garde intelligente (évite les runs inutiles)
├── state.py                   → Gestion état persistant
├── logger.py                  → Logs sécurisés (masque les tokens)
├── state.json                 → Persistance git (commité automatiquement)
├── requirements.txt
└── .github/workflows/epic.yml → Workflow GitHub Actions
```

---

## 🚀 Setup

### 1. Créer un webhook Discord
Paramètres du salon → Intégrations → Webhooks → Nouveau webhook → copier l'URL.

Tu peux créer deux webhooks :
- Un pour les **jeux gratuits** (`DISCORD_WEBHOOK`)
- Un pour les **alertes techniques** (`ALERT_WEBHOOK`) — optionnel, sinon les alertes vont dans le même salon

### 2. Ajouter les secrets GitHub
Settings → Secrets and variables → Actions → New repository secret

| Secret | Requis | Description |
|---|---|---|
| `DISCORD_WEBHOOK` | ✅ | Webhook salon jeux gratuits |
| `ALERT_WEBHOOK` | ❌ | Webhook salon alertes (défaut = DISCORD_WEBHOOK) |
| `ROLE_ID` | ❌ | ID rôle à mentionner |
| `AUTO_CLAIM` | ❌ | `true` pour activer la réclamation auto |
| `EPIC_BEARER_TOKEN` | ❌* | Token Bearer Epic |
| `EPIC_SESSION_AP` | ❌* | Cookie EPIC_SESSION_AP |
| `CLAIM_RETRIES` | ❌ | Nombre de retries (défaut : 3) |

*Requis si `AUTO_CLAIM=true`

### 3. Récupérer les cookies Epic

1. Va sur https://store.epicgames.com et connecte-toi
2. Ouvre les DevTools (F12)

**EPIC_BEARER_TOKEN :**
- Onglet Network → recharge la page → clique une requête epicgames.com
- Copie la valeur du header `Authorization` → retire le préfixe `Bearer `

**EPIC_SESSION_AP :**
- Onglet Application → Cookies → `https://store.epicgames.com`
- Copie la valeur du cookie `EPIC_SESSION_AP`

> ⚠️ Ces tokens expirent après quelques semaines. Le bot t'enverra une alerte Discord avec le lien direct pour les renouveler.

---

## ⚙️ Fonctionnement détaillé

### États d'un jeu dans `state.json`

| Statut | Signification |
|---|---|
| `notified` | Notifié dans Discord, réclamation en attente |
| `claimed` | Réclamé avec succès |
| `owned` | Déjà possédé (détecté via bibliothèque Epic) |
| `failed` | Échec réclamation — sera retenté (max 3 fois) |
| `eula_required` | EULA spécifique à accepter manuellement |
| `captcha` | Captcha détecté — réclamation manuelle requise |

### Notifications Discord

**Salon principal** (`DISCORD_WEBHOOK`) :
- Nouveau jeu gratuit détecté (embed avec image et prix original)
- Jeu réclamé avec succès
- Jeu déjà possédé

**Salon alertes** (`ALERT_WEBHOOK`) :
- 🔑 Cookies expirés → lien direct vers les secrets GitHub
- 📋 EULA requise → lien de réclamation manuelle
- 🤖 Captcha détecté → lien de réclamation manuelle
- ⚠️ Échec après tous les retries
- ⚠️ API Epic inaccessible
- 💚 Heartbeat hebdomadaire (stats : jeux réclamés, valeur économisée)

### Scheduler intelligent
- Jeudi 15h–20h UTC → vérification à chaque run (10 min si cron fréquent)
- Reste du temps → vérification seulement si le dernier check date de +1h

---

## 💡 Conseils

- Mets le repo en **privé** si tu veux que `state.json` (et son historique) ne soit pas public
- Le `[skip ci]` dans le commit de `state.json` évite une boucle infinie de workflows
- GitHub Actions offre 2000 min gratuites/mois sur repo privé, illimitées sur repo public
- Tu peux déclencher un run manuel via l'onglet Actions → "Run workflow" pour tester
