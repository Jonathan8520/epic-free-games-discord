# 🎮 Epic Free Games Bot v3

Bot GitHub Actions qui détecte les jeux gratuits Epic Games Store et te
notifie sur Discord avec un lien direct pour les réclamer en 2 clics.

---

## 📁 Structure

```
├── main.py                    → Orchestrateur principal
├── config.py                  → Configuration centralisée
├── epic.py                    → API Epic Games Store
├── mobile.py                  → Jeux gratuits mobiles (GamerPower)
├── notifier.py                → Notifications Discord
├── scheduler.py               → Garde intelligente (évite les runs inutiles)
├── state.py                   → Gestion état persistant
├── logger.py                  → Logs
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
- Un pour les **alertes techniques** (`ALERT_WEBHOOK`) — optionnel

### 2. Ajouter les secrets GitHub
Settings → Secrets and variables → Actions → New repository secret

| Secret | Requis | Description |
|---|---|---|
| `DISCORD_WEBHOOK` | ✅ | Webhook salon jeux gratuits |
| `ALERT_WEBHOOK`   | ❌ | Webhook salon alertes (défaut = DISCORD_WEBHOOK) |
| `ROLE_ID`         | ❌ | ID rôle Discord à mentionner |

### 3. C'est tout
Va dans Actions → "Run workflow" pour tester.

---

## 💡 Fonctionnement

- Le workflow tourne **toutes les heures** (cron horaire)
- Le scheduler Python filtre :
  - Jeudi 15h–20h UTC → vérification à chaque run (Epic publie ~16h-17h UTC)
  - Reste du temps → vérification seulement si le dernier check date de +1h
- À chaque nouveau jeu détecté → notif Discord avec image, prix et lien direct
- Tu cliques sur le lien → Epic ouvre la page → tu réclames en 2 clics
- Heartbeat hebdomadaire dans le salon alertes pour confirmer que le bot est vivant

---

## ❓ Pourquoi pas d'auto-claim ?

Epic ne propose **aucune API publique** pour réclamer les jeux gratuits.
Les seules options sont :
- **Browser automation** (Playwright/Puppeteer) → lourd, fragile, risque de captcha
- **Tokens utilisateur** → expirent, rotation forcée, l'endpoint de checkout web refuse les tokens API

Pour 10 secondes par semaine de clic manuel, ça ne vaut pas la complexité.
Le bot fait l'essentiel : **te prévenir à temps** pour ne rater aucun jeu.
