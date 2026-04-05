"""
logger.py — Logger structuré qui masque automatiquement les tokens et cookies
pour éviter toute fuite dans les logs GitHub Actions (publics sur repo public).
"""

import os
import re
import logging
from datetime import datetime, timezone

_SECRETS_TO_MASK = [
    os.getenv("EPIC_BEARER_TOKEN", ""),
    os.getenv("EPIC_SESSION_AP", ""),
    os.getenv("DISCORD_WEBHOOK", ""),
    os.getenv("ALERT_WEBHOOK", ""),
]

def _mask(msg: str) -> str:
    for secret in _SECRETS_TO_MASK:
        if secret and len(secret) > 8:
            msg = msg.replace(secret, "***")
            msg = msg.replace(secret[:12], "***")
    msg = re.sub(r'Bearer\s+[A-Za-z0-9\-._~+/]+=*', 'Bearer ***', msg)
    msg = re.sub(r'(token|key|secret|password|cookie)\s*[:=]\s*\S+',
                 r'\1: ***', msg, flags=re.IGNORECASE)
    return msg


class SafeFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record.msg = _mask(str(record.msg))
        return super().format(record)


def get_logger(name: str = "epic_bot") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler()
    handler.setFormatter(SafeFormatter(
        fmt="[%(asctime)s] %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S"
    ))
    logger.addHandler(handler)
    return logger

log = get_logger()
