"""
bootstrap.py — Script à exécuter UNE SEULE FOIS en local pour obtenir
un refresh token launcher Epic Games (valable ~1 an).

Usage :
    1. Va sur https://www.epicgames.com et connecte-toi
    2. Va sur https://www.epicgames.com/id/api/redirect?clientId=34a02cf8f4414e29b15921876da36f9a&responseType=code
    3. Copie la valeur de "authorizationCode" dans la réponse JSON
    4. Lance : python bootstrap.py <authorizationCode>
    5. Copie le refresh_token affiché → secret GitHub EPIC_REFRESH_TOKEN

Le authorization code est valable 5 minutes seulement et usable une seule fois.
"""

import sys
from auth import exchange_code_for_tokens


REDIRECT_URL = (
    "https://www.epicgames.com/id/api/redirect"
    "?clientId=34a02cf8f4414e29b15921876da36f9a&responseType=code"
)


def main():
    if len(sys.argv) != 2:
        print("=" * 70)
        print("BOOTSTRAP — Génération du refresh token Epic Games launcher")
        print("=" * 70)
        print()
        print("Étape 1 — Connecte-toi à Epic Games dans ton navigateur :")
        print("  https://www.epicgames.com")
        print()
        print("Étape 2 — Ouvre cette URL pour obtenir un authorization code :")
        print(f"  {REDIRECT_URL}")
        print()
        print('Étape 3 — Copie la valeur du champ "authorizationCode" dans le JSON.')
        print()
        print("Étape 4 — Relance ce script avec le code :")
        print("  python bootstrap.py <authorizationCode>")
        print()
        sys.exit(1)

    code = sys.argv[1].strip()
    print(f"Échange du code contre des tokens Epic...")

    try:
        tokens = exchange_code_for_tokens(code)
    except Exception as e:
        print(f"\nERREUR : {e}")
        print("\nLe code est peut-être expiré (5 min de validité) ou déjà utilisé.")
        print(f"Récupère un nouveau code ici :\n  {REDIRECT_URL}")
        sys.exit(1)

    refresh_token = tokens.get("refresh_token", "")
    expires_at = tokens.get("refresh_expires_at", "?")
    account = tokens.get("displayName", "?")

    print()
    print("=" * 70)
    print(f"✅ Succès ! Compte : {account}")
    print(f"   Refresh token expire le : {expires_at}")
    print("=" * 70)
    print()
    print("Copie cette valeur dans le secret GitHub EPIC_REFRESH_TOKEN :")
    print()
    print(refresh_token)
    print()


if __name__ == "__main__":
    main()
