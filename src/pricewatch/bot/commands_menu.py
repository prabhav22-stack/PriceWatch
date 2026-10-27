"""Telegram Bot Command menu definitions and configuration.

Matches the native Telegram bot menu button shown in the user's interface.
"""

from typing import List
from telegram import Bot, BotCommand, MenuButtonCommands

from pricewatch.logging_setup import get_logger

logger = get_logger("commands_menu")

DEFAULT_BOT_COMMANDS: List[BotCommand] = [
    BotCommand("start", "Start the bot"),
    BotCommand("setpincode", "Set your pincode"),
    BotCommand("pincode", "Get your current pincode"),
    BotCommand("products", "Browse Amul products"),
    BotCommand("autoorder", "Toggle auto-ordering of products"),
    BotCommand("trackall", "Toggle restock alerts for all protein items"),
    BotCommand("repeat", "Set repeat notification limit (1-10 or 0 for until OOS)"),
    BotCommand("settings", "View or change your settings"),
    BotCommand("tracked", "List all tracked products"),
    BotCommand("favourites", "List your favourite products"),
    BotCommand("support", "Get support"),
    BotCommand("map", "View interactive map"),
    BotCommand("search", "Search Amul products"),
    BotCommand("analytics", "Warehouse restock & inventory metrics"),
    BotCommand("count", "Product stock quantity tables"),
    BotCommand("history", "View price trend chart"),
]


async def configure_bot_menu_button(bot: Bot) -> None:
    """Set the native bot commands and attach the chat menu button."""
    try:
        await bot.set_my_commands(DEFAULT_BOT_COMMANDS)
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        logger.info("Successfully configured Telegram bot menu commands and button")
    except Exception as exc:
        logger.warning("Failed to configure Telegram bot commands menu", error=str(exc))
