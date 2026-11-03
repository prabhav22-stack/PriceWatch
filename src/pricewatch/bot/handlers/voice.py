"""Telegram voice message handler powered by Groq Whisper (whisper-large-v3-turbo).

Enables users to send hands-free voice notes querying supplement recommendations,
price comparisons, and deal intelligence.
"""

from typing import Optional
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ContextTypes

from pricewatch.logging_setup import get_logger
from pricewatch.services.advisor_service import advisor_service
from pricewatch.services.llm_router import llm_router

logger = get_logger("bot.handlers.voice")


async def voice_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming Telegram voice notes and audio clips using Groq Whisper."""
    message = update.message
    if not message:
        return

    voice = message.voice or message.audio
    if not voice:
        return

    chat_id = update.effective_chat.id if update.effective_chat else message.chat_id
    user_id = update.effective_user.id if update.effective_user else 0

    # 1. Send typing / record_voice action indicator
    try:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    except Exception:
        pass

    # 2. Download voice audio bytes from Telegram
    try:
        voice_file = await context.bot.get_file(voice.file_id)
        audio_bytearray = await voice_file.download_as_bytearray()
        audio_bytes = bytes(audio_bytearray)
    except Exception as exc:
        logger.error("Failed to download voice note from Telegram", error=str(exc))
        await message.reply_text(
            "⚠️ Could not download your voice note. Please try again or type your query.",
            parse_mode=ParseMode.HTML,
        )
        return

    # 3. Transcribe via Groq Whisper
    try:
        filename = "voice.ogg" if message.voice else "audio.mp3"
        transcription = await llm_router.transcribe_audio(audio_bytes=audio_bytes, filename=filename)
    except Exception as exc:
        logger.error("Error during Whisper voice transcription", error=str(exc))
        transcription = None

    if not transcription or not transcription.strip():
        await message.reply_text(
            "🎙️ <i>I couldn't hear or transcribe that voice note clearly.</i>\n\n"
            "Try holding the mic closer or type your question directly:\n"
            "• <i>\"Top 5 isolate whey under 2500\"</i>\n"
            "• <i>\"Compare Nakpro Gold and MuscleBlaze on Amazon\"</i>",
            parse_mode=ParseMode.HTML,
        )
        return

    logger.info("Transcribed voice query", user_id=user_id, text=transcription)

    # 4. Route transcribed text to conversational natural shopping advisor
    discovery_service = context.bot_data.get("discovery_service")
    reply_text, keyboard = await advisor_service.handle_natural_chat(
        user_id=user_id,
        raw_text=transcription,
        discovery_service=discovery_service,
    )

    # Format with voice recognition acknowledgment header
    voiced_reply = f"🎙️ <i>\"{transcription.strip()}\"</i>\n\n{reply_text}"

    await message.reply_text(
        text=voiced_reply,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )
