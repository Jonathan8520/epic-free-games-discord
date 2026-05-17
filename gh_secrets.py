"""
gh_secrets.py — Met à jour un secret du repo GitHub via l'API.

Utilisé pour persister le nouveau refresh_token Epic après chaque rotation
(Epic invalide l'ancien à chaque usage).

Nécessite un Personal Access Token (PAT) avec scope `repo` (classic) ou la
permission "Secrets: read & write" (fine-grained) sur le repo cible.
"""

import base64
import requests
from nacl import encoding, public
from logger import log


def _encrypt(public_key_b64: str, value: str) -> str:
    """Chiffre une valeur avec la public key du repo (libsodium SealedBox)."""
    pk = public.PublicKey(public_key_b64.encode(), encoding.Base64Encoder())
    sealed = public.SealedBox(pk).encrypt(value.encode())
    return base64.b64encode(sealed).decode()


def update_secret(repo: str, pat: str, name: str, value: str) -> bool:
    """
    Met à jour le secret Actions `name` du repo `owner/name` avec `value`.
    Retourne True si succès.
    """
    if not (repo and pat and name and value):
        log.error("[GH_SECRETS] Paramètres manquants — pas de mise à jour.")
        return False

    headers = {
        "Authorization": f"Bearer {pat}",
        "Accept"       : "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        # 1. Récupère la public key du repo
        r = requests.get(
            f"https://api.github.com/repos/{repo}/actions/secrets/public-key",
            headers=headers, timeout=15,
        )
        if r.status_code != 200:
            log.error(f"[GH_SECRETS] public-key HTTP {r.status_code} : {r.text[:200]}")
            return False
        key_data = r.json()
        encrypted = _encrypt(key_data["key"], value)

        # 2. PUT le secret chiffré
        r = requests.put(
            f"https://api.github.com/repos/{repo}/actions/secrets/{name}",
            headers=headers,
            json={"encrypted_value": encrypted, "key_id": key_data["key_id"]},
            timeout=15,
        )
        if r.status_code not in (201, 204):
            log.error(f"[GH_SECRETS] PUT {name} HTTP {r.status_code} : {r.text[:200]}")
            return False

        log.info(f"[GH_SECRETS] Secret {name} mis à jour.")
        return True

    except requests.RequestException as e:
        log.error(f"[GH_SECRETS] Erreur réseau : {e}")
        return False
