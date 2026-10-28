"""Telegram Bot Command menu definitions and configuration.

Matches the native Telegram bot menu button shown in the user's interface.
"""

from typing import List
from telegram import Bot, BotCommand, MenuButtonCommands

from pricewatch.logging_setup import get_logger

logger = get_logger("commands_menu")

DEFAULT_BOT_COMMANDS: List[BotCommand] = [
    BotCommand("start", "Start the bot & main menu"),
    BotCommand("help", "Help guide & command reference"),
    BotCommand("products", "Browse Amul products & stock"),
    BotCommand("tracked", "List all your tracked products"),
    BotCommand("trackall", "Toggle restock alerts for all protein items"),
    BotCommand("repeat", "Set repeat notification limit (1-10 or 0 for until OOS)"),
    BotCommand("settings", "Notification settings & preferences"),
    BotCommand("pincode", "Get current delivery pincode"),
    BotCommand("setpincode", "Set a new delivery pincode"),
    BotCommand("favourites", "List your starred favourite products"),
    BotCommand("search", "Search Amul products by keyword"),
    BotCommand("untrack", "Stop tracking a product"),
    BotCommand("track", "Track a product link & target price"),
    BotCommand("count", "Real-time stock quantity tables"),
    BotCommand("analytics", "Warehouse restock & inventory metrics"),
    BotCommand("history", "View price trend chart"),
    BotCommand("map", "Amul warehouse delivery hubs"),
    BotCommand("status", "System health & uptime status"),
    BotCommand("support", "Support & GitHub community"),
]


async def configure_bot_menu_button(bot: Bot) -> None:
    """Set the native bot commands and attach the chat menu button."""
    try:
        await bot.set_my_commands(DEFAULT_BOT_COMMANDS)
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        logger.info("Successfully configured Telegram bot menu commands and button")
    except Exception as exc:
        logger.warning("Failed to configure Telegram bot commands menu", error=str(exc))
