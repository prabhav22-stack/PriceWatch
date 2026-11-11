"""Price history chart generator with headless Matplotlib."""

import asyncio
import io
from datetime import datetime, timezone
from typing import List, Optional

import matplotlib
# Use headless backend
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

from pricewatch.domain.models import CanonicalListing, PriceObservation
from pricewatch.logging_setup import get_logger

logger = get_logger("chart_service")


class ChartService:
    """Generates modern dark-themed price history charts as in-memory PNGs."""

    @classmethod
    async def generate_price_history_chart_async(
        cls,
        listing: CanonicalListing,
        observations: List[PriceObservation],
        target_price_paise: Optional[int] = None,
    ) -> Optional[bytes]:
        """
        Asynchronously generate a price history chart by offloading heavy
        Matplotlib rendering to a worker thread to keep the event loop unblocked.
        """
        return await asyncio.to_thread(
            cls.generate_price_history_chart,
            listing=listing,
            observations=observations,
            target_price_paise=target_price_paise,
        )

    @staticmethod
    def generate_quickchart_url(
        listing: CanonicalListing,
        observations: List[PriceObservation],
        target_price_paise: Optional[int] = None,
    ) -> Optional[str]:
        """
        Generate a hosted QuickChart.io URL for instant, zero-CPU chart rendering.
        Telegram servers fetch and render the image directly, requiring 0MB RAM on Render.
        """
        valid_obs = [
            o for o in observations
            if o.price_paise is not None and o.observed_at is not None
        ]
        if not valid_obs and listing.last_price_paise is not None:
            valid_obs = [
                PriceObservation(
                    listing_id=listing.id or 0,
                    price_paise=listing.last_price_paise,
                    available=True,
                    extraction_method="current",
                    observed_at=datetime.now(timezone.utc),
                )
            ]
        if not valid_obs:
            return None

        valid_obs.sort(key=lambda o: o.observed_at)
        labels = [o.observed_at.strftime("%d %b") for o in valid_obs][-15:]
        data = [round(o.price_paise / 100.0, 2) for o in valid_obs][-15:]

        import json
        import urllib.parse

        chart_config = {
            "type": "line",
            "data": {
                "labels": labels,
                "datasets": [
                    {
                        "label": "Price (₹)",
                        "data": data,
                        "borderColor": "#38bdf8",
                        "backgroundColor": "rgba(56, 189, 248, 0.2)",
                        "fill": True,
                        "tension": 0.3,
                    }
                ],
            },
            "options": {
                "legend": {"labels": {"fontColor": "#f8fafc"}},
                "scales": {
                    "yAxes": [{"ticks": {"fontColor": "#94a3b8"}}],
                    "xAxes": [{"ticks": {"fontColor": "#94a3b8"}}],
                },
            },
        }
        encoded = urllib.parse.quote(json.dumps(chart_config))
        return f"https://quickchart.io/chart?c={encoded}&bkg=%230f172a&w=600&h=320"

    @staticmethod
    def generate_price_history_chart(
        listing: CanonicalListing,
        observations: List[PriceObservation],
        target_price_paise: Optional[int] = None,
    ) -> Optional[bytes]:
        """
        Generate a modern dark-themed line chart showing price fluctuations.
        Returns bytes buffer of the PNG image, or None if insufficient data.
        """
        # Filter valid observations with price
        valid_obs = [
            o for o in observations
            if o.price_paise is not None and o.observed_at is not None
        ]

        # If empty but listing has a last_price, synthesize a single data point
        if not valid_obs and listing.last_price_paise is not None:
            valid_obs = [
                PriceObservation(
                    listing_id=listing.id or 0,
                    price_paise=listing.last_price_paise,
                    available=True,
                    extraction_method="current",
                    observed_at=datetime.now(timezone.utc),
                )
            ]

        if not valid_obs:
            return None

        # Sort by timestamp
        valid_obs.sort(key=lambda o: o.observed_at)

        timestamps = [o.observed_at for o in valid_obs]
        prices_rs = [(o.price_paise / 100.0) for o in valid_obs]

        # If only 1 observation, duplicate point 1 hour earlier to draw a baseline
        if len(timestamps) == 1:
            from datetime import timedelta
            timestamps = [timestamps[0] - timedelta(hours=1), timestamps[0]]
            prices_rs = [prices_rs[0], prices_rs[0]]

        # Setup figure with dark modern theme
        fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150)
        fig.patch.set_facecolor("#0f172a")  # Dark slate background
        ax.set_facecolor("#1e293b")        # Panel background

        # Plot line and fill gradient
        ax.plot(
            timestamps,
            prices_rs,
            color="#38bdf8",  # Electric sky blue
            linewidth=2.5,
            marker="o",
            markersize=5,
            markerfacecolor="#0284c7",
            markeredgecolor="#ffffff",
            markeredgewidth=1.2,
            zorder=4,
        )
        ax.fill_between(
            timestamps,
            prices_rs,
            color="#38bdf8",
            alpha=0.15,
            zorder=3,
        )

        # Highlight minimum price (All-time low in dataset)
        min_price = min(prices_rs)
        min_idx = prices_rs.index(min_price)
        min_time = timestamps[min_idx]
        ax.scatter(
            [min_time],
            [min_price],
            color="#22c55e",  # Vibrant green
            s=80,
            zorder=5,
            edgecolors="#ffffff",
            linewidth=1.5,
        )
        ax.annotate(
            f"Low: ₹{min_price:,.0f}",
            (min_time, min_price),
            textcoords="offset points",
            xytext=(0, -18),
            ha="center",
            fontsize=8.5,
            fontweight="bold",
            color="#4ade80",
            bbox=dict(boxstyle="round,pad=0.2", fc="#0f172a", ec="#22c55e", lw=1),
            zorder=6,
        )

        # Highlight current / latest price
        latest_price = prices_rs[-1]
        latest_time = timestamps[-1]
        ax.scatter(
            [latest_time],
            [latest_price],
            color="#f59e0b",  # Amber
            s=80,
            zorder=5,
            edgecolors="#ffffff",
            linewidth=1.5,
        )
        ax.annotate(
            f"Now: ₹{latest_price:,.0f}",
            (latest_time, latest_price),
            textcoords="offset points",
            xytext=(0, 10),
            ha="center",
            fontsize=8.5,
            fontweight="bold",
            color="#fbbf24",
            bbox=dict(boxstyle="round,pad=0.2", fc="#0f172a", ec="#f59e0b", lw=1),
            zorder=6,
        )

        # Formatting titles and axes
        title_trunc = listing.product_title[:45] + ("..." if len(listing.product_title) > 45 else "")
        ax.set_title(
            f"Price History: {title_trunc}",
            fontsize=11,
            fontweight="bold",
            color="#f8fafc",
            pad=14,
        )

        ax.grid(True, linestyle="--", alpha=0.2, color="#94a3b8")
        ax.tick_params(colors="#94a3b8", labelsize=8)

        # X-axis date formatter
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b\n%H:%M", tz=timezone.utc))
        fig.autofmt_xdate(rotation=0, ha="center")

        # Y-axis INR currency formatter
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda val, loc: f"₹{val:,.0f}"))

        # Target price threshold line if provided
        if target_price_paise and target_price_paise > 0:
            target_rs = target_price_paise / 100.0
            ax.axhline(
                y=target_rs,
                color="#f43f5e",  # Rose red target line
                linestyle=":",
                linewidth=1.8,
                alpha=0.85,
                zorder=2,
            )
            ax.text(
                timestamps[0],
                target_rs,
                f" Target: ₹{target_rs:,.0f}",
                color="#fb7185",
                fontsize=8,
                fontweight="bold",
                va="bottom",
            )

        # Spines
        for spine in ax.spines.values():
            spine.set_color("#334155")

        plt.tight_layout()

        # Render to in-memory bytes
        buf = io.BytesIO()
        plt.savefig(buf, format="png", facecolor=fig.get_facecolor(), edgecolor="none")
        plt.close(fig)
        buf.seek(0)
        return buf.getvalue()
