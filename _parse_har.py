"""
_parse_har.py — Extrait les POST intéressants du HAR pour identifier
l'endpoint de finalisation du claim.

Redact tout ce qui peut leak (Cookie, Authorization, CSRF tokens) avant affichage.
"""

import json
import re
import sys
from pathlib import Path

INTERESTING_HOSTS = (
    "epicgames.com",
    "epicgames-com",
    "epicgames.dev",
    "ol.epicgames.com",
    "payment-website",
)

# Headers à redact (ne jamais print en clair)
REDACT_HEADERS = {
    "cookie", "authorization", "x-csrf-token", "x-epic-csrf",
    "x-fp", "x-epic-session-id", "x-xsrf-token", "set-cookie",
}


def redact_headers(headers: list) -> dict:
    out = {}
    for h in headers:
        name = h["name"].lower()
        if name in REDACT_HEADERS:
            v = h["value"]
            out[h["name"]] = f"<REDACTED {len(v)} chars, starts: {v[:6]}...>"
        else:
            out[h["name"]] = h["value"]
    return out


def main(har_path: str):
    print(f"Loading {har_path}...")
    data = json.loads(Path(har_path).read_text(encoding="utf-8"))
    entries = data["log"]["entries"]
    print(f"Total entries: {len(entries)}")

    # Filtre 1 : POST/PUT/DELETE uniquement (claim est un POST)
    mutations = [e for e in entries if e["request"]["method"] in ("POST", "PUT", "DELETE", "PATCH")]
    print(f"Mutations (POST/PUT/etc): {len(mutations)}")

    # Filtre 2 : domaines Epic uniquement
    interesting = [
        e for e in mutations
        if any(h in e["request"]["url"].lower() for h in INTERESTING_HOSTS)
    ]
    print(f"Epic-domain mutations: {len(interesting)}\n")

    # Affiche chaque candidate
    for i, e in enumerate(interesting):
        req = e["request"]
        res = e["response"]
        url = req["url"]
        # Skip les calls de telemetry/analytics qui polluent
        if any(noise in url.lower() for noise in ("/telemetry", "/analytics", "/event", "/log", "tracking", "datadog", "tealium")):
            continue
        print(f"=== [{i}] {req['method']} {url}")
        print(f"    Status: {res['status']} {res.get('statusText', '')}")
        print(f"    Started: {e['startedDateTime']}")
        # Headers (redacted)
        headers = redact_headers(req["headers"])
        # Affiche seulement les headers non-standards intéressants
        for name, value in headers.items():
            ln = name.lower()
            if ln in ("user-agent", "accept", "accept-language", "accept-encoding",
                     "connection", "host", "origin", "referer", "sec-ch-ua",
                     "sec-ch-ua-mobile", "sec-ch-ua-platform", "sec-fetch-site",
                     "sec-fetch-mode", "sec-fetch-dest", "te", "dnt", "upgrade-insecure-requests",
                     "content-length", "pragma", "cache-control"):
                continue
            print(f"    {name}: {value}")
        # Payload (text)
        post_data = req.get("postData", {})
        if post_data:
            text = post_data.get("text", "")
            mime = post_data.get("mimeType", "")
            print(f"    --- BODY ({mime}, {len(text)} chars) ---")
            # Si JSON, pretty-print les keys top-level
            if "json" in mime.lower() and text:
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        print(f"    JSON keys: {list(parsed.keys())}")
                        # Si operationName présent (GraphQL), affiche-le
                        if "operationName" in parsed:
                            print(f"    GraphQL op: {parsed['operationName']}")
                        if "variables" in parsed:
                            print(f"    Variables: {json.dumps(parsed['variables'])[:500]}")
                except json.JSONDecodeError:
                    print(f"    (JSON decode failed)")
                    print(f"    {text[:300]}")
            else:
                print(f"    {text[:300]}")
        # Response body summary (look for offerId, transaction, success markers)
        resp_content = res.get("content", {}).get("text", "")
        if resp_content and len(resp_content) < 4000:
            markers = []
            for kw in ("SUCCESS", "FAILED", "CHECKOUT", "REACHED_PURCHASE_LIMIT",
                      "transactionId", "orderId", "quickPurchaseStatus", "errorCode",
                      "eligible", "captcha", "challenge"):
                if kw.lower() in resp_content.lower():
                    markers.append(kw)
            if markers:
                print(f"    RESP markers: {markers}")
                if len(resp_content) < 800:
                    print(f"    RESP: {resp_content}")
        print()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "store.epicgames.com.har")
