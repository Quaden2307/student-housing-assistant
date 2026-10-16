"""Post run reports to Discord (HANDOFF section 6: a silently dead scraper is how projects die)."""

from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger(__name__)


def discord(message: str, webhook_url: str | None = None) -> bool:
    """Post ``message`` to the Discord webhook; return True if it was sent.

    The URL comes from ``DISCORD_WEBHOOK_URL`` (set it in ``.env``). With no URL the message
    is logged and False is returned, so the pipeline works before the webhook exists.
    """
    url = webhook_url or os.environ.get("DISCORD_WEBHOOK_URL")
    if not url:
        log.info("DISCORD_WEBHOOK_URL not set; report not sent")
        return False
    try:
        response = requests.post(url, json={"content": message[:1900]}, timeout=10)
        response.raise_for_status()
    except requests.RequestException as exc:
        log.error("Discord post failed: %s", exc)
        return False
    return True
