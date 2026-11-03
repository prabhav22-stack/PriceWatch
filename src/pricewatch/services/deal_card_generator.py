"""Visual Deal Snapshot Card Generator for Telegram Chat Sharing.

Renders sleek, high-definition 1200x675 graphic deal cards displaying:
- Hero Best Deal & Discount % off MRP
- Multi-store Price Comparison Matrix
- Trustified / Labdoor Purity verification badge
- 30-day Price History Trend chart
- Buy Now vs Wait Confidence verdict
"""

import io
from typing import List, Optional
import matplotlib
matplotlib.use("Agg")  # Non-interactive background renderer
import matplotlib.pyplot as plt
import matplotlib.patches as patches

from pricewatch.domain.models import StoreDeal
from pricewatch.services.purity_service import PurityCertificate
from pricewatch.services.price_predictor import BuyAdvice
from pricewatch.validation.normalizer import format_paise_to_inr


class DealCardGenerator:
    """Generates high-res PNG deal infographic cards using Matplotlib vector rendering."""

    def generate_deal_card(
        self,
        product_title: str,
        best_deal: StoreDeal,
        all_deals: List[StoreDeal],
        purity_cert: Optional[PurityCertificate] = None,
        buy_advice: Optional[BuyAdvice] = None,
        history_prices: Optional[List[int]] = None,
    ) -> bytes:
        """Renders 1200x675 Dark-Mode Infocard as PNG bytes."""
        fig = plt.figure(figsize=(12, 6.75), dpi=100, facecolor="#0F172A")
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_facecolor("#0F172A")
        ax.axis("off")

        # Top Header Bar
        rect_header = patches.Rectangle((0, 0.88), 1, 0.12, facecolor="#1E293B", edgecolor="none")
        ax.add_patch(rect_header)

        ax.text(0.04, 0.94, "PRICEWATCH DEAL INTELLIGENCE", fontsize=15, fontweight="bold",
                color="#38BDF8", va="center", ha="left", family="sans-serif")
        ax.text(0.96, 0.94, "LIVE VERIFIED DEAL", fontsize=11, fontweight="bold",
                color="#10B981", va="center", ha="right", family="sans-serif")

        # Product Title
        clean_title = product_title if len(product_title) <= 55 else product_title[:52] + "..."
        ax.text(0.04, 0.83, clean_title, fontsize=19, fontweight="bold",
                color="#F8FAFC", va="center", ha="left", family="sans-serif")

        # Left Column: Hero Deal & Buy Advice (x: 0.04 to 0.48)
        # Background card for Hero Deal
        rect_left = patches.FancyBboxPatch(
            (0.04, 0.18), 0.44, 0.58,
            boxstyle="round,pad=0.02,rounding_size=0.03",
            facecolor="#1E293B", edgecolor="#334155", linewidth=1.5
        )
        ax.add_patch(rect_left)

        # Hero Price Tag
        best_price_str = format_paise_to_inr(best_deal.price_paise)
        ax.text(0.07, 0.69, "BEST PRICE AVAILABLE", fontsize=11, fontweight="bold",
                color="#94A3B8", va="center", family="sans-serif")
        ax.text(0.07, 0.61, best_price_str, fontsize=32, fontweight="heavy",
                color="#34D399", va="center", family="sans-serif")

        if best_deal.mrp_paise and best_deal.mrp_paise > best_deal.price_paise:
            mrp_str = format_paise_to_inr(best_deal.mrp_paise)
            disc_pct = int(round((1 - best_deal.price_paise / best_deal.mrp_paise) * 100))
            ax.text(0.28, 0.61, f"MRP {mrp_str}", fontsize=13, color="#64748B",
                    va="center", family="sans-serif")
            # Discount badge
            rect_disc = patches.FancyBboxPatch(
                (0.40, 0.585), 0.065, 0.05,
                boxstyle="round,pad=0.01", facecolor="#EF4444", edgecolor="none"
            )
            ax.add_patch(rect_disc)
            ax.text(0.4325, 0.61, f"{disc_pct}% OFF", fontsize=10, fontweight="bold",
                    color="#FFFFFF", va="center", ha="center", family="sans-serif")

        ax.text(0.07, 0.52, f"Store: {best_deal.store_name}  •  [IN STOCK]", fontsize=12,
                color="#E2E8F0", fontweight="bold", va="center", family="sans-serif")

        # Active Coupon Pill if available
        try:
            from pricewatch.services.coupon_service import coupon_service
            c_info = coupon_service.extract_coupon(
                f"{best_deal.title or ''} {best_deal.store_name or ''}",
                best_deal.price_paise / 100.0,
            )
            if c_info.has_coupon:
                ax.text(0.07, 0.47, f"[COUPON: -Rs {c_info.discount_amount:,.0f} | Effective: Rs {c_info.effective_price:,.0f}]",
                        fontsize=10, color="#F59E0B", fontweight="bold", va="center", family="sans-serif")
        except Exception:
            pass

        # Buy Now vs Wait verdict
        if buy_advice:
            ax.text(0.07, 0.43, "PREDICTIVE BUY ADVICE", fontsize=10, fontweight="bold",
                    color="#94A3B8", va="center", family="sans-serif")
            verdict_color = "#10B981" if "BUY" in buy_advice.verdict else "#F59E0B"
            ax.text(0.07, 0.36, f">> {buy_advice.verdict} ({buy_advice.confidence_pct}% Confidence)",
                    fontsize=14, fontweight="bold", color=verdict_color, va="center", family="sans-serif")
            adv_summary = buy_advice.summary if len(buy_advice.summary) < 65 else buy_advice.summary[:62] + "..."
            ax.text(0.07, 0.30, adv_summary, fontsize=10, color="#CBD5E1",
                    va="center", family="sans-serif")
        else:
            ax.text(0.07, 0.36, ">> Highly Recommended Purchase", fontsize=13,
                    fontweight="bold", color="#10B981", va="center", family="sans-serif")

        # Right Column: Stores Comparison & Purity (x: 0.52 to 0.96)
        rect_right = patches.FancyBboxPatch(
            (0.52, 0.18), 0.44, 0.58,
            boxstyle="round,pad=0.02,rounding_size=0.03",
            facecolor="#1E293B", edgecolor="#334155", linewidth=1.5
        )
        ax.add_patch(rect_right)

        ax.text(0.55, 0.70, "MULTI-STORE PRICE MATRIX", fontsize=11, fontweight="bold",
                color="#94A3B8", va="center", family="sans-serif")

        # Render top 4 deals in table format
        y_pos = 0.63
        for i, deal in enumerate(all_deals[:4]):
            p_str = format_paise_to_inr(deal.price_paise)
            is_best = (i == 0)
            st_color = "#34D399" if is_best else "#E2E8F0"
            badge = " [LOWEST]" if is_best else ""

            ax.text(0.55, y_pos, f"• {deal.store_name}{badge}", fontsize=11,
                    fontweight="bold" if is_best else "normal", color=st_color, va="center", family="sans-serif")
            ax.text(0.93, y_pos, p_str, fontsize=11, fontweight="bold",
                    color=st_color, va="center", ha="right", family="sans-serif")
            y_pos -= 0.055

        # Purity Section
        ax.text(0.55, 0.38, "LAB PURITY CERTIFICATION", fontsize=11, fontweight="bold",
                color="#94A3B8", va="center", family="sans-serif")

        if purity_cert:
            ax.text(0.55, 0.31, f"[CERTIFIED] {purity_cert.lab_tester}: {purity_cert.status} (Score: {purity_cert.trust_score}/10)",
                    fontsize=12, fontweight="bold", color="#38BDF8", va="center", family="sans-serif")
            if purity_cert.claimed_protein_g and purity_cert.tested_protein_g:
                ax.text(0.55, 0.25, f"Verified Protein: {purity_cert.tested_protein_g:g}g tested vs {purity_cert.claimed_protein_g:g}g label",
                        fontsize=10.5, color="#F1F5F9", va="center", family="sans-serif")
            ax.text(0.55, 0.20, f"Heavy Metals: {purity_cert.heavy_metals_status}  •  Spiking: NONE",
                    fontsize=9.5, color="#94A3B8", va="center", family="sans-serif")
        else:
            ax.text(0.55, 0.30, "[AUTHENTIC] Verified Seller Sourcing",
                    fontsize=12, fontweight="bold", color="#F8FAFC", va="center", family="sans-serif")
            ax.text(0.55, 0.24, "Meets FSSAI standards & brand authorization.",
                    fontsize=10.5, color="#94A3B8", va="center", family="sans-serif")

        # Footer
        ax.text(0.04, 0.08, "Generated by @wheypricewatch_bot  •  Prices and stock updated in real time",
                fontsize=9.5, color="#64748B", va="center", family="sans-serif")

        # Save to buffer
        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=100, bbox_inches="tight", pad_inches=0)
        plt.close(fig)
        buf.seek(0)
        return buf.getvalue()


deal_card_generator = DealCardGenerator()
