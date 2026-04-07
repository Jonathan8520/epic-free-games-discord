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
| `EPIC_REFRESH_TOKEN` | ❌* | Refresh token Epic (~1 an) — **recommandé** |
| `EPIC_BEARER_TOKEN` | ❌ | Token Bearer Epic (fallback manuel, ~8h) |
| `EPIC_SESSION_AP` | ❌ | Cookie EPIC_SESSION_AP (fallback manuel) |
| `CLAIM_RETRIES` | ❌ | Nombre de retries (défaut : 3) |

*Requis si `AUTO_CLAIM=true`. Le refresh token est la méthode recommandée : il dure ~1 an et le bot rafraîchit automatiquement le bearer token à chaque run.

### 3. Générer le refresh token Epic (recommandé)

Le refresh token doit être généré **une seule fois en local** via `bootstrap.py`.
Il dure ~1 an et le bot se rafraîchit tout seul ensuite.

1. **Connecte-toi** à Epic Games dans ton navigateur : https://www.epicgames.com
2. **Visite cette URL** pour obtenir un authorization code :
   ```
   https://www.epicgames.com/id/api/redirect?clientId=34a02cf8f4414e29b15921876da36f9a&responseType=code
   ```
3. **Copie la valeur** du champ `authorizationCode` dans le JSON affiché
4. **Lance le script** en local :
   ```bash
   pip install requests
   python bootstrap.py <authorizationCode>
   ```
5. **Copie le refresh token** affiché → secret GitHub `EPIC_REFRESH_TOKEN`

> Le authorization code est valable **5 minutes** et usable une seule fois.
> Si ça expire, recharge l'URL pour en obtenir un nouveau.
> Quand le refresh token expire (~1 an), le bot t'enverra une alerte Discord.

<details>
<summary>Méthode alternative (tokens manuels, expire vite)</summary>

**EPIC_BEARER_TOKEN :**
- Onglet Network → recharge la page → clique une requête epicgames.com
- Copie la valeur du header `Authorization` → retire le préfixe `Bearer `

**EPIC_SESSION_AP :**
- Onglet Application → Cookies → `https://store.epicgames.com`
- Copie la valeur du cookie `EPIC_SESSION_AP`

> ⚠️ Ces tokens expirent après quelques heures/semaines.
</details>

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
