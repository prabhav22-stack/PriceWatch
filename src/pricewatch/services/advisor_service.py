"""Conversational Shopping Advisor and Intelligent Recommendation Engine.

Answers natural chat requests like:
- "give me top 5 shilajit under Rs 1000 (factor reviews in too)"
- "Best whey protein concentrate under Rs 2000 (ranked list)"
- "suggest best creatine under 800"
- Or conversational product queries like "Nakpro Perform 1kg unflavoured"
"""

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from pricewatch.config import settings
from pricewatch.domain.models import StoreDeal
from pricewatch.logging_setup import get_logger
from pricewatch.services.discovery_matcher import extract_core_categories
from pricewatch.services.llm_router import llm_router
from pricewatch.services.store_searchers import (
    search_amazon,
    search_flipkart,
    search_healthkart,
    search_hyugalife,
    search_nutrabay,
    search_shopify_store,
)
from pricewatch.validation.normalizer import format_paise_to_inr

logger = get_logger("advisor_service")

TRUSTED_VERIFIED_BRANDS = {
    "nakpro", "asitis", "as-it-is", "atom", "muscleblaze", "amul",
    "optimum nutrition", "on", "nutrabay", "kapiva", "upakarma", "dabur",
    "carbamide forte", "himalaya", "myprotein", "fast&up", "wellcore"
}


def is_trusted_brand(title: str) -> bool:
    """Checks whether the product title matches a trusted, lab-verified supplement brand."""
    t = title.lower()
    for b in TRUSTED_VERIFIED_BRANDS:
        if len(b) <= 3:
            if re.search(r"\b" + re.escape(b) + r"\b", t):
                return True
        else:
            if b in t:
                return True
    return False


@dataclass
class ChatIntent:
    intent_type: str  # "recommendation", "comparison", "general_chat"
    category: Optional[str] = None
    sub_type: Optional[str] = None
    max_budget_inr: Optional[int] = None
    limit: int = 5
    search_query: str = ""
    chat_reply: Optional[str] = None


