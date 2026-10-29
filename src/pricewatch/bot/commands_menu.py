"""Telegram Bot Command menu definitions and configuration.

Matches the native Telegram bot menu button shown in the user's interface.
"""

from typing import List
from telegram import Bot, BotCommand, MenuButtonCommands

from pricewatch.logging_setup import get_logger

logger = get_logger("commands_menu")

DEFAULT_BOT_COMMANDS: List[BotCommand] = [
    BotCommand("start", "Home dashboard & main menu"),
    BotCommand("track", "Track a product link & target price"),
    BotCommand("tracked", "List all your tracked products"),
    BotCommand("check", "Instant live price & stock check"),
    BotCommand("untrack", "Stop tracking a product"),
    BotCommand("history", "View price trend chart"),
    BotCommand("settings", "Notification settings & preferences"),
    BotCommand("pincode", "View or set delivery pincode"),
    BotCommand("setpincode", "Set a new delivery pincode"),
    BotCommand("products", "Browse Amul products & stock"),
    BotCommand("trackall", "Toggle restock alerts for all protein items"),
    BotCommand("search", "Search Amul products by keyword"),
    BotCommand("favourites", "List your starred favourite products"),
    BotCommand("count", "Real-time warehouse stock counts"),
    BotCommand("analytics", "Warehouse restock & inventory metrics"),
    BotCommand("repeat", "Set repeat notification limit"),
    BotCommand("status", "System health & check frequencies"),
    BotCommand("map", "Amul warehouse delivery hubs"),
    BotCommand("help", "Help guide & command reference"),
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
