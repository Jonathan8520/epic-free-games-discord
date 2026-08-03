"""
_parse_har_deep.py — Extrait les détails complets des 2 calls critiques :
- talon init/execute (qui produit le captchaToken)
- payment-website confirm-order (qui finalise le claim)

Redact tout ce qui leak (cookies, tokens) avant affichage.
"""

import json
import sys
from pathlib import Path

TARGETS = [
    "talon-service-prod.ecosec.on.epicgames.com/v1/init",
    "payment-website-pci.ol.epicgames.com/v2/purchase/confirm-order",
    "payment-website-pci.ol.epicgames.com/v2/purchase/order-preview",
    "payment-website-pci.ol.epicgames.com/v2/purchase/get-earn-reward",
]

REDACT_HEADERS = {
    "cookie", "authorization", "x-csrf-token", "x-epic-csrf",
    "x-epic-session-id", "x-xsrf-token", "set-cookie",
}


def redact_value(v: str) -> str:
    return f"<REDACTED {len(v)} chars>"


def maybe_redact(payload: str, key_patterns: list) -> str:
    """Redact des champs sensibles dans un JSON string."""
    try:
        obj = json.loads(payload)
    except Exception:
        return payload[:500]

    def walk(o):
        if isinstance(o, dict):
            return {
                k: redact_value(str(v)) if any(p in k.lower() for p in key_patterns) and isinstance(v, str) and len(v) > 50
                else walk(v)
                for k, v in o.items()
            }
        if isinstance(o, list):
            return [walk(x) for x in o]
        return o

    return json.dumps(walk(obj), indent=2)[:5000]


def cookies_summary(cookies: list) -> str:
    """Liste les noms de cookies (pas les valeurs)."""
    names = [c["name"] for c in cookies]
    return ", ".join(sorted(set(names)))


def main(har_path: str):
    data = json.loads(Path(har_path).read_text(encoding="utf-8"))
    entries = data["log"]["entries"]

    for target in TARGETS:
        matches = [e for e in entries if target in e["request"]["url"]]
        if not matches:
            print(f"\n=== {target} : NOT FOUND ===\n")
            continue

        # Prend la dernière (cas où plusieurs init successifs)
        for idx, e in enumerate(matches):
            req = e["request"]
            res = e["response"]

            print(f"\n{'='*80}")
            print(f"=== [{target}] match #{idx + 1}/{len(matches)}")
            print(f"=== {req['method']} {req['url']}")
            print(f"=== Status: {res['status']} {res.get('statusText','')}")
            print('='*80)

            # Headers (filtré)
            print("\n--- REQUEST HEADERS ---")
            for h in req["headers"]:
                name = h["name"]
                value = h["value"]
                ln = name.lower()
                if ln in REDACT_HEADERS:
                    print(f"  {name}: <REDACTED>")
                elif ln.startswith(":") or ln in ("content-length", "te", "dnt", "pragma", "cache-control", "priority"):
                    continue
                else:
                    print(f"  {name}: {value[:200]}")

            # Cookies summary
            print("\n--- REQUEST COOKIES (names only) ---")
            print(f"  {cookies_summary(req.get('cookies', []))}")

            # Body (redact sensibles)
            post = req.get("postData", {})
            if post:
                text = post.get("text", "")
                print(f"\n--- REQUEST BODY ({post.get('mimeType', '')}, {len(text)} chars) ---")
                if "json" in post.get("mimeType", "").lower():
                    print(maybe_redact(text, ["token", "captcha", "signature", "challenge", "xal", "ewa", "kid", "session"]))
                else:
                    print(text[:2000])

            # Response body
            resp_text = res.get("content", {}).get("text", "")
            print(f"\n--- RESPONSE BODY ({len(resp_text)} chars) ---")
            if resp_text:
                if len(resp_text) < 2000:
                    print(resp_text)
                else:
                    print(maybe_redact(resp_text, ["token", "captcha", "signature", "session", "id"]))

            # Stop apres 1 occurrence pour pas spam
            break


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "store.epicgames.com.har")
