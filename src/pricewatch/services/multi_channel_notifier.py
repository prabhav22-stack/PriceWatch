"""Multi-channel notification dispatcher using Apprise.

Enables PriceWatch to dispatch alerts simultaneously to Telegram, Discord webhooks,
NTFY topics, Slack, Pushover, custom Webhooks, and Email.
"""

import os
from typing import List, Optional
import apprise

from pricewatch.logging_setup import get_logger

logger = get_logger("multi_channel_notifier")


class MultiChannelNotifier:
    """Dispatches alerts across 90+ notification services via Apprise."""

    def __init__(self, default_channels: Optional[List[str]] = None):
        self.default_channels: List[str] = list(default_channels or [])
        env_channels = os.getenv("APPRISE_URLS")
        if env_channels:
            for ch in env_channels.split(","):
                ch = ch.strip()
                if ch and ch not in self.default_channels:
                    self.default_channels.append(ch)

    async def notify(
        self,
        title: str,
        body: str,
        channels: Optional[List[str]] = None,
        url: Optional[str] = None,
    ) -> bool:
        """
        Send notification to all specified or default channels.
        Returns True if at least one service received the alert or no channels were configured.
        """
        target_channels = list(channels or self.default_channels)
        if not target_channels:
            return True

        ap = apprise.Apprise()
        for ch in target_channels:
            try:
                ap.add(ch)
            except Exception as exc:
                logger.warning("Failed to register Apprise channel", channel=ch, error=str(exc))

        if not ap:
            return False

        try:
            # Strip HTML tags if plain text service or keep HTML formatting
            ok = await ap.async_notify(
                title=title,
                body=body,
                body_format=apprise.NotifyFormat.HTML,
            )
            logger.info("Dispatched multi-channel alert via Apprise", title=title, success=ok, channels=len(target_channels))
            return ok
        except Exception as exc:
            logger.warning("Error during Apprise multi-channel dispatch", error=str(exc))
            return False


# Shared singleton instance
notifier = MultiChannelNotifier()
