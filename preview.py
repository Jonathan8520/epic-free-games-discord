"""
preview.py — Envoie sur Discord les notifs des jeux gratuits actuels
SANS toucher au state.json. Pratique pour tester le rendu visuel.

Usage local :
    set DISCORD_WEBHOOK=https://discord.com/api/webhooks/...
    python preview.py
"""

from epic import get_free_games, get_surprise_free_games
from notifier import notify_new_game, notify_upcoming_game, notify_surprise_game
from logger import log


def main():
    log.info("=" * 50)
    log.info("PREVIEW — envoi des notifs sans toucher au state")

    games = get_free_games()
    current  = [g for g in games if g["status"] == "current"]
    upcoming = [g for g in games if g["status"] == "next"]

    log.info(f"{len(current)} actuel(s), {len(upcoming)} à venir.")

    for game in current:
        notify_new_game(game)

    for game in upcoming:
        notify_upcoming_game(game)

    surprise = get_surprise_free_games(exclude_ids={g["id"] for g in games})
    for game in surprise:
        notify_surprise_game(game)

    log.info("Preview terminée.")


if __name__ == "__main__":
    main()