class ConversationalAdvisorService:
    """Answers natural language supplement questions, curates recommendations, and routes queries."""

    async def parse_chat_intent(self, user_text: str) -> ChatIntent:
        """Use LLM (Groq / Gemini) to extract user intent, category, budget, and search parameters."""
        prompt = (
            "You are an AI natural language router for an Indian fitness supplement bot.\n"
            "Analyze this user message and extract intent into JSON:\n"
            "{\n"
            "  \"intent_type\": \"recommendation\" | \"comparison\" | \"general_chat\",\n"
            "  \"category\": string or null (e.g. 'shilajit', 'whey', 'creatine', 'peanut_butter', 'fish_oil'),\n"
            "  \"sub_type\": string or null (e.g. 'concentrate', 'isolate', 'resin', 'micronized', 'unflavoured'),\n"
            "  \"max_budget_inr\": integer or null (e.g. 1000, 2000, 800),\n"
            "  \"limit\": integer (default 5),\n"
            "  \"search_query\": string to search stores (e.g. 'shilajit', 'whey protein concentrate'),\n"
            "  \"chat_reply\": string or null (only if intent_type is general_chat)\n"
            "}\n"
            "Guidelines:\n"
            "- If user asks for top/best/recommendation/under X budget -> 'recommendation'\n"
            "- If user specifies an exact single product (e.g. 'nakpro perform 1kg unflavoured', 'amul whey') -> 'comparison'\n"
            "- If user asks a general question or greeting -> 'general_chat'\n"
            f"User message: \"{user_text}\"\n"
            "Output ONLY valid JSON."
        )

        # 1. Try Groq
        if llm_router.has_groq:
            try:
                import httpx
                url = "https://api.groq.com/openai/v1/chat/completions"
                headers = {"Authorization": f"Bearer {llm_router.groq_api_key}", "Content-Type": "application/json"}
                payload = {
                    "model": "qwen/qwen3.8-27b",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"}
                }
                async with httpx.AsyncClient(timeout=4.0) as client:
                    resp = await client.post(url, headers=headers, json=payload)
                    if resp.status_code == 200:
                        data = json.loads(resp.json()["choices"][0]["message"]["content"])
                        return ChatIntent(
                            intent_type=data.get("intent_type") or "comparison",
                            category=data.get("category"),
                            sub_type=data.get("sub_type"),
                            max_budget_inr=int(data["max_budget_inr"]) if data.get("max_budget_inr") else None,
                            limit=int(data.get("limit") or 5),
                            search_query=data.get("search_query") or user_text,
                            chat_reply=data.get("chat_reply"),
                        )
            except Exception as exc:
                logger.debug("Groq intent parse exception", error=str(exc))

        # 2. Try Gemini
        if llm_router.has_gemini:
            try:
                from pricewatch.services.gemini_service import gemini_service
                res = await gemini_service._call_gemini(prompt)
                if res:
                    cleaned = res.replace("```json", "").replace("```", "").strip()
                    data = json.loads(cleaned)
                    return ChatIntent(
                        intent_type=data.get("intent_type") or "comparison",
                        category=data.get("category"),
                        sub_type=data.get("sub_type"),
                        max_budget_inr=int(data["max_budget_inr"]) if data.get("max_budget_inr") else None,
                        limit=int(data.get("limit") or 5),
                        search_query=data.get("search_query") or user_text,
                        chat_reply=data.get("chat_reply"),
                    )
            except Exception as exc:
                logger.debug("Gemini intent parse exception", error=str(exc))

        # Fallback: heuristics
        low = user_text.lower().strip()
        words = set(re.findall(r"\b\w+\b", low))
        greetings = {"hi", "hello", "hey", "help", "menu", "start", "assistant", "info"}
        if words.intersection(greetings) or low in ("hello there", "hi there", "hey there"):
            return ChatIntent(
                intent_type="general_chat",
                chat_reply="Hello! I'm your PriceWatch assistant. You can ask me for product recommendations (e.g. 'top 5 shilajit under 1000'), compare prices across stores (e.g. 'Nakpro Perform 1kg'), or paste any product link to start tracking!",
            )

        budget_m = re.search(r"(?:under|below|less than|max|budget)\s*(?:rs\.?|inr|₹)?\s*(\d+)", low)
        max_budget = int(budget_m.group(1)) if budget_m else None
        is_rec = any(w in low for w in ("top", "best", "recommend", "suggest", "under", "good"))

        return ChatIntent(
            intent_type="recommendation" if is_rec else "comparison",
            category=next((c for c in ("shilajit", "whey", "creatine", "peanut", "fish oil") if c in low), None),
            max_budget_inr=max_budget,
            limit=5,
            search_query=user_text,
        )

    async def generate_recommendations(
        self,
        category: str,
        sub_type: Optional[str] = None,
        max_budget_inr: Optional[int] = None,
        limit: int = 5,
        original_query: str = "",
    ) -> Tuple[str, InlineKeyboardMarkup]:
        """Fetch real store deals, apply budget & trust scoring, and generate ranked recommendations."""
        search_term = f"{category} {sub_type or ''}".strip()
        logger.info("Generating curated recommendations", term=search_term, budget=max_budget_inr)

        # 1. Query stores in parallel
        tasks = [
            search_flipkart(search_term),
            search_amazon(search_term),
            search_hyugalife(search_term),
            search_healthkart(search_term),
            search_nutrabay(search_term),
            search_shopify_store("nakpro.com", "Nakpro Direct", search_term),
            search_shopify_store("asitisnutrition.com", "AS-IT-IS Direct", search_term),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_deals: List[StoreDeal] = []
        for r in results:
            if isinstance(r, list):
                all_deals.extend(r)

        # 2. Strict Filter: Budget cap & Category relevance
        max_paise = (max_budget_inr * 100) if max_budget_inr else 999999999
        filtered: List[StoreDeal] = []
        seen_keys = set()

        for d in all_deals:
            if d.price_paise <= 0 or d.price_paise > max_paise:
                continue

            low_title = d.product_title.lower()
            # Category relevance
            cats = extract_core_categories(low_title)
            cat_words = [w for w in re.sub(r"[^\w\s]", " ", category.lower()).split() if w not in ("protein", "powder", "best", "top", "supplement", "supplements")]
            if not cat_words:
                cat_words = [category.lower()]
            match_cat = any(w in cats or w in low_title for w in cat_words)
            if not match_cat:
                continue

            # Sub-type match (e.g. concentrate vs isolate vs unflavoured)
            if sub_type:
                st = sub_type.lower()
                if st == "concentrate" and "isolate" in low_title and "concentrate" not in low_title:
                    continue
                if st == "isolate" and "isolate" not in low_title:
                    continue
                if st in ("unflavoured", "unflavored", "raw"):
                    if any(flv in low_title for flv in ("chocolate", "vanilla", "mango", "kulfi", "coffee", "strawberry", "banana", "berry")):
                        continue

            # Deduplicate similar titles
            short_key = re.sub(r"[^\w]", "", low_title)[:22]
            if short_key in seen_keys:
                continue
            seen_keys.add(short_key)
            filtered.append(d)

        if not filtered:
            # Fallback if strict budget filtered everything
            budget_str = f" under ₹{max_budget_inr}" if max_budget_inr else ""
            msg = (
                f"🔍 <b>No verified deals found for {category.title()}{budget_str}</b>\n\n"
                f"Try increasing your budget or search for individual brands:\n"
                f"• <code>/compare Nakpro Perform</code>\n"
                f"• <code>/compare Amul Whey Protein</code>\n"
                f"• <code>/compare Nutrabay Shilajit</code>"
            )
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="nav:home")]])
            return msg, kb

        # 3. Trust & Value Ranking
        # Priority: Trusted/LabDoor/Trustified brands first, then lowest price
        ranked = sorted(
            filtered,
            key=lambda d: (
                0 if is_trusted_brand(d.product_title) else 1,
                d.price_paise,
            )
        )
        top_deals = ranked[:limit]

        # 4. Format Ranked Response
        budget_header = f" Under ₹{max_budget_inr:,.0f}" if max_budget_inr else ""
        sub_header = f" ({sub_type.title()})" if sub_type else ""
        lines = [
            f"🏆 <b>Top {len(top_deals)} {category.title()}{sub_header} Recommendations{budget_header}</b>",
            "<i>Ranked by verified seller trust, lab testing & buyer value:</i>\n",
        ]

        buttons: List[List[InlineKeyboardButton]] = []
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣"]

        for i, deal in enumerate(top_deals):
            medal = medals[i] if i < len(medals) else f"{i+1}."
            price_str = format_paise_to_inr(deal.price_paise)
            mrp_str = f" <s>{format_paise_to_inr(deal.mrp_paise)}</s>" if deal.mrp_paise and deal.mrp_paise > deal.price_paise else ""

            # Check for trust badge
            trust_badge = "🛡️ <b>Lab-Verified Brand</b>" if is_trusted_brand(deal.product_title) else "⭐ Verified Seller"

            lines.append(f"{medal} <b>{deal.product_title}</b>")
            lines.append(f"   💰 <code>{price_str}</code>{mrp_str} on <b>{deal.store_name}</b> (🟢 In Stock)")
            lines.append(f"   {trust_badge}")
            if deal.variant_title:
                lines.append(f"   🏷️ <i>{deal.variant_title}</i>")
            lines.append("")

            # Action button
            trunc_name = (deal.product_title[:20] + "..") if len(deal.product_title) > 20 else deal.product_title
            btn_text = f"🛒 {i+1}. Buy on {deal.store_name} ({price_str})"
            if deal.url:
                buttons.append([InlineKeyboardButton(btn_text, url=deal.url)])

        lines.append("<i>💡 Tap any button below to open the deal directly in store.</i>")
        buttons.append([
            InlineKeyboardButton("📋 Tracked Items", callback_data="nav:tracked"),
            InlineKeyboardButton("🏠 Main Menu", callback_data="nav:home"),
        ])

        return "\n".join(lines), InlineKeyboardMarkup(buttons)


advisor_service = ConversationalAdvisorService()
